/* Run from the project root with an existing host GCC:
 * gcc -std=c11 -Wall -Wextra -Werror -I tests -I BDC_CTRL\protocol tests\protocol_encoder_test.c BDC_CTRL\protocol\bdc_protocol.c -o tests\protocol_encoder_test.exe
 * tests\protocol_encoder_test.exe
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "bdc_protocol.h"

static uint32_t tick;
static HAL_StatusTypeDef rx_status = HAL_OK, tx_status = HAL_OK;
static unsigned rx_calls, tx_calls;
uint32_t HAL_GetTick(void) { return tick; }
HAL_StatusTypeDef HAL_UARTEx_ReceiveToIdle_DMA(UART_HandleTypeDef *u, uint8_t *p, uint16_t n)
{ (void)u; (void)p; assert(n == 10); ++rx_calls; return rx_status; }
HAL_StatusTypeDef HAL_UART_Transmit_IT(UART_HandleTypeDef *u, uint8_t *p, uint16_t n)
{ (void)u; (void)p; assert(n == 16); ++tx_calls; return tx_status; }
static uint16_t crc(const uint8_t *p, unsigned n)
{
    uint16_t c = 0xffff; unsigned i;
    while (n--) { c ^= (uint16_t)*p++ << 8; for (i=0; i<8; ++i) c = (c & 0x8000) ? (uint16_t)((c << 1) ^ 0x1021) : (uint16_t)(c << 1); }
    return c;
}
static void frame(BDC_Protocol *p, uint8_t id, uint8_t cmd, uint8_t seq, uint32_t bits)
{
    uint16_t c; uint8_t *b = p->rx_buffer;
    b[0]=0xa5; b[1]=id; b[2]=cmd; b[3]=seq;
    b[4]=(uint8_t)bits; b[5]=(uint8_t)(bits>>8); b[6]=(uint8_t)(bits>>16); b[7]=(uint8_t)(bits>>24);
    c=crc(b,8); b[8]=(uint8_t)c; b[9]=(uint8_t)(c>>8);
}
static void protocol_test(void)
{
    UART_HandleTypeDef uart; BDC_Protocol *p = new_BDC_Protocol(&uart);
    BDC_CMD cmd; float value; uint8_t valid; uint32_t old;
    assert(sizeof(BDCProt_Request)==10 && sizeof(BDCProt_Response)==16);
    assert(crc((const uint8_t*)"123456789",9)==0x29b1);
    tick=100; assert(BDC_Protocol_Init(p,0)==HAL_OK); assert(BDC_Protocol_Init(p,16)==HAL_OK);
    assert(BDC_Protocol_Init(p,17)==HAL_ERROR && p->board_id==16);
    {
        unsigned id;
        for (id=0; id<17; ++id) {
            assert(BDC_Protocol_Init(p,(uint8_t)id)==HAL_OK);
            frame(p,(uint8_t)id,BDC_CMD_DISABLE,(uint8_t)id,0);
            assert(BDC_Protocol_HandleReceive(p,10,&cmd,&value,&valid)==HAL_OK && valid);
            assert(p->response_sequence==id && p->board_id==id && p->response_required);
        }
    }
    tick=200; frame(p,16,BDC_CMD_IMP_POS,42,0x3f800000);
    assert(BDC_Protocol_HandleReceive(p,10,&cmd,&value,&valid)==HAL_OK);
    assert(valid && cmd==BDC_CMD_IMP_POS && value==1.0f && p->response_required && p->last_valid_command_tick==200);
    assert(BDC_Protocol_TransmitResponse(p,0x1234,12.0f,25.0f,5)==HAL_OK);
    assert(tx_calls==1 && p->tx_pending && p->tx_response.id==16 && p->tx_response.sequence==42);
    assert(p->tx_response.crc16==crc((const uint8_t*)&p->tx_response,14));
    assert(BDC_Protocol_HandleTransmitComplete(p)==HAL_OK && !p->tx_pending);
    old=p->last_valid_command_tick; tick=300;
    frame(p,15,0,0,0); assert(BDC_Protocol_HandleReceive(p,10,&cmd,&value,&valid)==HAL_OK && !valid && p->last_valid_command_tick==old);
    frame(p,16,0,0,0); p->rx_buffer[8]^=1; assert(BDC_Protocol_HandleReceive(p,10,&cmd,&value,&valid)==HAL_OK && !valid);
    frame(p,16,8,0,0); assert(BDC_Protocol_HandleReceive(p,10,&cmd,&value,&valid)==HAL_OK && !valid);
    frame(p,16,0,0,0); p->rx_buffer[0]=0; assert(BDC_Protocol_HandleReceive(p,10,&cmd,&value,&valid)==HAL_OK && !valid);
    frame(p,16,0,0,0); assert(BDC_Protocol_HandleReceive(p,5,&cmd,&value,&valid)==HAL_OK && !valid);
    frame(p,16,BDC_CMD_CAL_ZERO,7,0);
    assert(BDC_Protocol_HandleReceive(p,10,&cmd,&value,&valid)==HAL_OK && valid && cmd==BDC_CMD_CAL_ZERO);
    assert(BDC_Protocol_HandleReceive(p,10,&cmd,&value,&valid)==HAL_OK && valid && cmd==BDC_CMD_CAL_ZERO);
    old=p->last_valid_command_tick;
    frame(p,255,BDC_CMD_ENABLE,0,0); assert(BDC_Protocol_HandleReceive(p,10,&cmd,&value,&valid)==HAL_OK && !valid);
    frame(p,255,BDC_CMD_DISABLE,0,0); rx_status=HAL_BUSY;
    assert(BDC_Protocol_HandleReceive(p,10,&cmd,&value,&valid)==HAL_BUSY && valid && cmd==BDC_CMD_DISABLE && !p->response_required);
    rx_status=HAL_OK; assert(p->last_valid_command_tick==old);
    assert(!BDC_Protocol_IsCommandTimedOut(p,old+1000)); assert(BDC_Protocol_IsCommandTimedOut(p,old+1001));
    p->last_valid_command_tick=0xfffffff0u; assert(BDC_Protocol_IsCommandTimedOut(p,0x3d9u));
    frame(p,16,0,1,0); assert(BDC_Protocol_HandleReceive(p,10,&cmd,&value,&valid)==HAL_OK && valid);
    tx_status=HAL_BUSY; assert(BDC_Protocol_TransmitResponse(p,0,0,0,0)==HAL_BUSY && !p->tx_pending && !p->response_required);
}
int main(void) { protocol_test(); puts("protocol tests passed"); return 0; }
