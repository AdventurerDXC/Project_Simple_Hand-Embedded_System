#include "tactile_bridge.h"

#include "usb_device.h"
#include "tim.h"
#include "usbd_cdc_if.h"
#include "usbd_cdc.h"

#include <stddef.h>
#include <string.h>
#include <stdint.h>

extern USBD_HandleTypeDef hUsbDeviceFS;

/* ===================== 传感板列表 ===================== */

static const uint8_t s_board_ids[TACTILE_BOARD_COUNT] =
{
    0U, 1U, 2U, 3U, 4U, 5U,
    6U, 7U, 8U, 9U, 10U, 11U
};

/* TIM1 starts a 50 ms round; TIM2 schedules one board every 4 ms. */

/* ===================== 轮询命令 ===================== */

#define POLL_FRAME_SIZE             5U
#define RX_DMA_SIZE                 256U
#define POLL_HEADER_0               0xAAU
#define POLL_HEADER_1               0x55U
#define POLL_CMD_READ               0x01U

/* ===================== 数据帧 ===================== */

#define DATA_HEADER_0               0xFFU
#define DATA_HEADER_1               0x66U

#define DATA_BOARD_ID_INDEX         2U
#define DATA_CHECKSUM_INDEX         77U

/* ===================== USB队列 ===================== */

#define FRAME_QUEUE_CAPACITY        8U
#define FRAME_QUEUE_SLOT_NUM        (FRAME_QUEUE_CAPACITY + 1U)

typedef enum
{
    RX_WAIT_HEADER_FF = 0,
    RX_WAIT_HEADER_66,
    RX_RECEIVE_FRAME
} BridgeRxStateTypeDef;

static UART_HandleTypeDef *s_huart = NULL;

/* UART circular RX DMA and persistent TX buffer. */
static uint8_t s_rx_dma[RX_DMA_SIZE];
static uint16_t s_rx_dma_position = 0U;
static volatile uint8_t s_rx_restart_needed = 0U;
static uint8_t s_poll_tx_frame[POLL_FRAME_SIZE];

static uint8_t s_rx_frame[TACTILE_DATA_FRAME_SIZE];
static volatile uint16_t s_rx_index = 0U;
static volatile BridgeRxStateTypeDef s_rx_state = RX_WAIT_HEADER_FF;

/* USB发送队列 */
static uint8_t s_frame_queue
    [FRAME_QUEUE_SLOT_NUM]
    [TACTILE_DATA_FRAME_SIZE];

static volatile uint8_t s_queue_head = 0U;
static volatile uint8_t s_queue_tail = 0U;

static uint8_t s_usb_tx_buffer[TACTILE_DATA_FRAME_SIZE];

/* 轮询状态 */
static volatile uint8_t s_round_active = 0U;
static volatile uint8_t s_waiting_response = 0U;
static volatile uint8_t s_response_received = 0U;

static uint8_t s_poll_index = 0U;
static uint8_t s_expected_board_id = 0U;

static volatile uint32_t s_round_overrun_count = 0U;
static volatile uint32_t s_poll_tx_error_count = 0U;

/* 统计 */
static volatile uint32_t s_valid_frame_count = 0U;
static volatile uint32_t s_timeout_count = 0U;
static volatile uint32_t s_checksum_error_count = 0U;
static volatile uint32_t s_unexpected_frame_count = 0U;
static volatile uint32_t s_dropped_frame_count = 0U;

/* ===================== 私有函数声明 ===================== */

static void Bridge_ProcessUSB(void);
static HAL_StatusTypeDef Bridge_StartReceive(void);
static HAL_StatusTypeDef Bridge_SendPoll(uint8_t board_id);
static void Bridge_BeginRound(void);
static void Bridge_SendNextSlot(void);
static void Bridge_CheckPreviousResponse(void);

static void Bridge_ResetParser(void);
static void Bridge_ParseByte(uint8_t data);

static uint8_t Bridge_CheckDataFrame(const uint8_t *frame);

static uint16_t Bridge_Checksum16(const uint8_t *data, uint16_t length);

