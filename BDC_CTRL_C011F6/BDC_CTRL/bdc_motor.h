/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __BDC_MOTOR_H
#define __BDC_MOTOR_H
/* =================================================================================
File name:       __BDC_MOTOR_H
Author: Mr.NoFish, Adventurer
===================================================================================*/

#include "main.h"

#include "adc.h"
#include "tim.h"
#include "spi.h"
#include "usart.h"


#include "controller/imp_controller.h"
#include "controller/pid_controller.h"

#include "driver/drv8213_driver.h"
#include "driver/ma782_driver.h"
#include "driver/utils_driver.h"

#include "protocol/bdc_protocol.h"
#include "protocol/eeprom.h"


typedef struct BDC_Motor_ BDC_Motor;
typedef struct BDC_Proto_Packet_ BDC_Proto_Packet;

/* Configure a unique ID for each flashed board. */
#ifndef BOARD_ID
#define BOARD_ID                  8U
#endif
#if (BOARD_ID < 0) || (BOARD_ID >= BDC_num)
#error "BOARD_ID must be in the range 0..16"
#endif

#define BDC_Kt                    1.0f
#define BDC_POS_SCALE_DEG         (180.0f / 32768.0f)
#define BDC_IMPEDANCE_LOOP_DIVIDER 10U      // 每10步电流环执行1次阻抗环
#define BDC_IMPEDANCE_LOOP_HZ     1000.0f   // 阻抗环1kHz

struct BDC_Motor_
{	
	BDC_Protocol* proto;
	
	DRV8213_Driver* mtr;
	MA782_Driver* mps;
	UTILS_Driver* utils;
	
	PID_Controller* pid;
	IMP_Controller* imp;
	
    motor_type motor;
    
	uint8_t imp_period;

	uint8_t state;

	volatile uint8_t motor_enabled;
	volatile uint8_t zero_calibrate_request;
	uint8_t zero_valid;
	
	float32_t pos;
	float32_t prev_pos;
	float32_t vel;
	
	float32_t It;
	float32_t Id;
	float32_t Ud;
    
    float32_t Uvm;
    float32_t Temp;

};

BDC_Motor* new_BDC_Motor(void);

HAL_StatusTypeDef BDC_Motor_Init(BDC_Motor* ctrl);
HAL_StatusTypeDef BDC_Motor_CalibrateZero(BDC_Motor* ctrl);
HAL_StatusTypeDef BDC_Motor_Enable(BDC_Motor* ctrl);
HAL_StatusTypeDef BDC_Motor_Disable(BDC_Motor* ctrl);
HAL_StatusTypeDef BDC_Motor_Set(BDC_Motor* ctrl, BDC_CMD command, float32_t pData);
void BDC_Motor_Process(BDC_Motor* ctrl);
void BDC_Motor_CommunicationProcess(BDC_Motor* ctrl, uint16_t size);
void BDC_Motor_CommunicationTransmitComplete(BDC_Motor* ctrl);
uint8_t BDC_Motor_GetStatus(const BDC_Motor* ctrl);
HAL_StatusTypeDef Main_controller_Read(BDC_Motor* ctrl);
HAL_StatusTypeDef Main_controller_Transmit(BDC_Motor* ctrl);

#endif
