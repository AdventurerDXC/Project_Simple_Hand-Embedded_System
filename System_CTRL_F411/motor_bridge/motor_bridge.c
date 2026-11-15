#include "motor_bridge.h"

#include "usbd_cdc_if.h"
#include "tim.h"

#include <string.h>

/* Each ring can buffer one full motor round plus an empty slot. */
#define MOTOR_BRIDGE_COMMAND_QUEUE_CAPACITY   BDC_num
#define MOTOR_BRIDGE_COMMAND_QUEUE_SLOT_NUM   (MOTOR_BRIDGE_COMMAND_QUEUE_CAPACITY + 1U)
#define MOTOR_BRIDGE_RESPONSE_QUEUE_SLOT_NUM  (MOTOR_BRIDGE_COMMAND_QUEUE_CAPACITY + 1U)
#define MOTOR_BRIDGE_TIM3_COUNTER_PERIOD      50000U
#define MOTOR_BRIDGE_RX_DMA_SIZE             64U

/* 电机单线总线的轮询状态。 */
typedef enum
{
	MOTOR_BRIDGE_IDLE = 0,          /* 空闲，可以发送队列中的下一条命令 */
	MOTOR_BRIDGE_TRANSMITTING,
	MOTOR_BRIDGE_ABORTING,
	MOTOR_BRIDGE_WAITING_RESPONSE   /* 请求已发送，等待目标从站响应 */
} MotorBridgeState;

/* USART1 的 HAL 句柄，由初始化函数传入。 */
static UART_HandleTypeDef *s_huart = NULL;
volatile BDCProt_CommandType BDCProt_Command[BDC_num];

/* The queue contains one scheduled command per board and round at most. */
static BDCProt_CommandType s_command_queue[MOTOR_BRIDGE_COMMAND_QUEUE_SLOT_NUM];
static volatile uint8_t s_command_head = 0U;
static volatile uint8_t s_command_tail = 0U;

/* USB 数据可能分包或粘包，此缓冲区用于重组固定长度的 10 B 请求帧。 */
static uint8_t s_usb_assembly[BDC_PROTOCOL_REQUEST_SIZE];
static uint8_t s_usb_assembly_length = 0U;

/* USART1 RX circular DMA and persistent TX DMA buffer. */
static uint8_t s_rx_dma[MOTOR_BRIDGE_RX_DMA_SIZE];
static uint16_t s_rx_dma_position = 0U;
static volatile uint8_t s_rx_restart_needed = 0U;
static BDCProt_Request s_tx_request;

/* 从站 16 B 响应帧的组帧缓冲区、已接收字节数和“完整帧就绪”标志。 */
static uint8_t s_response_frame[BDC_PROTOCOL_RESPONSE_SIZE];
static volatile uint8_t s_response_index = 0U;
static volatile uint8_t s_response_ready = 0U;
static uint8_t s_usb_response_queue[MOTOR_BRIDGE_RESPONSE_QUEUE_SLOT_NUM]
	[BDC_PROTOCOL_RESPONSE_SIZE];
static volatile uint8_t s_usb_response_head = 0U;
static volatile uint8_t s_usb_response_tail = 0U;
static volatile uint8_t s_usb_tx_active = 0U;

/* 当前轮询状态及当前请求所期望的 ID、序号和响应截止时间。 */
static volatile MotorBridgeState s_state = MOTOR_BRIDGE_IDLE;
static volatile uint8_t s_tx_active = 0U;
static uint8_t s_expected_id = 0U;        /* 当前等待响应的目标电机板 ID */
static uint8_t s_expected_sequence = 0U;  /* 当前等待响应的请求 sequence */
static volatile uint16_t s_response_start_count = 0U;
static volatile uint8_t s_next_poll_id = 0U;
static volatile uint8_t s_round_restart_pending = 0U;
static volatile uint32_t s_round_overrun_count = 0U;

/* 通信统计量，可通过头文件中的查询函数读取。 */
static volatile uint32_t s_received_command_count = 0U;
static volatile uint32_t s_dropped_command_count = 0U;
static volatile uint32_t s_transmit_error_count = 0U;
static volatile uint32_t s_response_count = 0U;
static volatile uint32_t s_response_timeout_count = 0U;
static volatile uint32_t s_response_error_count = 0U;

