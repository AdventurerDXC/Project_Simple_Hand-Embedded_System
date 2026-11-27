/* =================================================================================
File name:       __BDC_MOTOR_C
Author: Mr.NoFish, Adventurer
===================================================================================*/
#include "bdc_motor.h"

BDC_Motor* main_core;

volatile uint16_t adc_buf[3];

const motor_type motortype[BDC_num] = {N20_1024, N20_1218, N20_1024, N20_1218, N20_1218,  // thumb
                                       N20_1024, N20_1024, N20_1218, N20_1218,            // index
                                       N20_1024, N20_1024, N20_1218, N20_1218,            // middle
                                       N20_1024, N20_1024, N20_1218, N20_1218,            // ring
};

q15_t origin;
q15_t data;

IMP_CtrlData imp_data;
PID_CtrlData pid_data;

static float32_t motor_ud;
static float32_t motor_ip;
static float32_t motor_iavg;
static float32_t board_temp;
static float32_t bus_voltage;
    

BDC_Motor* new_BDC_Motor(void)
{
	static BDC_Motor motor;
	BDC_Motor* pObj = &motor;
	
    pObj->proto = new_BDC_Protocol(&huart1);
    
	pObj->mtr = new_DRV8213_Driver(&htim1, TIM_CHANNEL_3, TIM_CHANNEL_4, BDC_GS_GPIO_Port, BDC_GS_Pin);
	pObj->mps = new_MA782_Driver(&hspi1, SPI1_NSS_GPIO_Port, SPI1_NSS_Pin);
	pObj->utils = new_util_Driver();
	
    pObj->pid = new_PID_Controller();
	pObj->imp = new_IMP_Controller();
	
	//printf("INFO: BDC_Motor initialization succeeded.\r\n");
	return pObj;			
}

HAL_StatusTypeDef BDC_Motor_Init(BDC_Motor* ctrl)
{
	uint16_t stored_zero;

	ctrl->zero_valid = 0U;
	if (Flash_Read_Data(&stored_zero) == HAL_OK)
	{
		origin = (q15_t)stored_zero;
		ctrl->zero_valid = 1U;
	}
	ctrl->motor_enabled = 0U;
	ctrl->zero_calibrate_request = 0U;
    
    ctrl->motor = motortype[BOARD_ID];
    
	DRV8213_Driver_Init(ctrl->mtr, &adc_buf[0], &motor_ud, &motor_ip, &motor_iavg);
	MA782_Driver_Init(ctrl->mps, &data, origin, ctrl->motor);
	
	UTILS_Driver_InitTemp(ctrl->utils, &adc_buf[1], &board_temp);
	UTILS_Driver_InitVolt(ctrl->utils, &adc_buf[2], &bus_voltage);
    
    HAL_ADCEx_Calibration_Start(&hadc1);
    HAL_ADC_Start_DMA(&hadc1, (uint32_t*)adc_buf, 3); 
	
    if(ctrl->motor == N20_1024) {
        PID_Controller_Init(ctrl->pid, &pid_data, 0.001867, 0.0010472, 0, -0.99, 0.99);
        IMP_Controller_Init(ctrl->imp, &imp_data, 5, 0.1, -300, 300);
    }
        
    if(ctrl->motor == N20_1218) {
        PID_Controller_Init(ctrl->pid, &pid_data, 0.002914, 0.0014583, 0, -0.99, 0.99);
        IMP_Controller_Init(ctrl->imp, &imp_data, 10, 0.2, -300, 300);
    }
        

	if (BDC_Protocol_Init(ctrl->proto, BOARD_ID) != HAL_OK)
	{
		return HAL_ERROR;
	}
	
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_3);
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_4);
	HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_1);
    
    __HAL_TIM_SetCompare(&htim3, TIM_CHANNEL_1, 97);
    
	HAL_TIM_Base_Start(&htim1);
	HAL_TIM_Base_Start_IT(&htim17);

	if (BDC_Protocol_Receive(ctrl->proto) != HAL_OK)
	{
		return HAL_ERROR;
	}
    
    MA782_Driver_Read(ctrl->mps);
    
	return HAL_OK;
}

