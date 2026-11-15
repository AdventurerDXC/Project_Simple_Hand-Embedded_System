/* =================================================================================
File name:       __MA782_Driver_DRIVER_C
Author: Mr.NoFish
===================================================================================*/
#include "ma782_driver.h"

MA782_Driver* new_MA782_Driver(SPI_HandleTypeDef *hspi, 
                                GPIO_TypeDef *cs_port, uint16_t cs_pin) 
{
	static MA782_Driver driver;
	MA782_Driver* hdev = &driver;
    hdev->hspi = hspi;
    hdev->cs_port = cs_port;
    hdev->cs_pin = cs_pin;

	return hdev;
}

HAL_StatusTypeDef MA782_Driver_Init(MA782_Driver *hdev, q15_t* data, q15_t origin, uint8_t motor_type)
{
	if (data == NULL)
	{
		return HAL_ERROR;
	}
	hdev->data = data;
    
    hdev->origin = origin;
	
    HAL_GPIO_WritePin(hdev->cs_port, hdev->cs_pin, GPIO_PIN_SET);
    MA782_Driver_WriteReg(hdev, MA782_REG_CYCLE_TIME_LOW, 25);
    MA782_Driver_WriteReg(hdev, MA782_REG_CYCLE_TIME_HIGH, 0);
    MA782_Driver_WriteReg(hdev, MA782_REG_ROTATION_DIRECTION, 0);
    
    if(motor_type == 1) {
        MA782_Driver_WriteReg(hdev, MA782_REG_ENABLE_TRIM_Y, 2);
        MA782_Driver_WriteReg(hdev, MA782_REG_BIAS_TRIM, 152);
    }

	return MA782_Driver_SetZero(hdev, (uint16_t)origin);
}

HAL_StatusTypeDef MA782_Driver_WriteReg(MA782_Driver *hdev, uint16_t addr, uint8_t value)
{
	uint16_t rcv;
    uint16_t command = MA782_CMD_WRITE_REGISTER | addr | value;
    
	hdev->status = MA782_Driver_SetCommand(hdev, command, &rcv);
    if((hdev->status == HAL_OK) && (rcv == value))  {
		*hdev->data = hdev->rx_buf[0];
        return HAL_OK;
    }
	return HAL_ERROR;
}

HAL_StatusTypeDef MA782_Driver_SetZero(MA782_Driver *hdev, uint16_t origin)
{
	HAL_StatusTypeDef status;

	status = MA782_Driver_WriteReg(hdev, MA782_REG_ZERO_HIGH, (uint8_t)(origin >> 8));
	if (status != HAL_OK)
	{
		return status;
	}

	status = MA782_Driver_WriteReg(hdev, MA782_REG_ZERO_LOW, (uint8_t)(origin & 0xFFU));
	if (status == HAL_OK)
	{
		hdev->origin = (q15_t)origin;
	}

	return status;
}

HAL_StatusTypeDef MA782_Driver_Read(MA782_Driver *hdev)
{
	uint16_t command = MA782_CMD_READ_REGISTER | MA782_REG_MAGNET_FLAGS;

	hdev->status = MA782_Driver_SetCommand(hdev, command, (uint16_t*)&hdev->magnet_flags);
	if((hdev->status == HAL_OK) && ((hdev->magnet_flags & 0xC0) == 0x00))  {
		*hdev->data = hdev->rx_buf[0];
        return HAL_OK;
    }
	return HAL_ERROR;
}

HAL_StatusTypeDef MA782_Driver_SetCommand(MA782_Driver *hdev, uint16_t pTxData, uint16_t* pRxData)
{
	HAL_GPIO_WritePin(hdev->cs_port, hdev->cs_pin, GPIO_PIN_RESET);
	
	hdev->tx_buf[0] = pTxData;
	hdev->tx_buf[1] = 0;
	hdev->status = HAL_SPI_TransmitReceive(hdev->hspi, (uint8_t*)hdev->tx_buf, (uint8_t*)hdev->rx_buf, 1, 2);
    
    HAL_GPIO_WritePin(hdev->cs_port, hdev->cs_pin, GPIO_PIN_SET);
    
    HAL_GPIO_WritePin(hdev->cs_port, hdev->cs_pin, GPIO_PIN_RESET);
    
    hdev->status = HAL_SPI_TransmitReceive(hdev->hspi, (uint8_t*)(hdev->tx_buf + 1), (uint8_t*)(hdev->rx_buf + 1), 1, 2);
	if((hdev->status == HAL_OK) && ((hdev->rx_buf[0] & 0xFF00) == (hdev->rx_buf[1] & 0xFF00)))
		*pRxData = hdev->rx_buf[1] & 0x00FF;
	else
		hdev->status = HAL_ERROR;
		
	HAL_GPIO_WritePin(hdev->cs_port, hdev->cs_pin, GPIO_PIN_SET);
	
	return hdev->status;
}
