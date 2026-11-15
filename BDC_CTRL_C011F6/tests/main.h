#ifndef TEST_MAIN_H
#define TEST_MAIN_H
#include <stdint.h>
#include <stddef.h>
typedef float float32_t;
typedef struct { int unused; } UART_HandleTypeDef;
typedef enum { HAL_OK, HAL_ERROR, HAL_BUSY, HAL_TIMEOUT } HAL_StatusTypeDef;
uint32_t HAL_GetTick(void);
HAL_StatusTypeDef HAL_UARTEx_ReceiveToIdle_DMA(UART_HandleTypeDef *, uint8_t *, uint16_t);
HAL_StatusTypeDef HAL_UART_Transmit_IT(UART_HandleTypeDef *, uint8_t *, uint16_t);
#endif