HAL_StatusTypeDef BDC_Motor_Enable(BDC_Motor* ctrl)
{
	if ((ctrl->zero_calibrate_request != 0U) || (ctrl->zero_valid == 0U))
		return HAL_BUSY;

	ctrl->imp_period = 0U;
	__HAL_TIM_CLEAR_FLAG(&htim3, TIM_FLAG_UPDATE);
	if (HAL_TIM_Base_Start_IT(&htim3) != HAL_OK)
	{
		return HAL_ERROR;
	}

	ctrl->motor_enabled = 1U;
	return HAL_OK;
}

HAL_StatusTypeDef BDC_Motor_Disable(BDC_Motor* ctrl)
{
	HAL_StatusTypeDef status;

	ctrl->motor_enabled = 0U;
	status = HAL_TIM_Base_Stop_IT(&htim3);
	__HAL_TIM_CLEAR_FLAG(&htim3, TIM_FLAG_UPDATE);
	__HAL_TIM_SetCompare(&htim1, TIM_CHANNEL_3, 0U);
	__HAL_TIM_SetCompare(&htim1, TIM_CHANNEL_4, 0U);

	return status;
}

HAL_StatusTypeDef BDC_Motor_CalibrateZero(BDC_Motor* ctrl)
{
	uint16_t zero_offset;
	HAL_StatusTypeDef status;

	__HAL_TIM_SetCompare(&htim1, TIM_CHANNEL_3, 0U);
    __HAL_TIM_SetCompare(&htim1, TIM_CHANNEL_4, 0U);

	status = MA782_Driver_Read(ctrl->mps);
	if (status != HAL_OK)
		return status;

	/* MA782 returns its angle relative to the currently programmed zero point. */
	zero_offset = (uint16_t)ctrl->mps->origin + (uint16_t)(*ctrl->mps->data);
	status = MA782_Driver_SetZero(ctrl->mps, zero_offset);
	if (status != HAL_OK)
		return status;

	status = Flash_Write_Data(zero_offset);
	if (status == HAL_OK)
	{
		origin = (q15_t)zero_offset;
		ctrl->zero_valid = 1U;
	}

	return status;
}

HAL_StatusTypeDef BDC_Motor_Run(BDC_Motor* ctrl)
{
	if ((ctrl->motor_enabled == 0U) || (ctrl->zero_calibrate_request != 0U))
        return HAL_BUSY;

	DRV8213_Driver_Get(ctrl->mtr, &ctrl->It);
	PID_Controller_Calc(ctrl->pid, ctrl->It);
	DRV8213_Driver_Write(ctrl->mtr, &ctrl->pid->obs->output);

	if (++ctrl->imp_period >= BDC_IMPEDANCE_LOOP_DIVIDER)
	{
		MA782_Driver_Read(ctrl->mps);
		ctrl->prev_pos = ctrl->pos;
		ctrl->pos = (float32_t)(*ctrl->mps->data) * BDC_POS_SCALE_DEG;
		ctrl->vel = (ctrl->pos - ctrl->prev_pos) * BDC_IMPEDANCE_LOOP_HZ;
		
		switch(ctrl->state)
		{
			case BDC_CMD_IMP_TAU:
				IMP_Controller_Calc(ctrl->imp, 0, 0);
				break;
			case BDC_CMD_IMP_VEL:
				IMP_Controller_Calc(ctrl->imp, 0, ctrl->vel);
				break;
			case BDC_CMD_IMP_POS:
				IMP_Controller_Calc(ctrl->imp, ctrl->pos, ctrl->vel);
				break;
		}
		ctrl->Id = ctrl->imp->obs->tau_cmd * BDC_Kt;
		PID_Controller_SetD(ctrl->pid, ctrl->Id);
		
		ctrl->imp_period = 0;
	}

	return HAL_OK;
}

void BDC_Motor_Process(BDC_Motor *ctrl)
{
	BDC_Protocol_Process(ctrl->proto);
//	if ((ctrl->motor_enabled != 0U) &&
//		(BDC_Protocol_IsCommandTimedOut(ctrl->proto, HAL_GetTick()) != 0U))
//	{
//		(void)BDC_Motor_Disable(ctrl);
//	}

	if (ctrl->zero_calibrate_request == 0U)
	{
		return;
	}

	(void)BDC_Motor_Disable(ctrl);
	(void)BDC_Motor_CalibrateZero(ctrl);

	ctrl->zero_calibrate_request = 0U;
}

