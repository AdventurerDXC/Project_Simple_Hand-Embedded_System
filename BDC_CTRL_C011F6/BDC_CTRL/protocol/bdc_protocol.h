/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __BDC_PROTOCOL_H
#define __BDC_PROTOCOL_H
/* =================================================================================
File name:       __BDC_PROTOCOL_H
===================================================================================*/

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "main.h"

#define BDC_num     17U

#define BDC_PROTOCOL_RX_SOF                0xA5U
#define BDC_PROTOCOL_TX_SOF                0x5AU
#define BDC_PROTOCOL_BROADCAST_ID          0xFFU
#define BDC_PROTOCOL_COMMAND_TIMEOUT_MS    1000U


#define BDC_PROTOCOL_REQUEST_SIZE           10U
#define BDC_PROTOCOL_RESPONSE_SIZE          16U

#define BDC_STATUS_MOTOR_ENABLED            (1U << 0)
#define BDC_STATUS_ZERO_CALIBRATING         (1U << 1)
#define BDC_STATUS_ZERO_VALID               (1U << 2)

typedef enum
{
    N20_1024, 
    N20_1218
}motor_type;

typedef enum
{
    BDC_CMD_IMP_TAU,  // 阻抗控制命令
    BDC_CMD_IMP_VEL,  // 速度控制命令
	BDC_CMD_IMP_POS,  // 位置控制命令
	BDC_CMD_IMP_K_P,  // 设置阻抗环Kp
	BDC_CMD_IMP_K_D,  // 设置阻抗环Kd
    BDC_CMD_CAL_ZERO, // 校准零点命令
    BDC_CMD_ENABLE,   // 电机使能命令
    BDC_CMD_DISABLE   // 电机失能命令
}BDC_CMD;

typedef struct BDC_Protocol_ BDC_Protocol;
typedef struct BDCProt_Request_ BDCProt_Request;
typedef struct BDCProt_Response_ BDCProt_Response;

#pragma pack(push, 1)
struct BDCProt_Request_
{
    uint8_t sof;
    uint8_t id;
    uint8_t command;
    uint8_t sequence;
    float32_t pData;
    uint16_t crc16;
};

struct BDCProt_Response_
{
    uint8_t sof;
    uint8_t id;
    uint8_t sequence;
    uint16_t pos;
    float32_t Uvm;
    float32_t bdc_temp;
    uint8_t status;
    uint16_t crc16;
};
#pragma pack(pop)


struct BDC_Protocol_
{
	UART_HandleTypeDef* huart;
	uint8_t board_id;
    uint8_t rx_buffer[BDC_PROTOCOL_REQUEST_SIZE];
	BDCProt_Response tx_response;
	volatile uint8_t tx_pending;
    uint8_t response_required;
    uint8_t response_sequence;
	volatile uint32_t last_valid_command_tick;
};


BDC_Protocol* new_BDC_Protocol(UART_HandleTypeDef* huart);
HAL_StatusTypeDef delete_BDC_Protocol(BDC_Protocol* hdev);

HAL_StatusTypeDef BDC_Protocol_Init(BDC_Protocol* prot, uint8_t board_id);

HAL_StatusTypeDef BDC_Protocol_Receive(BDC_Protocol* prot);
HAL_StatusTypeDef BDC_Protocol_HandleReceive(BDC_Protocol* prot, uint16_t size,
                                              BDC_CMD* command, float32_t* pData,
                                              uint8_t* command_valid);
HAL_StatusTypeDef BDC_Protocol_TransmitResponse(BDC_Protocol* prot, uint16_t position,
                                                 float32_t Uvm, float32_t bdc_temp,
                                                 uint8_t status);
HAL_StatusTypeDef BDC_Protocol_HandleTransmitComplete(BDC_Protocol* prot);
uint8_t BDC_Protocol_IsCommandTimedOut(const BDC_Protocol* prot, uint32_t now_tick);

#endif