/* 私有函数声明。 */
static unsigned short MotorBridge_Crc16(
	const unsigned char *data,
	unsigned short length);
static uint8_t MotorBridge_NextQueueIndex(uint8_t index);
static uint8_t MotorBridge_PushCommand(const BDCProt_CommandType *command);
static uint8_t MotorBridge_PopCommand(BDCProt_CommandType *command);
static void MotorBridge_BeginPollRound(void);
static void MotorBridge_ScheduleBoard(uint8_t id);
static uint8_t MotorBridge_RequestIsValid(const BDCProt_Request *request);
static uint8_t MotorBridge_ResponseIsExpected(const uint8_t *frame);
static void MotorBridge_ResetResponseParser(void);
static void MotorBridge_ProcessResponse(void);
static void MotorBridge_ProcessCommand(void);
static void MotorBridge_ProcessUSBTransmit(void);
static uint8_t MotorBridge_ResponseTimedOut(void);
static HAL_StatusTypeDef MotorBridge_StartReceive(void);

/** Start continuous USART1 DMA reception and the polling timers. */
HAL_StatusTypeDef MotorBridge_Init(UART_HandleTypeDef *huart)
{
	/* 没有串口句柄则无法进行任何通信。 */
	if (huart == NULL)
		return HAL_ERROR;

	/* 复位队列、USB 组帧状态、轮询状态及调试计数器。 */
	s_huart = huart;
	s_command_head = 0U;
	s_command_tail = 0U;
	s_usb_assembly_length = 0U;
	s_state = MOTOR_BRIDGE_IDLE;
	s_tx_active = 0U;
	s_response_ready = 0U;
	s_usb_response_head = 0U;
	s_usb_response_tail = 0U;
	s_usb_tx_active = 0U;
	s_next_poll_id = 0U;
	s_round_restart_pending = 0U;
	s_round_overrun_count = 0U;
	MotorBridge_ResetResponseParser();
	{
		uint8_t id;
		for (id = 0U; id < BDC_num; id++)
		{
			BDCProt_Command[id].id = id;
			BDCProt_Command[id].sequence = 0U;
			BDCProt_Command[id].command = BDC_CMD_DISABLE;
			BDCProt_Command[id].pData = 0.0f;
		}
	}

	s_received_command_count = 0U;
	s_dropped_command_count = 0U;
	s_transmit_error_count = 0U;
	s_response_count = 0U;
	s_response_timeout_count = 0U;
	s_response_error_count = 0U;

	if (MotorBridge_StartReceive() != HAL_OK)
		return HAL_ERROR;

	/* Send board 0 now; TIM4 schedules subsequent boards every 2.5 ms. */
	MotorBridge_BeginPollRound();
	if (HAL_TIM_Base_Start_IT(&htim3) != HAL_OK)
		return HAL_ERROR;

	return HAL_OK;
}

/**
 * @brief 逐字节解析 PC 经 USB CDC 下发的请求帧。
 * @details 兼容 USB 分包与粘包；只有帧头、ID/命令范围、CRC 都正确的帧才入队。
 */
