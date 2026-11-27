
#ifndef COM_H
#define COM_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32c0xx_hal.h"
#include "tactile_sense.h"
#include <stdint.h>

#define SENSOR_BOARD_ID             10U

#define COM_FRAME_HEADER_SIZE       2U
#define COM_BOARD_ID_SIZE           1U
#define COM_COUNTER_SIZE            2U
#define COM_ADC_DATA_SIZE           (TACTILE_POINT_NUM * 2U)
#define COM_CHECKSUM_SIZE           2U

#define COM_POLL_FRAME_SIZE         5U
#define COM_DATA_FRAME_SIZE        (COM_FRAME_HEADER_SIZE +        \
                                    COM_BOARD_ID_SIZE     +        \
                                    COM_COUNTER_SIZE      +        \
                                    COM_ADC_DATA_SIZE     +        \
                                    COM_CHECKSUM_SIZE)

/**
 * @brief 初始化串口通信模块
 *
 * 初始化后：
 * 1. USART保持接收轮询命令
 * 2. TX引脚进入高阻状态
 * 3. 只有收到匹配本机ID的命令后才允许发送
 *
 * @param huart USART外设句柄  board_id 传感板id
 * @return HAL_StatusTypeDef
 */
HAL_StatusTypeDef COM_Init(
    UART_HandleTypeDef *huart,
    uint8_t board_id,
    const uint16_t initial_data[TACTILE_POINT_NUM]);

/* Retry failed reception and release TX if a response stalls. */
void COM_Process(void);

/**
 * @brief 发布最新完整扫描；轮询响应在UART接收回调中立即启动。
 * @param adc_data 36个已换算的触觉值
 */
void COM_UpdateTactileData(const uint16_t adc_data[TACTILE_POINT_NUM]);

/**
 * @brief UART DMA接收事件处理
 */
void COM_UART_RxEventCallback(UART_HandleTypeDef *huart, uint16_t size);

/**
 * @brief UART DMA transmit completion; called after the final stop bit.
 */
void COM_UART_TxCpltCallback(UART_HandleTypeDef *huart);

/**
 * @brief UART错误恢复
 */
void COM_UART_ErrorCallback(UART_HandleTypeDef *huart);

uint32_t COM_GetPollCount(void);
uint32_t COM_GetTransmitCount(void);
uint32_t COM_GetChecksumErrorCount(void);

#ifdef __cplusplus
}
#endif

#endif