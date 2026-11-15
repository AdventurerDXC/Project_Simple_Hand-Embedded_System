/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MA782_DRIVER_H
#define __MA782_DRIVER_H
/* =================================================================================
File name:       __MA782_DRIVER_H
Author: Mr.NoFish
===================================================================================*/

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/

#include "main.h"

#define MA782_REG_ZERO_LOW            0x0000 // 零位低字节
#define MA782_REG_ZERO_HIGH           0x0100 // 零位高字节
#define MA782_REG_BIAS_TRIM           0x0200 // 偏置电流调整
#define MA782_REG_ENABLE_TRIM_X       0x0300 // 启用X轴偏置调整
#define MA782_REG_ENABLE_TRIM_Y       0x0300 // 启用Y轴偏置调整
#define MA782_REG_CYCLE_TIME_LOW      0x0400 // 周期时间低字节
#define MA782_REG_CYCLE_TIME_HIGH     0x0500 // 周期时间高字节
#define MA782_REG_MAGNET_LOW_THRESH   0x0600 // 磁场强度低阈值
#define MA782_REG_MAGNET_HIGH_THRESH  0x0600 // 磁场强度高阈值
#define MA782_REG_MAGNET_ENABLE       0x0700 // 磁场强度检测使能
#define MA782_REG_ND_MODE             0x0700 // ND引脚模式
#define MA782_REG_ND_HYSTERESIS       0x0700 // ND引脚迟滞
#define MA782_REG_ROTATION_DIRECTION  0x0900 // 旋转方向
#define MA782_REG_REFERENCE_ANGLE     0x0A00 // 参考角度 ASC mode
#define MA782_REG_ASC_ENABLE          0x0B00 // 自动采样使能 ASC mode
#define MA782_REG_ASC_REGISTER        0x0B00 // 自动采样寄存器
#define MA782_REG_FILTER_WINDOW       0x0E00 // 滤波窗口大小
#define MA782_REG_ERROR_FLAGS         0x1A00 // 错误标志
#define MA782_REG_MAGNET_FLAGS        0x1B00 // 磁场标志

// MA782寄存器位定义
#define MA782_ENABLE_TRIM_X           (1 << 7) // 启用X轴偏置调整
#define MA782_ENABLE_TRIM_Y           (1 << 6) // 启用Y轴偏置调整
#define MA782_ND_MODE_LOGIC_LEVEL     (1 << 7) // ND引脚逻辑电平模式
#define MA782_ND_HYSTERESIS_MASK       0x3F    // ND引脚迟滞掩码
#define MA782_MAGNET_ENABLE           (1 << 7) // 磁场强度检测使能
#define MA782_ASC_ENABLE              (1 << 7) // 自动采样使能
#define MA782_ASC_REGISTER_ENABLE     (1 << 7) // 自动采样寄存器使能

// MA782命令宏定义
#define MA782_CMD_READ_ANGLE          0x0000 // 读取角度
#define MA782_CMD_CLEAR_ERROR_FLAGS   0x2000 // 清除错误标志
#define MA782_CMD_READ_REGISTER       0x4000 // 读取寄存器
#define MA782_CMD_WRITE_REGISTER      0x8000 // 写入寄存器
#define MA782_CMD_RESTORE_ALL_NVM     0xA000 // 从NVM恢复所有寄存器
#define MA782_CMD_STORE_ALL_NVM       0xC000 // 存储所有寄存器到NVM
#define MA782_CMD_STORE_SINGLE_NVM    0xE000 // 存储单个寄存器到NV

typedef struct MA782_Driver_ MA782_Driver;

struct MA782_Driver_{

    SPI_HandleTypeDef *hspi;
    GPIO_TypeDef *cs_port;
    uint16_t cs_pin;
	
	HAL_StatusTypeDef status;
	
	uint16_t rx_buf[2];
	uint16_t tx_buf[2];
	
	uint8_t magnet_flags;
	
	q15_t origin;
	
	q15_t* data;
};


MA782_Driver* new_MA782_Driver(SPI_HandleTypeDef *hspi, 
                               GPIO_TypeDef *cs_port, uint16_t cs_pin);

HAL_StatusTypeDef MA782_Driver_Init(MA782_Driver *hdev, q15_t* data, q15_t origin, uint8_t motor_type);

HAL_StatusTypeDef MA782_Driver_WriteReg(MA782_Driver *hdev, uint16_t addr, uint8_t value);

HAL_StatusTypeDef MA782_Driver_SetZero(MA782_Driver *hdev, uint16_t origin);

HAL_StatusTypeDef MA782_Driver_Read(MA782_Driver *hdev);

HAL_StatusTypeDef MA782_Driver_SetCommand(MA782_Driver *hdev, uint16_t pTxData, uint16_t* pRxData);

#ifdef __cplusplus
}
#endif

#endif