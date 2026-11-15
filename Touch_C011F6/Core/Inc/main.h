/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  *                   This file contains the common defines of the application.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32c0xx_hal.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

/* Exported functions prototypes ---------------------------------------------*/
void Error_Handler(void);

/* USER CODE BEGIN EFP */

/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/
#define ADC_IN_Pin GPIO_PIN_0
#define ADC_IN_GPIO_Port GPIOA
#define Y0_Pin GPIO_PIN_1
#define Y0_GPIO_Port GPIOA
#define Y1_Pin GPIO_PIN_2
#define Y1_GPIO_Port GPIOA
#define Y2_Pin GPIO_PIN_3
#define Y2_GPIO_Port GPIOA
#define Y3_Pin GPIO_PIN_4
#define Y3_GPIO_Port GPIOA
#define Y4_Pin GPIO_PIN_5
#define Y4_GPIO_Port GPIOA
#define Y5_Pin GPIO_PIN_6
#define Y5_GPIO_Port GPIOA
#define EN_Pin GPIO_PIN_7
#define EN_GPIO_Port GPIOA
#define S0_Pin GPIO_PIN_8
#define S0_GPIO_Port GPIOA
#define S1_Pin GPIO_PIN_11
#define S1_GPIO_Port GPIOA
#define S2_Pin GPIO_PIN_12
#define S2_GPIO_Port GPIOA
#define USART_TX_Pin GPIO_PIN_6
#define USART_TX_GPIO_Port GPIOB
#define USART_RX_Pin GPIO_PIN_7
#define USART_RX_GPIO_Port GPIOB

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
