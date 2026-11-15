/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __PID_CONTROLLER_H__
#define __PID_CONTROLLER_H__
/* =================================================================================
File name:       __PID_CONTROLLER_H__
===================================================================================*/

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/

#include "main.h"

typedef struct PID_Controller_ PID_Controller;
typedef struct PID_CtrlData_ PID_CtrlData;

struct PID_Controller_
{
    PID_CtrlData* obs;
	float32_t errorn[3];
	
};

struct PID_CtrlData_
{
	float32_t k[3];
	
	float32_t limit_int;
	
	float32_t limit1;
	float32_t limit2;
	
	float32_t setValue;
	
	float32_t output;
};
 
PID_Controller* new_PID_Controller(void);
void delete_PID_Controller(PID_Controller* ctrl);

HAL_StatusTypeDef PID_Controller_Init(PID_Controller* ctrl, PID_CtrlData* obs, float32_t kp, float32_t ki, float32_t kd, float32_t limit1, float32_t limit2);
HAL_StatusTypeDef PID_Controller_Calc(PID_Controller* ctrl, float32_t value);
HAL_StatusTypeDef PID_Controller_SetD(PID_Controller* ctrl, float32_t value);

#endif