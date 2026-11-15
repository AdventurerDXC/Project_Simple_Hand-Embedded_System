/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __DRV8213_DRIVER_H
#define __DRV8213_DRIVER_H
/* =================================================================================
File name:       __DRV8213_DRIVER_H
Author: Mr.NoFish
===================================================================================*/

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/

#include "main.h"

#define DRV8213_VIO 3300.0f // mV
#define DRV8213_RES 1000.0f // Ω

#define DRV8213_GS_LOW 205
#define DRV8213_GS_HIGH_Z 1050
#define DRV8213_GS_HIGH 4900


typedef struct DRV8213_Driver_ DRV8213_Driver;

typedef enum
{
  GS_PIN_LOW = 0U,
  GS_PIN_HIGH_Z,
  GS_PIN_HIGH
} GS_PinState;

struct DRV8213_Driver_
{
	
	//drv8213 interface
	TIM_HandleTypeDef* htim;
	uint32_t TIM_CHANNEL_A;
	uint32_t TIM_CHANNEL_B;
	
	GPIO_TypeDef* GPIOx;
	uint32_t GPIO_Pin;
	
	//交互寄存器
	volatile uint16_t* adc_buf; //电流采样值
	
	//状态寄存器
	float32_t gainsel[3];
	uint8_t gainsel_pin_state;
	
	float32_t* Ud; //电压占空比设定值，-1到1
	float32_t* Ip; //电流测量峰值
    float32_t  Ip_; //上一时刻电流测量峰值
    float32_t* Iavg;//电流测量平均值值
};
	
DRV8213_Driver* new_DRV8213_Driver(
		TIM_HandleTypeDef* htim, uint32_t TIM_CHANNEL_A,	uint32_t TIM_CHANNEL_B,
		GPIO_TypeDef* GPIOx, uint32_t GPIO_Pin);

HAL_StatusTypeDef delete_DRV8213_Driver(DRV8213_Driver* hdev);

HAL_StatusTypeDef DRV8213_Driver_Init(DRV8213_Driver* hdev, volatile uint16_t* adc_buf, 
                                      float32_t* Ud, float32_t* Ip, float32_t* Iavg);

HAL_StatusTypeDef DRV8213_Driver_Get(DRV8213_Driver* hdev, float32_t* It);
HAL_StatusTypeDef DRV8213_GS_WritePin(DRV8213_Driver* hdev, GS_PinState PinState);
HAL_StatusTypeDef DRV8213_Driver_Write(DRV8213_Driver* hdev, float32_t* Ud);

#endif
