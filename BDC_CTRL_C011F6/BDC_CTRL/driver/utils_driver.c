/* =================================================================================
File name:       __UTILS_DRIVER_C
Author: Mr.NoFish
===================================================================================*/
#include "utils_driver.h"

/*
 * NTC 分压 ADC 查表，数组下标 i 对应温度：i * 5 °C。
 * 电路模型：3.3 V -- 10 kΩ NTC -- TEMP_ADC -- 10 kΩ -- GND。
 * 温度升高时 NTC 阻值下降、TEMP_ADC 的 ADC 码值上升。相邻点间执行线性插值，
 * 对 1 Hz 的板温监测已经足够，且不再链接/执行庞大的浮点 log() 库。
 */
static const uint16_t s_ntc_adc_table[NTC_TEMP_TABLE_COUNT] =
{
	1070U, 1256U, 1450U, 1649U, 1850U, 2048U, 2239U,
	2420U, 2591U, 2748U, 2893U, 3024U, 3141U, 3247U,
	3341U, 3424U, 3498U, 3563U, 3620U, 3671U, 3715U
};

UTILS_Driver* new_util_Driver(void)
{
	static UTILS_Driver driver;
	return &driver;
}

HAL_StatusTypeDef UTILS_Driver_InitTemp(UTILS_Driver* hdev, volatile uint16_t* adc_buf_temp, float32_t* bdc_temp)
{
	if ((adc_buf_temp == NULL) || (bdc_temp == NULL))
	{
		return HAL_ERROR;
	}
	hdev->adc_buf_temp = adc_buf_temp;
	hdev->bdc_temp = bdc_temp;

	/* 未获得第一笔 ADC 数据前，以室温作为安全且确定的初始遥测值。 */
	*hdev->bdc_temp = 25.0f;
    
	return HAL_OK;
}

HAL_StatusTypeDef UTILS_Driver_GetTemp(UTILS_Driver* hdev, float32_t* bdc_temp)
{
	uint16_t adc_raw;
	uint8_t index;
	uint16_t adc_high;
	uint16_t adc_low;
	uint32_t temperature_tenth_c;

	if ((hdev == NULL) || (hdev->adc_buf_temp == NULL) || (hdev->bdc_temp == NULL))
	{
		return HAL_ERROR;
	}

	/* DMA 异步更新 ADC 缓冲；只读取一次，保证本次换算使用同一原始码值。 */
	adc_raw = *hdev->adc_buf_temp;

	/* 超出标定范围时饱和，避免除零或外推到不可信的温度。 */
	if (adc_raw <= s_ntc_adc_table[0])
	{
		temperature_tenth_c = NTC_TEMP_MIN_C * 10U;
	}
	else if (adc_raw >= s_ntc_adc_table[NTC_TEMP_TABLE_COUNT - 1U])
	{
		temperature_tenth_c = NTC_TEMP_MAX_C * 10U;
	}
	else
	{
		/* 找到 adc_low <= adc_raw <= adc_high 的 5 °C 区间。 */
		for (index = 0U; index < (NTC_TEMP_TABLE_COUNT - 1U); index++)
		{
			if (adc_raw <= s_ntc_adc_table[index + 1U])
			{
				break;
			}
		}

		adc_low = s_ntc_adc_table[index];
		adc_high = s_ntc_adc_table[index + 1U];

		/*
		 * 全程采用整数计算并四舍五入到 0.1 °C：
		 * T = T_low + 5 * (ADC - ADC_low) / (ADC_high - ADC_low)。
		 */
		temperature_tenth_c = ((uint32_t)(NTC_TEMP_MIN_C + index * NTC_TEMP_STEP_C) * 10U) +
			(((uint32_t)(adc_raw - adc_low) * NTC_TEMP_STEP_C * 10U +
			  (uint32_t)(adc_high - adc_low) / 2U) /
			 (uint32_t)(adc_high - adc_low));
	}

	/* 仅在最后一步转换为 float，以兼容已有温度遥测接口。 */
	*hdev->bdc_temp = (float32_t)temperature_tenth_c * 0.1f;
	
    if(bdc_temp != NULL)
        *bdc_temp = *hdev->bdc_temp;
    
	return HAL_OK;
}

HAL_StatusTypeDef UTILS_Driver_InitVolt(UTILS_Driver* hdev, volatile uint16_t* adc_buf_volt, float32_t* bdc_volt)
{
	if ((adc_buf_volt == NULL) || (bdc_volt == NULL))
	{
		return HAL_ERROR;
	}
	hdev->adc_buf_volt = adc_buf_volt;
	hdev->bdc_volt = bdc_volt;

	*hdev->bdc_volt = 0.0f;
    
	return HAL_OK;
}

HAL_StatusTypeDef UTILS_Driver_GetVolt(UTILS_Driver* hdev, float32_t* bdc_volt)
{
	if ((hdev == NULL) || (hdev->adc_buf_volt == NULL) || (hdev->bdc_volt == NULL))
	{
		return HAL_ERROR;
	}

	*hdev->bdc_volt = (float32_t)(*hdev->adc_buf_volt) * util_VIO * util_RES / 0xfff;
    
    if(bdc_volt != NULL)
        *bdc_volt = *hdev->bdc_volt;
	
	return HAL_OK;
}

