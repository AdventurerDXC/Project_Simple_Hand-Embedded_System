#include "com.h"
#include "main.h"
#include <stddef.h>
#include "gpio.h"

/* ===================== 引脚配置 ===================== */
#define COM_TX_GPIO_PORT       USART_TX_GPIO_Port
#define COM_TX_GPIO_PIN        USART_TX_Pin
#define COM_TX_GPIO_AF         GPIO_AF0_USART1

/* ===================== 查询协议 ===================== */
#define COM_POLL_HEADER_0       0xAAU
#define COM_POLL_HEADER_1       0x55U
#define COM_POLL_CMD_READ       0x01U

/* ===================== 数据协议 ===================== */
#define COM_FRAME_HEADER_0          0xFFU
#define COM_FRAME_HEADER_1          0x66U

#define COM_HEADER_INDEX            0U
#define COM_BOARD_ID_INDEX          2U
#define COM_COUNTER_INDEX           3U
#define COM_ADC_DATA_INDEX          5U
#define COM_CHECKSUM_INDEX          77U

static UART_HandleTypeDef *s_huart = NULL;

static uint8_t s_board_id = 0U;

static uint8_t s_poll_rx_frame[COM_POLL_FRAME_SIZE];
static uint8_t s_tx_frame[3][COM_DATA_FRAME_SIZE];
static volatile uint8_t s_active_force_buffer = 0U;
static volatile uint8_t s_tx_buffer_index = 0xFFU;
static volatile uint8_t s_tx_busy = 0U;

static volatile uint16_t s_frame_counter = 0U;

static volatile uint32_t s_poll_count = 0U;
static volatile uint32_t s_transmit_count = 0U;
static volatile uint32_t s_checksum_error_count = 0U;

/* ===================== 私有函数声明 ===================== */
static uint8_t COM_CheckPollFrame(const uint8_t *frame);

static void COM_BuildTactileFrame(
    uint8_t *frame,
    const uint16_t adc_data[TACTILE_POINT_NUM]);

static void COM_RefreshFrameCounter(uint8_t *frame);

static uint16_t COM_CalculateChecksum(const uint8_t *data, uint16_t length);

static void COM_SetTxAlternateFunction(void);

static void COM_SetTxHighImpedance(void);

static HAL_StatusTypeDef COM_StartPollReception(void);

/**
 * @brief 初始化串口通信模块
 */
HAL_StatusTypeDef COM_Init(
    UART_HandleTypeDef *huart,
    uint8_t board_id,
    const uint16_t initial_data[TACTILE_POINT_NUM])
{
    uint8_t buffer_index;

    if ((huart == NULL) || (initial_data == NULL))
        return HAL_ERROR;

    s_huart = huart;
    s_board_id = board_id;
    
    s_frame_counter = 0U;
    s_active_force_buffer = 0U;
    s_tx_buffer_index = 0xFFU;
    s_tx_busy = 0U;
    s_poll_count = 0U;
    s_transmit_count = 0U;
    s_checksum_error_count = 0U;

    /* Prepare a valid cached response before enabling RX DMA. */
    for (buffer_index = 0U; buffer_index < 3U; buffer_index++)
        COM_BuildTactileFrame(s_tx_frame[buffer_index], initial_data);
    
    /*
     * 未被轮询时，TX必须处于高阻状态。
     * 仅“不调用HAL_UART_Transmit”是不够的，
     * 因为USART TX空闲时仍会推挽输出高电平。
     */
    COM_SetTxHighImpedance();

    return COM_StartPollReception();
}

/**
 * @brief Publish the latest complete scan for use by the UART ISR.
 */
void COM_UpdateTactileData(const uint16_t adc_data[TACTILE_POINT_NUM])
{
    uint8_t build_buffer;

    if ((s_huart == NULL) || (adc_data == NULL))
        return;

    for (build_buffer = 0U; build_buffer < 3U; build_buffer++)
    {
        if ((build_buffer != s_active_force_buffer) &&
            (build_buffer != s_tx_buffer_index))
            break;
    }

    if (build_buffer >= 3U)
        return;

    COM_BuildTactileFrame(s_tx_frame[build_buffer], adc_data);

    /* Publish the completed frame atomically with respect to the UART ISR. */
    __DMB();
    __disable_irq();
    s_active_force_buffer = build_buffer;
    __enable_irq();
}