void MotorBridge_USBReceive(const uint8_t *data, uint32_t length)
{
	uint32_t index;

	/* 空指针不包含有效 USB 数据。 */
	if (data == NULL)
		return;

	/* 逐字节处理，避免假设一个 USB 包恰好等于一帧。 */
	for (index = 0U; index < length; index++)
	{
		BDCProt_Request request;

		/* 未处于组帧状态时，仅接受请求帧头 0xA5。 */
		if ((s_usb_assembly_length == 0U) &&
			(data[index] != BDC_PROTOCOL_REQUEST_SOF))
			continue;

		/* 保存当前字节，直到凑满 10 B 固定长度帧。 */
		s_usb_assembly[s_usb_assembly_length] = data[index];
		s_usb_assembly_length++;

		if (s_usb_assembly_length < BDC_PROTOCOL_REQUEST_SIZE)
			continue;

		/* 完整帧转为结构体后，马上将组帧长度清零以接收下一帧。 */
		memcpy(&request, s_usb_assembly, sizeof(request));
		s_usb_assembly_length = 0U;

		/* Valid requests replace the latest command for the addressed board. */
		if (MotorBridge_RequestIsValid(&request) != 0U)
		{
			uint8_t first_id = request.id;
			uint8_t last_id = request.id;
			uint8_t id;

			/* Broadcast DISABLE updates the latest-command state for all boards. */
			if (request.id == BDC_PROTOCOL_BROADCAST_ID)
			{
				first_id = 0U;
				last_id = BDC_num - 1U;
			}

			{
				uint32_t primask = __get_PRIMASK();
				__disable_irq();
				for (id = first_id; id <= last_id; id++)
				{
					BDCProt_CommandType command;
					command.id = id;
					command.sequence = request.sequence;
					command.command = (BDC_CMD)request.command;
					command.pData = request.pData;
					BDCProt_Command[id] = command;
				}
				__DMB();
				if (primask == 0U)
					__enable_irq();
			}
			s_received_command_count++;
		}
		else
			s_dropped_command_count++;
	}
}

/**
 * @brief 桥接模块的主循环处理函数。
 * @details 先处理当前响应（上传或超时），总线空闲时再发送下一条命令。
 */
void MotorBridge_Process(void)
{
	/* 保证任意时刻只存在一笔“请求—响应”事务。 */
	if (s_rx_restart_needed != 0U)
		(void)MotorBridge_StartReceive();
	MotorBridge_ProcessResponse();
	MotorBridge_ProcessUSBTransmit();

	if (s_state == MOTOR_BRIDGE_IDLE)
		MotorBridge_ProcessCommand();

	if ((s_round_restart_pending != 0U) &&
		(s_state == MOTOR_BRIDGE_IDLE) &&
		(s_next_poll_id >= BDC_num))
	{
		if (s_command_head == s_command_tail)
		{
			s_round_restart_pending = 0U;
			MotorBridge_BeginPollRound();
		}
		else
		{
			/* Finish the current round's remaining queued slots before restarting. */
			MotorBridge_ProcessCommand();
		}
	}
}

static HAL_StatusTypeDef MotorBridge_StartReceive(void)
{
	HAL_StatusTypeDef status;
	uint32_t primask = __get_PRIMASK();

	__disable_irq();
	s_rx_dma_position = 0U;
	status = HAL_UARTEx_ReceiveToIdle_DMA(s_huart, s_rx_dma, MOTOR_BRIDGE_RX_DMA_SIZE);
	s_rx_restart_needed = (status == HAL_OK) ? 0U : 1U;
	if (primask == 0U)
		__enable_irq();
	return status;
}

void MotorBridge_UART_RxEventCallback(UART_HandleTypeDef *huart, uint16_t size)
{
	uint16_t position;
	(void)size;
	if ((s_huart == NULL) || (huart != s_huart))
		return;

	/* Read the live DMA cursor, not a possibly stale HT/IDLE event position. */
	position = MOTOR_BRIDGE_RX_DMA_SIZE - (uint16_t)__HAL_DMA_GET_COUNTER(huart->hdmarx);
	if (position == MOTOR_BRIDGE_RX_DMA_SIZE)
		position = 0U;
	while (s_rx_dma_position != position)
	{
		uint8_t byte = s_rx_dma[s_rx_dma_position++];
		if (s_rx_dma_position == MOTOR_BRIDGE_RX_DMA_SIZE)
			s_rx_dma_position = 0U;

		if (((s_state == MOTOR_BRIDGE_TRANSMITTING) ||
			(s_state == MOTOR_BRIDGE_WAITING_RESPONSE)) && (s_response_ready == 0U))
		{
			if (s_response_index == 0U)
			{
				if (byte == BDC_PROTOCOL_RESPONSE_SOF)
				{
					s_response_frame[0] = byte;
					s_response_index = 1U;
				}
			}
			else
			{
				s_response_frame[s_response_index++] = byte;
				if (s_response_index >= BDC_PROTOCOL_RESPONSE_SIZE)
				{
					if (MotorBridge_ResponseIsExpected(s_response_frame) != 0U)
						s_response_ready = 1U;
					else
						s_response_error_count++;
					MotorBridge_ResetResponseParser();
				}
			}
		}
	}
}

