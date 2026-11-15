/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __UTILS_DRIVER_H
#define __UTILS_DRIVER_H
/* =================================================================================
File name:       __UTILS_DRIVER_H
Author: Mr.NoFish
===================================================================================*/

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/

#include "main.h"

#define util_VIO           3.3f                  // V
#define util_RES           (100.0f / 18.0f)      // kΩ

#define ntc_B             3380
#define ntc_T0             298

/*
 * NTC 查表范围与分辨率。
 * 查表由 10 kΩ / B=3380 / R25=10 kΩ 的原理图参数离线计算得出，
 * 可避免在 STM32C0 无 FPU 的运行时调用 log()。
 */
#define NTC_TEMP_MIN_C             0U
#define NTC_TEMP_MAX_C             100U
#define NTC_TEMP_STEP_C            5U
#define NTC_TEMP_TABLE_COUNT       (((NTC_TEMP_MAX_C - NTC_TEMP_MIN_C) / NTC_TEMP_STEP_C) + 1U)

typedef struct UTILS_Driver_ UTILS_Driver;


struct UTILS_Driver_
{
	volatile uint16_t* adc_buf_temp;
	volatile uint16_t* adc_buf_volt;
    
    float32_t* bdc_temp;
    float32_t* bdc_volt;

	TIM_HandleTypeDef* htim_led;
	uint32_t TIM_CHANNEL_led;
	
	
};
UTILS_Driver* new_util_Driver(void);

HAL_StatusTypeDef UTILS_Driver_InitTemp(UTILS_Driver* hdev, volatile uint16_t* adc_buf_temp, float32_t* bdc_temp);
HAL_StatusTypeDef UTILS_Driver_GetTemp(UTILS_Driver* hdev, float32_t* bdc_temp);

HAL_StatusTypeDef UTILS_Driver_InitVolt(UTILS_Driver* hdev, volatile uint16_t* adc_buf_volt, float32_t* bdc_volt);
HAL_StatusTypeDef UTILS_Driver_GetVolt(UTILS_Driver* hdev, float32_t* bdc_volt);


#endif