/* ===================== UART回调 ===================== */
void COM_UART_RxEventCallback(UART_HandleTypeDef *huart, uint16_t size)
{
    if ((s_huart == NULL) || (huart == NULL) ||
        (huart->Instance != s_huart->Instance))
        return;

    if ((size == COM_POLL_FRAME_SIZE) &&
        (COM_CheckPollFrame(s_poll_rx_frame) != 0U))
    {
        s_poll_count++;

        if ((s_poll_rx_frame[2] == COM_POLL_CMD_READ) &&
            (s_poll_rx_frame[3] == s_board_id))
        {
            uint8_t active_buffer = s_active_force_buffer;

            if ((s_tx_busy != 0U) ||
                (active_buffer == s_tx_buffer_index))
                return;

            /* DMA owns the published frame until UART TC. */
            COM_RefreshFrameCounter(s_tx_frame[active_buffer]);
            COM_SetTxAlternateFunction();
            s_tx_busy = 1U;
            s_tx_buffer_index = active_buffer;

            if (HAL_UART_Transmit_DMA(
                    s_huart,
                    s_tx_frame[active_buffer],
                    COM_DATA_FRAME_SIZE) != HAL_OK)
            {
                s_tx_busy = 0U;
                s_tx_buffer_index = 0xFFU;
                COM_SetTxHighImpedance();
                (void)COM_StartPollReception();
            }
            else
            {
                s_frame_counter++;
            }
            return;
        }
    }
    else
        s_checksum_error_count++;

    /* Non-target or invalid fixed-length request: receive the next poll. */
    (void)COM_StartPollReception();
}

void COM_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
    if ((s_huart == NULL) || (huart == NULL) ||
        (huart->Instance != s_huart->Instance) ||
        (s_tx_busy == 0U))
        return;

    /* HAL calls this after UART TC, not merely DMA memory completion. */
    COM_SetTxHighImpedance();
    s_tx_busy = 0U;
    s_tx_buffer_index = 0xFFU;
    s_transmit_count++;

    (void)COM_StartPollReception();
}

void COM_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    if ((s_huart == NULL) || (huart == NULL) ||
        (huart->Instance != s_huart->Instance))
        return;

    (void)HAL_UART_DMAStop(s_huart);
    s_tx_busy = 0U;
    s_tx_buffer_index = 0xFFU;
    COM_SetTxHighImpedance();
    (void)COM_StartPollReception();
}

static HAL_StatusTypeDef COM_StartPollReception(void)
{
    HAL_StatusTypeDef status = HAL_UARTEx_ReceiveToIdle_DMA(
        s_huart,
        s_poll_rx_frame,
        COM_POLL_FRAME_SIZE);

    return status;
}

static uint8_t COM_CheckPollFrame(const uint8_t *frame)
{
    uint16_t sum;
    uint8_t checksum;

    if (frame == NULL)
        return 0U;

    if ((frame[0] != COM_POLL_HEADER_0) ||
        (frame[1] != COM_POLL_HEADER_1))
        return 0U;

    sum =
        (uint16_t)frame[0] +
        (uint16_t)frame[1] +
        (uint16_t)frame[2] +
        (uint16_t)frame[3];

    checksum = (uint8_t)(sum & 0xFFU);

    return (checksum == frame[4]) ? 1U : 0U;
}

/**
 * @brief 生成完整的79字节触觉数据帧
 */
