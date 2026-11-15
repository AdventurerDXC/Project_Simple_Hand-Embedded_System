/* =================================================================================
File name:       __DRV8213_DRIVER_C
Author: Mr.NoFish
===================================================================================*/
#include "drv8213_driver.h"

DRV8213_Driver* new_DRV8213_Driver(
		TIM_HandleTypeDef* htim, uint32_t TIM_CHANNEL_A,	uint32_t TIM_CHANNEL_B,
		GPIO_TypeDef* GPIOx, uint32_t GPIO_Pin)
{
	static DRV8213_Driver driver;
	DRV8213_Driver* pObj = &driver;
	pObj->htim = htim;
	pObj->TIM_CHANNEL_A = TIM_CHANNEL_A;
	pObj->TIM_CHANNEL_B = TIM_CHANNEL_B;
	pObj->GPIOx = GPIOx;
	pObj->GPIO_Pin = GPIO_Pin;
	
	return pObj;				
}

HAL_StatusTypeDef DRV8213_Driver_Init(DRV8213_Driver* hdev, volatile uint16_t* adc_buf, 
                                      float32_t* Ud, float32_t* Ip, float32_t* Iavg)
{
	if ((adc_buf == NULL) || (Ud == NULL) || (Ip == NULL) || (Iavg == NULL))
	{
		return HAL_ERROR;
	}

	hdev->adc_buf = adc_buf;
	hdev->Ud = Ud;
	hdev->Ip = Ip;
	hdev->Iavg = Iavg;
	
	
	hdev->gainsel[GS_PIN_LOW] = DRV8213_VIO * 1000000 / 0xfff / DRV8213_RES / DRV8213_GS_LOW;
	hdev->gainsel[GS_PIN_HIGH_Z] = DRV8213_VIO * 1000000 / 0xfff / DRV8213_RES / DRV8213_GS_HIGH_Z;
	hdev->gainsel[GS_PIN_HIGH] = DRV8213_VIO * 1000000 / 0xfff / DRV8213_RES / DRV8213_GS_HIGH;
	
	hdev->gainsel_pin_state = GS_PIN_HIGH;
	DRV8213_GS_WritePin(hdev, hdev->gainsel_pin_state);
	return HAL_OK;
}

HAL_StatusTypeDef delete_DRV8213_Driver(DRV8213_Driver* hdev)
{
	(void)hdev;
	return HAL_OK;
}

HAL_StatusTypeDef DRV8213_Driver_Get(DRV8213_Driver* hdev, float32_t* Iavg)
{
    hdev->Ip_ = *hdev->Ip;
	*hdev->Ip = (float32_t)(*hdev->adc_buf) * hdev->gainsel[hdev->gainsel_pin_state];
	*hdev->Iavg = *hdev->Ip * *hdev->Ud;
    
    // 数字滤波器
    *hdev->Ip = 0.8**hdev->Ip + 0.2*hdev->Ip_;
    
    if(*hdev->Ip > 65 && hdev->gainsel_pin_state == GS_PIN_HIGH)
        hdev->gainsel_pin_state--;
    if(*hdev->Ip < 55 && hdev->gainsel_pin_state == GS_PIN_HIGH_Z)
        hdev->gainsel_pin_state++;

	DRV8213_GS_WritePin(hdev, hdev->gainsel_pin_state);
	
	if(Iavg != NULL)
		*Iavg = *hdev->Iavg;
	
	return HAL_OK;
}

HAL_StatusTypeDef DRV8213_GS_WritePin(DRV8213_Driver* hdev, GS_PinState PinState)
{
	GPIO_InitTypeDef GPIO_InitStruct = {0};

	GPIO_InitStruct.Pin = hdev->GPIO_Pin;
	GPIO_InitStruct.Pull = GPIO_NOPULL;      // 无上拉/下拉（浮空）
	
	switch(PinState)
	{
		case GS_PIN_LOW:
			GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP; // 输入模式
			HAL_GPIO_Init(hdev->GPIOx, &GPIO_InitStruct);
			HAL_GPIO_WritePin(hdev->GPIOx, hdev->GPIO_Pin, GPIO_PIN_RESET);
			break;
		
		case GS_PIN_HIGH_Z:
			GPIO_InitStruct.Mode = GPIO_MODE_INPUT; // 输入模式
			HAL_GPIO_Init(hdev->GPIOx, &GPIO_InitStruct);
			break;
		
		case GS_PIN_HIGH:
			GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP; // 输入模式
			HAL_GPIO_Init(hdev->GPIOx, &GPIO_InitStruct);
			HAL_GPIO_WritePin(hdev->GPIOx, hdev->GPIO_Pin, GPIO_PIN_SET);
			break;
	}
	
	return HAL_OK;
}

HAL_StatusTypeDef DRV8213_Driver_Write(DRV8213_Driver* hdev, float32_t* Ud)
{
	q15_t tmp;
	if(Ud != NULL)
		*hdev->Ud = *Ud;
	
	tmp = *hdev->Ud * hdev->htim->Init.Period;

	if(*hdev->Ud > 0)
	{
		__HAL_TIM_SetCompare(hdev->htim, hdev->TIM_CHANNEL_B, hdev->htim->Init.Period);
		__HAL_TIM_SetCompare(hdev->htim, hdev->TIM_CHANNEL_A, hdev->htim->Init.Period - tmp);
	}
	else
	{
		tmp = -tmp;
        __HAL_TIM_SetCompare(hdev->htim, hdev->TIM_CHANNEL_A, hdev->htim->Init.Period);
		__HAL_TIM_SetCompare(hdev->htim, hdev->TIM_CHANNEL_B, hdev->htim->Init.Period - tmp);
	}
	
	return HAL_OK;
}