void MotorBridge_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
	if (huart != s_huart)
		return;
	s_tx_active = 0U;
	if (s_state == MOTOR_BRIDGE_TRANSMITTING)
	{
		s_response_start_count = (uint16_t)__HAL_TIM_GET_COUNTER(&htim3);
		s_state = MOTOR_BRIDGE_WAITING_RESPONSE;
	}
}

void MotorBridge_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
	if ((s_huart == NULL) || (huart != s_huart))
		return;

	MotorBridge_ResetResponseParser();
	if (((huart->ErrorCode & HAL_UART_ERROR_DMA) != 0U) &&
		(s_tx_active != 0U))
	{
		(void)HAL_UART_AbortTransmit(huart);
		if (huart->hdmatx->State != HAL_DMA_STATE_READY)
			(void)HAL_DMA_Abort(huart->hdmatx);
		s_tx_active = 0U;
		if (s_state == MOTOR_BRIDGE_TRANSMITTING)
		{
			s_transmit_error_count++;
			s_response_start_count = (uint16_t)__HAL_TIM_GET_COUNTER(&htim3);
			s_state = MOTOR_BRIDGE_WAITING_RESPONSE;
		}
	}
	(void)HAL_UART_AbortReceive(huart);
	if (huart->hdmarx->State != HAL_DMA_STATE_READY)
		(void)HAL_DMA_Abort(huart->hdmarx);
	s_rx_restart_needed = 1U;
}
/** @brief Release the current USB response slot after CDC consumed its buffer. */
void MotorBridge_USBTransmitCpltCallback(void)
{
	if (s_usb_tx_active != 0U)
	{
		s_usb_response_tail = MotorBridge_NextQueueIndex(s_usb_response_tail);
		__DMB();
		s_usb_tx_active = 0U;
	}
}

/**
 * @brief TIM3 starts a new 50 ms round; TIM4 schedules the next board each 2.5 ms.
 * @note Timer ISRs only enqueue a snapshot. UART transmission remains in the main loop.
 */
void MotorBridge_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
	if ((htim == NULL) || (s_huart == NULL))
		return;

	if (htim->Instance == TIM3)
	{
		if ((s_state != MOTOR_BRIDGE_IDLE) ||
			(s_command_head != s_command_tail) ||
			(s_next_poll_id < BDC_num) ||
			(s_round_restart_pending != 0U))
		{
			s_round_overrun_count++;
			s_round_restart_pending = 1U;
		}
		else
		{
			MotorBridge_BeginPollRound();
		}
	}
	else if ((htim->Instance == TIM4) && (s_next_poll_id < BDC_num))
	{
		/* Do not advance to another address before the prior reply or timeout. */
		if ((s_state != MOTOR_BRIDGE_IDLE) ||
			(s_command_head != s_command_tail))
			return;

		MotorBridge_ScheduleBoard(s_next_poll_id);
		s_next_poll_id++;
		if (s_next_poll_id >= BDC_num)
			(void)HAL_TIM_Base_Stop_IT(&htim4);
	}
}

/* 以下函数只返回初始化以来累计的通信统计值。 */
uint32_t MotorBridge_GetReceivedCommandCount(void)
{
	return s_received_command_count;
}

uint32_t MotorBridge_GetDroppedCommandCount(void)
{
	return s_dropped_command_count;
}

uint32_t MotorBridge_GetTransmitErrorCount(void)
{
	return s_transmit_error_count;
}

uint32_t MotorBridge_GetResponseCount(void)
{
	return s_response_count;
}

uint32_t MotorBridge_GetResponseTimeoutCount(void)
{
	return s_response_timeout_count;
}

uint32_t MotorBridge_GetResponseErrorCount(void)
{
	return s_response_error_count;
}

