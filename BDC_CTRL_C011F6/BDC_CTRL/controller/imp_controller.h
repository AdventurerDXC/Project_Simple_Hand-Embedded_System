/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __IMP_CONTROLLER_H__
#define __IMP_CONTROLLER_H__
/* =================================================================================
File name:       __IMP_CONTROLLER_H__
改编自https://blog.csdn.net/wind4study/article/details/45116281
===================================================================================*/

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ----------------------------------------------------------------*/

#include "main.h"

typedef struct IMP_Controller_ IMP_Controller;
typedef struct IMP_CtrlData_ IMP_CtrlData;

struct IMP_Controller_
{
	IMP_CtrlData* obs;

	float32_t pos_e;
	float32_t vel_e;
};

struct IMP_CtrlData_
{
	float32_t pos;
	float32_t vel;
	
	float32_t pos_d;
	float32_t vel_d;
	
	float32_t k_p;
	float32_t k_d;
	
    float32_t tau_d;
    float32_t tau_cmd;
    
    float32_t limit1;
	float32_t limit2;
};

IMP_Controller* new_IMP_Controller(void);
HAL_StatusTypeDef delete_IMP_Controller(IMP_Controller* ctrl);

HAL_StatusTypeDef IMP_Controller_Init(IMP_Controller* ctrl, IMP_CtrlData* obs, float32_t kp, float32_t kd, float32_t limit1, float32_t limit2);
HAL_StatusTypeDef IMP_Controller_Calc(IMP_Controller* ctrl, float32_t pos, float32_t vel);
HAL_StatusTypeDef IMP_Controller_SetK(IMP_Controller* ctrl, float32_t k_p, float32_t k_d);
HAL_StatusTypeDef IMP_Controller_SetD(IMP_Controller* ctrl, float32_t pos_d, float32_t vel_d, float32_t tau_d);

#endif