static void COM_BuildTactileFrame(
    uint8_t *frame,
    const uint16_t adc_data[TACTILE_POINT_NUM])
{
    uint8_t point;
    uint8_t data_index;
    uint16_t checksum;

    /* 帧头。*/
    frame[COM_HEADER_INDEX] = COM_FRAME_HEADER_0;
    frame[COM_HEADER_INDEX + 1U] = COM_FRAME_HEADER_1;

    frame[COM_BOARD_ID_INDEX] = s_board_id;
    
    /* 帧计数器，高字节在前。*/
    frame[COM_COUNTER_INDEX] = (uint8_t)((s_frame_counter >> 8U) & 0xFFU);
    frame[COM_COUNTER_INDEX + 1U] = (uint8_t)(s_frame_counter & 0xFFU);

    /* 写入36个ADC值。
     * 每个ADC值占2字节，高字节在前。*/
    for (point = 0U; point < TACTILE_POINT_NUM; point++)
    {
        data_index = (uint8_t)(COM_ADC_DATA_INDEX + point * 2U);

        frame[data_index] = (uint8_t)((adc_data[point] >> 8U) & 0xFFU);
        frame[data_index + 1U] = (uint8_t)(adc_data[point] & 0xFFU);
    }

    /* 校验和包括Byte 0~76，
     * 不包括校验和自身的Byte 77~78 */
    checksum = COM_CalculateChecksum(frame, COM_CHECKSUM_INDEX);

    frame[COM_CHECKSUM_INDEX] = (uint8_t)((checksum >> 8U) & 0xFFU);
    frame[COM_CHECKSUM_INDEX + 1U] = (uint8_t)(checksum & 0xFFU);
}

/**
 * @brief 计算16位累加校验和
 *
 * 所有字节直接相加，
 * 最终保留累加结果的低16位。
 */
static uint16_t COM_CalculateChecksum(const uint8_t *data, uint16_t length)
{
    uint16_t index;
    uint32_t checksum_sum = 0U;

    if (data == NULL)
        return 0U;

    for (index = 0U; index < length; index++)
        checksum_sum += data[index];

    return (uint16_t)(checksum_sum & 0xFFFFU);
}

static void COM_RefreshFrameCounter(uint8_t *frame)
{
    uint16_t checksum;

    frame[COM_COUNTER_INDEX] = (uint8_t)((s_frame_counter >> 8U) & 0xFFU);
    frame[COM_COUNTER_INDEX + 1U] = (uint8_t)(s_frame_counter & 0xFFU);
    checksum = COM_CalculateChecksum(frame, COM_CHECKSUM_INDEX);
    frame[COM_CHECKSUM_INDEX] = (uint8_t)((checksum >> 8U) & 0xFFU);
    frame[COM_CHECKSUM_INDEX + 1U] = (uint8_t)(checksum & 0xFFU);
}

/* ===================== TX三态控制 ===================== */
static void COM_SetTxAlternateFunction(void)
{
    GPIO_InitTypeDef gpio_init = {0};

    gpio_init.Pin = COM_TX_GPIO_PIN;
    gpio_init.Mode = GPIO_MODE_AF_PP;
    gpio_init.Pull = GPIO_NOPULL;
    gpio_init.Speed = GPIO_SPEED_FREQ_HIGH;
    gpio_init.Alternate = COM_TX_GPIO_AF;

    HAL_GPIO_Init(COM_TX_GPIO_PORT, &gpio_init);
}

static void COM_SetTxHighImpedance(void)
{
    GPIO_InitTypeDef gpio_init = {0};

    /* Analog模式会关闭数字输入缓冲，
     * 可作为较干净的高阻状态。*/
    gpio_init.Pin = COM_TX_GPIO_PIN;
    gpio_init.Mode = GPIO_MODE_ANALOG;
    gpio_init.Pull = GPIO_NOPULL;

    HAL_GPIO_Init(COM_TX_GPIO_PORT, &gpio_init);
}

/* ===================== 统计接口 ===================== */
uint32_t COM_GetPollCount(void)
{
    return s_poll_count;
}

uint32_t COM_GetTransmitCount(void)
{
    return s_transmit_count;
}

uint32_t COM_GetChecksumErrorCount(void)
{
    return s_checksum_error_count;
}