/* TX DMA owns s_tx_request until the UART transmission-complete callback. */
static void MotorBridge_ProcessCommand(void)
{
	BDCProt_CommandType command;
	HAL_StatusTypeDef status;
	uint32_t primask;
	uint8_t scheduled_id;

	if ((s_rx_restart_needed != 0U) || (s_tx_active != 0U) ||
		(MotorBridge_PopCommand(&command) == 0U))
		return;

	scheduled_id = command.id;
	if (command.id < BDC_num)
	{
		primask = __get_PRIMASK();
		__disable_irq();
		command = BDCProt_Command[command.id];
		command.id = scheduled_id;
		__DMB();
		if (primask == 0U)
			__enable_irq();
	}

	s_tx_request.sof = BDC_PROTOCOL_REQUEST_SOF;
	s_tx_request.id = command.id;
	s_tx_request.command = (uint8_t)command.command;
	s_tx_request.sequence = command.sequence;
	s_tx_request.pData = command.pData;
	s_tx_request.crc16 = MotorBridge_Crc16((const uint8_t *)&s_tx_request,
		BDC_PROTOCOL_REQUEST_SIZE - sizeof(s_tx_request.crc16));

	primask = __get_PRIMASK();
	__disable_irq();
	MotorBridge_ResetResponseParser();
	s_response_ready = 0U;
	s_expected_id = command.id;
	s_expected_sequence = command.sequence;
	s_response_start_count = (uint16_t)__HAL_TIM_GET_COUNTER(&htim3);
	s_state = MOTOR_BRIDGE_TRANSMITTING;
	s_tx_active = 1U;
	status = HAL_UART_Transmit_DMA(s_huart, (const uint8_t *)&s_tx_request,
		BDC_PROTOCOL_REQUEST_SIZE);
	if (status != HAL_OK)
	{
		s_tx_active = 0U;
		s_transmit_error_count++;
		s_state = MOTOR_BRIDGE_IDLE;
	}
	if (primask == 0U)
		__enable_irq();
}
/**
 * @brief 在主循环中处理当前请求的响应上传或超时。
 * @details 响应帧由 USART1 中断填充。当 USB 忙时，保持响应就绪标志，
 *          下次进入主循环继续尝试上传，避免直接丢失从站状态信息。
 */
static void MotorBridge_ProcessResponse(void)
{
	uint8_t abort_tx = 0U;
	uint32_t primask = __get_PRIMASK();
	__disable_irq();

	if (s_state == MOTOR_BRIDGE_TRANSMITTING)
	{
		if (MotorBridge_ResponseTimedOut() != 0U)
		{
			s_state = MOTOR_BRIDGE_ABORTING;
			abort_tx = 1U;
		}
	}
	else if (s_state == MOTOR_BRIDGE_WAITING_RESPONSE)
	{
		if (s_response_ready != 0U)
		{
			uint8_t next = MotorBridge_NextQueueIndex(s_usb_response_head);
			if (next != s_usb_response_tail)
			{
				memcpy(s_usb_response_queue[s_usb_response_head], s_response_frame,
					BDC_PROTOCOL_RESPONSE_SIZE);
				__DMB();
				s_usb_response_head = next;
				s_response_count++;
			}
			else
				s_response_error_count++;
			s_response_ready = 0U;
			s_state = MOTOR_BRIDGE_IDLE;
		}
		else if (MotorBridge_ResponseTimedOut() != 0U)
		{
			s_response_timeout_count++;
			MotorBridge_ResetResponseParser();
			s_state = MOTOR_BRIDGE_IDLE;
		}
	}
	if (primask == 0U)
		__enable_irq();

	if (abort_tx != 0U)
	{
		(void)HAL_UART_AbortTransmit(s_huart);
		s_tx_active = 0U;
		s_transmit_error_count++;
		s_response_start_count = (uint16_t)__HAL_TIM_GET_COUNTER(&htim3);
		s_state = MOTOR_BRIDGE_WAITING_RESPONSE;
	}
}
static uint8_t MotorBridge_ResponseTimedOut(void)
{
	uint16_t now = (uint16_t)__HAL_TIM_GET_COUNTER(&htim3);
	uint32_t elapsed;

	if (now >= s_response_start_count)
		elapsed = (uint32_t)(now - s_response_start_count);
	else
		elapsed = MOTOR_BRIDGE_TIM3_COUNTER_PERIOD - s_response_start_count + now;

	return (elapsed >= BDC_PROTOCOL_RESPONSE_TIMEOUT_TIMER_TICKS) ? 1U : 0U;
}

