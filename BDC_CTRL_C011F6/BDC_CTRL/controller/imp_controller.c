/* =================================================================================
File name:       __IMP_CONTROLLER_C__
===================================================================================*/
#include "imp_controller.h"

IMP_Controller* new_IMP_Controller(void)
{
	static IMP_Controller controller;
	return &controller;
}

HAL_StatusTypeDef delete_IMP_Controller(IMP_Controller* ctrl)
{
	(void)ctrl;
	return HAL_OK;
}


HAL_StatusTypeDef IMP_Controller_Init(IMP_Controller* ctrl, IMP_CtrlData* obs, float32_t k_p, float32_t k_d, float32_t limit1, float32_t limit2)
{
	if (obs == NULL)
	{
		return HAL_ERROR;
	}
	ctrl->obs = obs;
    
    ctrl->obs->k_p = k_p;
    ctrl->obs->k_d = k_d;
    
    if(limit1 >= limit2)  return HAL_ERROR;
    
    ctrl->obs->limit1 = limit1;
	ctrl->obs->limit2 = limit2;
	
	return HAL_OK;
}

HAL_StatusTypeDef IMP_Controller_Calc(IMP_Controller* ctrl, float32_t pos, float32_t vel)
{
	ctrl->obs->pos = pos;
	ctrl->obs->vel = vel;
	
	ctrl->pos_e = ctrl->obs->pos_d - ctrl->obs->pos;
	ctrl->vel_e = ctrl->obs->vel_d - ctrl->obs->vel;
    
    if(ctrl->pos_e >= 180.0f)  ctrl->pos_e -= 360.0f;
    if(ctrl->pos_e < -180.0f)  ctrl->pos_e += 360.0f;
    
	ctrl->obs->tau_cmd = ctrl->obs->k_p * ctrl->pos_e 
					   + ctrl->obs->k_d * ctrl->vel_e 
					   + ctrl->obs->tau_d;
    
    if(ctrl->obs->tau_cmd < ctrl->obs->limit1)
        ctrl->obs->tau_cmd = ctrl->obs->limit1;
    if(ctrl->obs->tau_cmd > ctrl->obs->limit2)
        ctrl->obs->tau_cmd = ctrl->obs->limit2;
    
	return HAL_OK;
}

HAL_StatusTypeDef IMP_Controller_SetK(IMP_Controller* ctrl, float32_t k_p, float32_t k_d)
{
	ctrl->obs->k_p = k_p;
	ctrl->obs->k_d = k_d;
	return HAL_OK;
}

HAL_StatusTypeDef IMP_Controller_SetD(IMP_Controller* ctrl, float32_t pos_d, float32_t vel_d, float32_t tau_d)
{
	ctrl->obs->pos_d = pos_d;
	ctrl->obs->vel_d = vel_d;
	ctrl->obs->tau_d = tau_d;
	return HAL_OK;
}