static uint8_t Bridge_QueueNext(uint8_t index);
static uint8_t Bridge_QueuePushFromISR(const uint8_t *frame);

static uint8_t Bridge_USBReady(void);

/* ===================== 初始化 ===================== */

HAL_StatusTypeDef TactileBridge_Init(UART_HandleTypeDef *huart)
{
    if (huart == NULL)
        return HAL_ERROR;

    s_huart = huart;

    Bridge_ResetParser();

    s_queue_head = 0U;
    s_queue_tail = 0U;

    s_round_active = 0U;
    s_waiting_response = 0U;
    s_response_received = 0U;

    s_poll_index = 0U;
    s_expected_board_id = 0U;

    s_valid_frame_count = 0U;
    s_timeout_count = 0U;
    s_checksum_error_count = 0U;
    s_unexpected_frame_count = 0U;
    s_dropped_frame_count = 0U;

    s_round_overrun_count = 0U;
    s_poll_tx_error_count = 0U;

    if (Bridge_StartReceive() != HAL_OK)
        return HAL_ERROR;

    /* Start the first round immediately; TIM1 schedules subsequent rounds. */
    Bridge_BeginRound();

    /* TIM1 generates the 50 ms round boundary. */
    if (HAL_TIM_Base_Start_IT(&htim1) != HAL_OK)
        return HAL_ERROR;

    return HAL_OK;
}

/* ===================== 主循环 ===================== */
void TactileBridge_Process(void)
{
    if (s_rx_restart_needed != 0U)
        (void)Bridge_StartReceive();
    Bridge_ProcessUSB();
}

/* ===================== Timer-driven fixed-slot polling ===================== */
void TactileBridge_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
    if (htim == NULL)
        return;

    if (htim->Instance == TIM1)
    {
        if (s_round_active != 0U)
            s_round_overrun_count++;

        (void)HAL_TIM_Base_Stop_IT(&htim2);
        Bridge_CheckPreviousResponse();
        s_round_active = 0U;

        Bridge_BeginRound();
    }
    else if ((htim->Instance == TIM2) && (s_round_active != 0U))
    {
        Bridge_CheckPreviousResponse();
        if (s_poll_index >= TACTILE_BOARD_COUNT)
        {
            /* Final slot: check board 11's reply, then end this 48 ms sweep. */
            s_round_active = 0U;
            (void)HAL_TIM_Base_Stop_IT(&htim2);
            return;
        }

        Bridge_SendNextSlot();
    }
}

static void Bridge_BeginRound(void)
{
    s_round_active = 1U;
    __HAL_TIM_SET_COUNTER(&htim2, 0U);
    __HAL_TIM_CLEAR_FLAG(&htim2, TIM_FLAG_UPDATE);
    s_poll_index = 0U;
    Bridge_SendNextSlot();

    if (HAL_TIM_Base_Start_IT(&htim2) != HAL_OK)
    {
        s_round_active = 0U;
        s_poll_tx_error_count++;
    }
}

static void Bridge_SendNextSlot(void)
{
    if (s_poll_index >= TACTILE_BOARD_COUNT)
    {
        return;
    }

    s_expected_board_id = s_board_ids[s_poll_index];
    s_response_received = 0U;
    s_waiting_response = 1U;

    if ((s_rx_restart_needed != 0U) ||
        (Bridge_SendPoll(s_expected_board_id) != HAL_OK))
    {
        s_waiting_response = 0U;
        s_poll_tx_error_count++;
    }

    s_poll_index++;
}

static void Bridge_CheckPreviousResponse(void)
{
    if (s_waiting_response != 0U)
    {
        if (s_response_received == 0U)
        {
            s_timeout_count++;
            Bridge_ResetParser();
        }

        s_waiting_response = 0U;
        s_response_received = 0U;
    }
}

