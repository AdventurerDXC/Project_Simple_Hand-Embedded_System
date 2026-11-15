/* =================================================================================
File name:       __BDC_PROTOCOL_C
Author: Mr.AdventurerDXC
===================================================================================*/

#include "bdc_protocol.h"
#include <string.h>

/**
 * @brief Calculate CRC-16/CCITT-FALSE for protocol frames.
 */
static uint16_t BDC_Protocol_CalculateCrc16(const uint8_t* data, uint16_t length)
{
	uint16_t crc = 0xFFFFU;
	uint16_t index;
	uint8_t bit;

	for (index = 0U; index < length; index++)
	{
		crc ^= (uint16_t)data[index] << 8U;
		for (bit = 0U; bit < 8U; bit++)
		{
			if ((crc & 0x8000U) != 0U)
				crc = (uint16_t)((crc << 1U) ^ 0x1021U);
			else
				crc <<= 1U;
		}
	}

	return crc;
}

BDC_Protocol* new_BDC_Protocol(UART_HandleTypeDef* huart)
{
	static BDC_Protocol protocol;
	BDC_Protocol* pObj = &protocol;

	pObj->huart = huart;
	pObj->board_id = 0U;
	pObj->tx_pending = 0U;
	pObj->response_required = 0U;
	pObj->response_sequence = 0U;
	pObj->last_valid_command_tick = 0U;
	return pObj;
}

HAL_StatusTypeDef BDC_Protocol_Init(BDC_Protocol* prot, uint8_t board_id)
{
	if (board_id >= BDC_num)
	{
		return HAL_ERROR;
	}

	prot->board_id = board_id;
	prot->tx_pending = 0U;
	prot->response_required = 0U;
	prot->response_sequence = 0U;
	prot->last_valid_command_tick = HAL_GetTick();
	return HAL_OK;
}

/**
 * @brief Start DMA reception of a fixed-size request frame.
 * @note HT, TC, and IDLE events may trigger the RxEvent callback.
 */
HAL_StatusTypeDef BDC_Protocol_Receive(BDC_Protocol* prot)
{
	return HAL_UARTEx_ReceiveToIdle_DMA(prot->huart, prot->rx_buffer,
								  BDC_PROTOCOL_REQUEST_SIZE);
}

/**
 * @brief У�� DMA ���յ�����֡������ȡ��ִ�еĿ������
 * @details ������ֻ��Э�������command_valid Ϊ 1 ʱ�����÷���ִ�� BDC_Motor_Set��
 * @param size UART �ص������ʵ�ʽ����ֽ�����
 * @param command ������Ϸ����
 * @param pData ���������� float32 ������
 * @param command_valid �����1 ��ʾ command �� pData ��Ч��0 ��ʾ������֡��
 */
HAL_StatusTypeDef BDC_Protocol_HandleReceive(BDC_Protocol* prot, uint16_t size,
                                              BDC_CMD* command, float32_t* pData,
                                              uint8_t* command_valid)
{
	/* request �� DMA �������ľֲ������������������� DMA ����Ӱ�챾�ν����� */
	BDCProt_Request request;
	uint16_t crc16;

	if ((command == NULL) || (pData == NULL) || (command_valid == NULL))
	{
		return HAL_ERROR;
	}

	*command_valid = 0U;
	prot->response_required = 0U;

	/* �� 10 B �¼��������԰봫��������� IDLE ��֡��ֱ�Ӷ������ع� DMA�� */
	if ((size != BDC_PROTOCOL_REQUEST_SIZE) || (prot->tx_pending != 0U))
	{
		return BDC_Protocol_Receive(prot);
	}

	/* �̶����������� 10 B ����֡�� */
	memcpy(&request, prot->rx_buffer, BDC_PROTOCOL_REQUEST_SIZE);

	/* CRC ����ǰ 8 B���� sof��id��command��sequence��pData�� */
	crc16 = BDC_Protocol_CalculateCrc16((const uint8_t*)&request,
	                                    BDC_PROTOCOL_REQUEST_SIZE - sizeof(request.crc16));

	/* ֡ͷ��CRC��Ŀ�� ID ���������һ���Ϸ�������ִ�е����� */
	if ((request.sof != BDC_PROTOCOL_RX_SOF) || (crc16 != request.crc16) ||
		((request.id != prot->board_id) && (request.id != BDC_PROTOCOL_BROADCAST_ID)) ||
		(request.command > (uint8_t)BDC_CMD_DISABLE))
	{
		return BDC_Protocol_Receive(prot);
	}

	if (request.id == BDC_PROTOCOL_BROADCAST_ID)
	{
		/* Broadcast is intentionally limited to the safe stop command. */
		if (request.command == (uint8_t)BDC_CMD_DISABLE)
		{
			*command = BDC_CMD_DISABLE;
			*pData = 0.0f;
			*command_valid = 1U;
		}
		return BDC_Protocol_Receive(prot);
	}

	/* ��������Ч����֡����ͨ�ſ��Ź���Ҫ����ң��ش��� */
	prot->last_valid_command_tick = HAL_GetTick();
	*command = (BDC_CMD)request.command;
	*pData = request.pData;
	*command_valid = 1U;
	prot->response_required = 1U;
	prot->response_sequence = request.sequence;

	return HAL_OK;
}

