#ifndef TACTILE_BRIDGE_H
#define TACTILE_BRIDGE_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32f4xx_hal.h"
#include <stdint.h>

#define TACTILE_BOARD_COUNT       12U
#define TACTILE_DATA_FRAME_SIZE   79U

HAL_StatusTypeDef TactileBridge_Init(
    UART_HandleTypeDef *huart);

void TactileBridge_Process(void);

void TactileBridge_TIM_PeriodElapsedCallback(
    TIM_HandleTypeDef *htim);

void TactileBridge_UART_RxEventCallback(
    UART_HandleTypeDef *huart, uint16_t size);

void TactileBridge_UART_ErrorCallback(
    UART_HandleTypeDef *huart);

uint32_t TactileBridge_GetValidFrameCount(void);
uint32_t TactileBridge_GetTimeoutCount(void);
uint32_t TactileBridge_GetUnexpectedFrameCount(void);

#ifdef __cplusplus
}
#endif

#endif