static HAL_StatusTypeDef Bridge_SendPoll(uint8_t board_id)
{
    uint16_t sum;

    if (s_huart->gState != HAL_UART_STATE_READY)
        return HAL_BUSY;

    s_poll_tx_frame[0] = POLL_HEADER_0;
    s_poll_tx_frame[1] = POLL_HEADER_1;
    s_poll_tx_frame[2] = POLL_CMD_READ;
    s_poll_tx_frame[3] = board_id;

    sum = (uint16_t)s_poll_tx_frame[0] +
          (uint16_t)s_poll_tx_frame[1] +
          (uint16_t)s_poll_tx_frame[2] +
          (uint16_t)s_poll_tx_frame[3];

    s_poll_tx_frame[4] = (uint8_t)(sum & 0xFFU);

    /* Keep the DMA source unchanged until the UART finishes transmission. */
    return HAL_UART_Transmit_DMA(
        s_huart,
        s_poll_tx_frame,
        POLL_FRAME_SIZE);
}

/* ===================== UART回调 ===================== */

static HAL_StatusTypeDef Bridge_StartReceive(void)
{
    HAL_StatusTypeDef status;
    uint32_t primask = __get_PRIMASK();
    __disable_irq();
    s_rx_dma_position = 0U;
    status = HAL_UARTEx_ReceiveToIdle_DMA(s_huart, s_rx_dma, RX_DMA_SIZE);
    s_rx_restart_needed = (status == HAL_OK) ? 0U : 1U;
    if (primask == 0U)
        __enable_irq();
    return status;
}

void TactileBridge_UART_RxEventCallback(UART_HandleTypeDef *huart, uint16_t size)
{
    uint16_t position;
    (void)size;
    if ((s_huart == NULL) || (huart != s_huart))
        return;

    position = RX_DMA_SIZE - (uint16_t)__HAL_DMA_GET_COUNTER(huart->hdmarx);
    if (position == RX_DMA_SIZE)
        position = 0U;
    while (s_rx_dma_position != position)
    {
        uint8_t byte = s_rx_dma[s_rx_dma_position++];
        if (s_rx_dma_position == RX_DMA_SIZE)
            s_rx_dma_position = 0U;
        Bridge_ParseByte(byte);
    }
}

void TactileBridge_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    if ((s_huart == NULL) || (huart != s_huart))
        return;

    Bridge_ResetParser();
    if (((huart->ErrorCode & HAL_UART_ERROR_DMA) != 0U) &&
        ((huart->gState != HAL_UART_STATE_READY) ||
         (huart->hdmatx->State != HAL_DMA_STATE_READY)))
    {
        (void)HAL_UART_AbortTransmit(huart);
        if (huart->hdmatx->State != HAL_DMA_STATE_READY)
            (void)HAL_DMA_Abort(huart->hdmatx);
        s_poll_tx_error_count++;
    }
    (void)HAL_UART_AbortReceive(huart);
    if (huart->hdmarx->State != HAL_DMA_STATE_READY)
        (void)HAL_DMA_Abort(huart->hdmarx);
    s_rx_restart_needed = 1U;
}
/* ===================== 数据帧解析 ===================== */
static void Bridge_ResetParser(void)
{
    s_rx_index = 0U;
    s_rx_state = RX_WAIT_HEADER_FF;
}

static void Bridge_ParseByte(uint8_t data)
{
    switch (s_rx_state)
    {
        case RX_WAIT_HEADER_FF:
        {
            if (data == DATA_HEADER_0)
            {
                s_rx_frame[0] = data;
                s_rx_state = RX_WAIT_HEADER_66;
            }

            break;
        }

        case RX_WAIT_HEADER_66:
        {
            if (data == DATA_HEADER_1)
            {
                s_rx_frame[1] = data;
                s_rx_index = 2U;
                s_rx_state = RX_RECEIVE_FRAME;
            }
            else if (data == DATA_HEADER_0)
                s_rx_frame[0] = data;
            else
                Bridge_ResetParser();

            break;
        }

        case RX_RECEIVE_FRAME:
        {
            if (s_rx_index < TACTILE_DATA_FRAME_SIZE)
            {
                s_rx_frame[s_rx_index] = data;
                s_rx_index++;
            }

            if (s_rx_index >= TACTILE_DATA_FRAME_SIZE)
            {
                if (Bridge_CheckDataFrame(s_rx_frame) != 0U)
                {
                    /*
                     * 只有当前正在轮询的ID才是有效响应。
                     */
                    if ((s_waiting_response != 0U) &&
                        (s_rx_frame[DATA_BOARD_ID_INDEX] ==
                         s_expected_board_id))
                    {
                        if (Bridge_QueuePushFromISR(s_rx_frame) != 0U)
                            s_valid_frame_count++;
                        else
                            s_dropped_frame_count++;

                        s_response_received = 1U;
                    }
                    else
                        s_unexpected_frame_count++;
                }
                else
                    s_checksum_error_count++;

                Bridge_ResetParser();
            }

            break;
        }

        default:
        {
            Bridge_ResetParser();
            break;
        }
    }
}