/** @brief Send queued telemetry without blocking motor polling on USB backpressure. */
static void MotorBridge_ProcessUSBTransmit(void)
{
	uint8_t tail;
	uint32_t primask;

	primask = __get_PRIMASK();
	__disable_irq();
	if ((s_usb_tx_active != 0U) ||
		(s_usb_response_tail == s_usb_response_head))
	{
		if (primask == 0U)
			__enable_irq();
		return;
	}

	tail = s_usb_response_tail;
	s_usb_tx_active = 1U;
	__DMB();
	/* Completion of a tactile transfer must not release a motor queue slot. */
	if (CDC_Transmit_FS(s_usb_response_queue[tail],
		BDC_PROTOCOL_RESPONSE_SIZE) != USBD_OK)
		s_usb_tx_active = 0U;
	if (primask == 0U)
		__enable_irq();
}

/**
 * @brief 按 CRC-16/CCITT-FALSE 算法计算校验值。
 * @param data 参与校验的首字节地址。
 * @param length 参与校验的字节数。
 * @return 初值 0xFFFF、多项式 0x1021、无输入/输出反射、无最终异或的 CRC。
 */
static unsigned short MotorBridge_Crc16(
    const unsigned char *data,
    unsigned short length)
{
	unsigned short crc = 0xFFFFU;
	unsigned short index;
	uint8_t bit;

	if (data == NULL)
		return 0U;

	/* 逐字节、逐位执行 CCITT-FALSE 多项式运算。 */
	for (index = 0U; index < length; index++)
	{
		crc ^= (unsigned short)data[index] << 8U;
		for (bit = 0U; bit < 8U; bit++)
		{
			if ((crc & 0x8000U) != 0U)
				crc = (unsigned short)((crc << 1U) ^ 0x1021U);
			else
				crc <<= 1U;
		}
	}

	return crc;
}

/**
 * @brief 验证 PC 下发的 10 B 请求帧是否符合协议。
 * @details Validate SOF, command, ID, broadcast restriction and CRC.
 */
static uint8_t MotorBridge_RequestIsValid(const BDCProt_Request *request)
{
	unsigned short crc;

	if (request == NULL)
		return 0U;

	/* 广播地址 0xFF 的唯一合法命令为 DISABLE。 */
	if ((request->sof != BDC_PROTOCOL_REQUEST_SOF) ||
		(request->command > BDC_CMD_DISABLE) ||
		((request->id >= BDC_num) &&
		 (request->id != BDC_PROTOCOL_BROADCAST_ID)) ||
		((request->id == BDC_PROTOCOL_BROADCAST_ID) &&
		 (request->command != BDC_CMD_DISABLE)))
		return 0U;

	crc = MotorBridge_Crc16(
		(const uint8_t *)request,
		BDC_PROTOCOL_REQUEST_SIZE - sizeof(request->crc16));
	return (crc == request->crc16) ? 1U : 0U;
}

/**
 * @brief 验证收到的 16 B 帧是否为当前轮询请求的有效响应。
 * @details 响应必须同时匹配帧头、目标 ID、请求 sequence 和 CRC，
 *          以避免把总线噪声、旧帧或其它板的帧错误上传给 PC。
 */
static uint8_t MotorBridge_ResponseIsExpected(const uint8_t *frame)
{
	unsigned short received_crc;
	unsigned short calculated_crc;

	if (frame == NULL)
		return 0U;

	if ((frame[0] != BDC_PROTOCOL_RESPONSE_SOF) ||
		(frame[1] != s_expected_id) ||
		(frame[2] != s_expected_sequence))
		return 0U;

	/* 协议规定 CRC16 在帧末尾采用小端序存储。 */
	received_crc = (unsigned short)frame[14] |
		((unsigned short)frame[15] << 8U);
	calculated_crc = MotorBridge_Crc16(frame, 14U);

	return (received_crc == calculated_crc) ? 1U : 0U;
}