uint8_t BDC_Motor_GetStatus(const BDC_Motor* ctrl)
{
	uint8_t status = 0U;

	if (ctrl->motor_enabled != 0U)
	{
		status |= BDC_STATUS_MOTOR_ENABLED;
	}
	if (ctrl->zero_calibrate_request != 0U)
	{
		status |= BDC_STATUS_ZERO_CALIBRATING;
	}
	if (ctrl->zero_valid != 0U)
	{
		status |= BDC_STATUS_ZERO_VALID;
	}

	return status;
}

void BDC_Motor_CommunicationProcess(BDC_Motor* ctrl, uint16_t size)
{
	BDC_CMD command;
	float32_t pData;
	uint8_t command_valid;

	HAL_StatusTypeDef status = BDC_Protocol_HandleReceive(ctrl->proto, size, &command,
		&pData, &command_valid);

	/* Execute a validated broadcast stop even if RX rearming fails. */
	if (command_valid != 0U)
	{
		(void)BDC_Motor_Set(ctrl, command, pData);
	}

	if ((status == HAL_OK) && (ctrl->proto->response_required != 0U))
	{
		(void)BDC_Protocol_TransmitResponse(ctrl->proto, (uint16_t)data, ctrl->Uvm,
			ctrl->Temp, BDC_Motor_GetStatus(ctrl));
	}
}

void BDC_Motor_CommunicationTransmitComplete(BDC_Motor* ctrl)
{
	(void)BDC_Protocol_HandleTransmitComplete(ctrl->proto);
}

HAL_StatusTypeDef BDC_Motor_Set(BDC_Motor* ctrl, BDC_CMD command, float32_t pData)
{
		switch(command)
		{
			case BDC_CMD_IMP_TAU:
				ctrl->state = BDC_CMD_IMP_TAU;
				IMP_Controller_SetD(ctrl->imp,  0, 0, pData);
				break;
			case BDC_CMD_IMP_VEL:
				ctrl->state = BDC_CMD_IMP_VEL;
				IMP_Controller_SetD(ctrl->imp,  0, pData, 0);
				break;
			case BDC_CMD_IMP_POS:
				ctrl->state = BDC_CMD_IMP_POS;
				IMP_Controller_SetD(ctrl->imp,  pData, 0, 0);
				break;
			case BDC_CMD_IMP_K_P:
				IMP_Controller_SetK(ctrl->imp,  pData, ctrl->imp->obs->k_d);
				break;
			case BDC_CMD_IMP_K_D:
				IMP_Controller_SetK(ctrl->imp,  ctrl->imp->obs->k_p, pData);
				break;
            case BDC_CMD_CAL_ZERO:
				(void)BDC_Motor_Disable(ctrl);
				ctrl->zero_calibrate_request = 1U;
                break;
            case BDC_CMD_ENABLE:
				(void)BDC_Motor_Enable(ctrl);
                break;
            case BDC_CMD_DISABLE:
				(void)BDC_Motor_Disable(ctrl);
                break;
		}
		
		return HAL_OK;
}

void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
	if(htim == (&htim3))
	{
		BDC_Motor_Run(main_core);
	}
	if(htim == (&htim17))
	{
        UTILS_Driver_GetTemp(main_core->utils, &main_core->Temp);
        UTILS_Driver_GetVolt(main_core->utils, &main_core->Uvm);
	}
}

void HAL_UARTEx_RxEventCallback(UART_HandleTypeDef *huart, uint16_t Size)
{
	if(huart == &huart1)
	{
		if (HAL_UARTEx_GetRxEventType(huart) != HAL_UART_RXEVENT_HT)
		{
			BDC_Motor_CommunicationProcess(main_core, Size);
		}
	}
}

void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
	if (huart == &huart1)
	{
		BDC_Motor_CommunicationTransmitComplete(main_core);
	}
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
	if ((huart != &huart1) || (main_core == NULL) || (main_core->proto == NULL))
		return;
	__HAL_UART_CLEAR_OREFLAG(huart);
	__HAL_UART_CLEAR_FEFLAG(huart); // 清除帧错误标志
	__HAL_UART_CLEAR_NEFLAG(huart); // 清除噪声错误标志
	__HAL_UART_CLEAR_PEFLAG(huart); // 清除奇偶校验错误标志
	if (main_core->proto->tx_pending == 0U)
	{
		(void)BDC_Protocol_Receive(main_core->proto);
	}
}