
#ifndef __TACTILE_SENSE_H
#define __TACTILE_SENSE_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32c0xx_hal.h"
#include <stdint.h>

/* ======================== 参数配置 ======================== */

#define TACTILE_ROW_NUM             6U
#define TACTILE_COL_NUM             6U
#define TACTILE_POINT_NUM           (TACTILE_ROW_NUM * TACTILE_COL_NUM)

#define REF_RESISTOR                22U     // Kohms
#define R_F_RATIO                   31250U  // 1/R(Kohms) -> F(g)

#define ADC_RANGE                   0xFFF


/**
 * @brief 初始化触觉采集模块
 *
 * @param hadc ADC 外设句柄
 * @return HAL_StatusTypeDef
 */
HAL_StatusTypeDef TactileSense_Init(ADC_HandleTypeDef *hadc);


/**
 * @brief 扫描6×6压阻阵列
 *
 * 数据排列方式为行优先：
 *
 * data[0]  = Y0-X0
 * data[1]  = Y0-X1
 * ...
 * data[5]  = Y0-X5
 * data[6]  = Y1-X0
 * ...
 * data[35] = Y5-X5
 *
 * @param data 存放36个ADC原始值的数组
 * @return HAL_StatusTypeDef
 */
HAL_StatusTypeDef TactileSense_Scan(uint16_t data[TACTILE_POINT_NUM]);

/**
 * @brief 将ADC原始数据转换为实际力大小（单位：g）
 * @param data  存放36个ADC原始值的数组
 *        force 存放36个实际力值的数组
 */

void RawDataToForce(uint16_t data[TACTILE_POINT_NUM], uint16_t force[TACTILE_POINT_NUM]);

#ifdef __cplusplus
}
#endif

#endif /* __TACTILE_SENSE_H */