/** @brief 丢弃当前未完成响应帧，重新从帧头 0x5A 开始同步。 */
static void MotorBridge_ResetResponseParser(void)
{
	s_response_index = 0U;
}

/** @brief 获取环形队列的下一个索引；到达末尾后回绕到 0。 */
static uint8_t MotorBridge_NextQueueIndex(uint8_t index)
{
	index++;
	if (index >= MOTOR_BRIDGE_COMMAND_QUEUE_SLOT_NUM)
		index = 0U;

	return index;
}

/** @brief Start a polling round, scheduling board 0 immediately. */
static void MotorBridge_BeginPollRound(void)
{

	s_next_poll_id = 0U;
	__HAL_TIM_SET_COUNTER(&htim4, 0U);
	__HAL_TIM_CLEAR_FLAG(&htim4, TIM_FLAG_UPDATE);
	MotorBridge_ScheduleBoard(s_next_poll_id);
	s_next_poll_id++;
	if (HAL_TIM_Base_Start_IT(&htim4) != HAL_OK)
		s_transmit_error_count++;
}

/** @brief Snapshot the most recent command for an ID and append it to the TX queue. */
static void MotorBridge_ScheduleBoard(uint8_t id)
{
	BDCProt_CommandType command;
	uint32_t primask = __get_PRIMASK();

	if (id >= BDC_num)
		return;

	__disable_irq();
	command = BDCProt_Command[id];
	__DMB();
	if (primask == 0U)
		__enable_irq();

	/* Use the slot's ID even if a debugger accidentally edits the struct's id field. */
	command.id = id;
	if (MotorBridge_PushCommand(&command) == 0U)
		s_dropped_command_count++;
}

/**
 * @brief 将命令原子写入待发送环形队列。
 * @note Timer interrupts schedule slots; the main loop consumes them.
 * @return 1 表示成功；0 表示参数为空或队列已满。
 */
static uint8_t MotorBridge_PushCommand(const BDCProt_CommandType *command)
{
	uint8_t head;
	uint8_t next;
	uint32_t primask;

	if (command == NULL)
		return 0U;

	/* 保存调用前的中断使能状态，退出时不错误地打开原本关闭的中断。 */
	primask = __get_PRIMASK();
	__disable_irq();

	head = s_command_head;
	next = MotorBridge_NextQueueIndex(head);
	/* next 追上 tail 表示队列已满；保留一个空槽位用于区分满/空。 */
	if (next == s_command_tail)
	{
		if (primask == 0U)
			__enable_irq();
		return 0U;
	}

	/* 先写完整命令，再推进 head，避免消费者看到半写入数据。 */
	s_command_queue[head] = *command;
	__DMB();
	s_command_head = next;

	if (primask == 0U)
		__enable_irq();

	return 1U;
}

/**
 * @brief 从命令环形队列取出最早入队的一条命令。
 * @note The main loop consumes slots scheduled by timer interrupts.
 * @return 1 表示成功；0 表示参数为空或队列为空。
 */
static uint8_t MotorBridge_PopCommand(BDCProt_CommandType *command)
{
	uint8_t tail;
	uint32_t primask;

	if (command == NULL)
		return 0U;

	/* 保存并暂时关闭中断，保证检查与读取 tail 的过程不可分割。 */
	primask = __get_PRIMASK();
	__disable_irq();

	/* tail 与 head 相等时，队列中没有待发送命令。 */
	if (s_command_tail == s_command_head)
	{
		if (primask == 0U)
			__enable_irq();
		return 0U;
	}

	/* 先复制命令内容，再推进 tail 释放该槽位。 */
	tail = s_command_tail;
	*command = s_command_queue[tail];
	__DMB();
	s_command_tail = MotorBridge_NextQueueIndex(tail);

	if (primask == 0U)
		__enable_irq();

	return 1U;
}