static uint8_t Bridge_CheckDataFrame(const uint8_t *frame)
{
    uint16_t calculated;
    uint16_t received;

    if (frame == NULL)
        return 0U;

    if ((frame[0] != DATA_HEADER_0) ||
        (frame[1] != DATA_HEADER_1))
        return 0U;

    calculated = Bridge_Checksum16(
        frame,
        DATA_CHECKSUM_INDEX);

    received =
        ((uint16_t)frame[77] << 8U) |
         (uint16_t)frame[78];

    return (calculated == received) ? 1U : 0U;
}

static uint16_t Bridge_Checksum16(const uint8_t *data, uint16_t length)
{
    uint16_t index;
    uint32_t sum = 0U;

    if (data == NULL)
        return 0U;

    for (index = 0U; index < length; index++)
        sum += data[index];

    return (uint16_t)(sum & 0xFFFFU);
}

/* ===================== USB发送 ===================== */

static void Bridge_ProcessUSB(void)
{
    uint8_t tail;
    uint8_t status;

    if (s_queue_tail == s_queue_head)
        return;

    if (Bridge_USBReady() == 0U)
        return;

    tail = s_queue_tail;

    memcpy(
        s_usb_tx_buffer,
        s_frame_queue[tail],
        TACTILE_DATA_FRAME_SIZE);

    status = CDC_Transmit_FS(
        s_usb_tx_buffer,
        TACTILE_DATA_FRAME_SIZE);

    if (status == USBD_OK)
    {
        __DMB();

        s_queue_tail = Bridge_QueueNext(tail);
    }
}

static uint8_t Bridge_USBReady(void)
{
    USBD_CDC_HandleTypeDef *cdc_handle;

    if (hUsbDeviceFS.dev_state != USBD_STATE_CONFIGURED)
        return 0U;

    if (hUsbDeviceFS.pClassData == NULL)
        return 0U;

    cdc_handle =
        (USBD_CDC_HandleTypeDef *)
        hUsbDeviceFS.pClassData;

    return (cdc_handle->TxState == 0U) ? 1U : 0U;
}

/* ===================== 环形队列 ===================== */

static uint8_t Bridge_QueueNext(uint8_t index)
{
    index++;

    if (index >= FRAME_QUEUE_SLOT_NUM)
        index = 0U;

    return index;
}

static uint8_t Bridge_QueuePushFromISR(const uint8_t *frame)
{
    uint8_t head;
    uint8_t next;

    if (frame == NULL)
        return 0U;

    head = s_queue_head;
    next = Bridge_QueueNext(head);

    if (next == s_queue_tail)
        return 0U;

    memcpy(
        s_frame_queue[head],
        frame,
        TACTILE_DATA_FRAME_SIZE);

    __DMB();

    s_queue_head = next;

    return 1U;
}

/* ===================== 统计 ===================== */

uint32_t TactileBridge_GetValidFrameCount(void)
{
    return s_valid_frame_count;
}

uint32_t TactileBridge_GetTimeoutCount(void)
{
    return s_timeout_count;
}

uint32_t TactileBridge_GetUnexpectedFrameCount(void)
{
    return s_unexpected_frame_count;
}