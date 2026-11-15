/* =================================================================================
File name:       __PID_CONTROLLER_C__
===================================================================================*/
#include "pid_controller.h"

PID_Controller* new_PID_Controller(void)
{
	static PID_Controller controller;
	return &controller;
}

void delete_PID_Controller(PID_Controller* ctrl)
{
	(void)ctrl;
}


HAL_StatusTypeDef PID_Controller_Init(PID_Controller* ctrl, PID_CtrlData* obs, float32_t kp, float32_t ki, float32_t kd, float32_t limit1, float32_t limit2)
{
    if(obs == NULL)
        return HAL_ERROR;
    ctrl->obs = obs;
    
	ctrl->errorn[0] = 0.0f;
	ctrl->errorn[1] = 0.0f;
	ctrl->errorn[2] = 0.0f;
	ctrl->obs->setValue = 0.0f;
	ctrl->obs->output = 0.0f;
	
	ctrl->obs->k[0] = kp;
	ctrl->obs->k[1] = ki;
	ctrl->obs->k[2] = kd;

	ctrl->obs->limit1 = limit1;
	ctrl->obs->limit2 = limit2;
	
	return HAL_OK;
}

HAL_StatusTypeDef PID_Controller_Calc(PID_Controller* ctrl, float32_t value)
{
	float32_t errorn = ctrl->obs->setValue - value; //误差
    
	ctrl->errorn[2] = errorn - ctrl->errorn[0]; //微分
	ctrl->errorn[1] += errorn; //积分
	ctrl->errorn[0] = errorn;  //微分
	
    float32_t tmp = ctrl->errorn[0] * ctrl->obs->k[0]
			      + ctrl->errorn[1] * ctrl->obs->k[1]
			      + ctrl->errorn[2] * ctrl->obs->k[2];
    
    // 抗积分饱和
	if(tmp > ctrl->obs->limit2 && errorn > 0)
		ctrl->errorn[1] -= errorn;
	if(tmp < ctrl->obs->limit1 && errorn < 0)
		ctrl->errorn[1] -= errorn;
	

	ctrl->obs->output = ctrl->errorn[0] * ctrl->obs->k[0]
			          + ctrl->errorn[1] * ctrl->obs->k[1]
			          + ctrl->errorn[2] * ctrl->obs->k[2];
	
	if(ctrl->obs->output > ctrl->obs->limit2)
		ctrl->obs->output = ctrl->obs->limit2;
	if(ctrl->obs->output < ctrl->obs->limit1)
		ctrl->obs->output = ctrl->obs->limit1;
	
	return HAL_OK;
}

HAL_StatusTypeDef PID_Controller_SetD(PID_Controller* ctrl, float32_t value)
{
	ctrl->obs->setValue = value;
	
	return HAL_OK;
}