/**
 * @brief ��װ���� 16 B ң��֡������ UART �жϷ�ʽ���͡�
 * @note ������ɺ��� HAL_UART_TxCpltCallback ���� HandleTransmitComplete �ָ����ա�
 */
HAL_StatusTypeDef BDC_Protocol_TransmitResponse(BDC_Protocol* prot, uint16_t position,
                                                 float32_t Uvm, float32_t bdc_temp,
                                                 uint8_t status)
{
	HAL_StatusTypeDef tx_status;

	if ((prot->response_required == 0U) || (prot->tx_pending != 0U))
	{
		return HAL_ERROR;
	}

	prot->tx_response.sof = BDC_PROTOCOL_TX_SOF;
	prot->tx_response.id = prot->board_id;
	prot->tx_response.sequence = prot->response_sequence;
	prot->tx_response.pos = position;
	prot->tx_response.Uvm = Uvm;
	prot->tx_response.bdc_temp = bdc_temp;
	prot->tx_response.status = status;
	/* ��Ӧ CRC ����ǰ 14 B��ĩβ 2 B Ϊ CRC �ֶα����� */
	prot->tx_response.crc16 = BDC_Protocol_CalculateCrc16(
		(const uint8_t*)&prot->tx_response,
		BDC_PROTOCOL_RESPONSE_SIZE - sizeof(prot->tx_response.crc16));

	/* Send the response on TX without changing the independent RX line. */
	prot->tx_pending = 1U;
	/* ���������ͣ������� UART �ж��еȴ� 16 B ȫ���Ƴ��� */
	tx_status = HAL_UART_Transmit_IT(prot->huart, (uint8_t*)&prot->tx_response,
	                                 BDC_PROTOCOL_RESPONSE_SIZE);
	if (tx_status != HAL_OK)
	{
		prot->tx_pending = 0U;
		prot->response_required = 0U;
		(void)BDC_Protocol_Receive(prot);
	}

	return tx_status;
}

/**
 * @brief ��Ӧ֡ȫ��������ɺ�Ĵ������������״̬��������������֡���ա�
 */
HAL_StatusTypeDef BDC_Protocol_HandleTransmitComplete(BDC_Protocol* prot)
{
	prot->tx_pending = 0U;
	prot->response_required = 0U;
	return BDC_Protocol_Receive(prot);
}

/**
 * @brief �ж����һ����Ч���嵥�������Ƿ񳬹� 1000 ms��
 * @note uint32_t �������ȷ���� HAL_GetTick() ���ơ�
 */
uint8_t BDC_Protocol_IsCommandTimedOut(const BDC_Protocol* prot, uint32_t now_tick)
{
	return ((uint32_t)(now_tick - prot->last_valid_command_tick) >
		BDC_PROTOCOL_COMMAND_TIMEOUT_MS) ? 1U : 0U;
}

