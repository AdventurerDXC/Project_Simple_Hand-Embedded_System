
#include "tactile_sense.h"
#include "main.h"
#include <stddef.h>

/*
 * 切换模拟通道后丢弃的ADC采样次数。
 * 用于减小前一个通道残留电压的影响。
 */
#define TACTILE_ADC_DUMMY_SAMPLE_NUM      1U

/*
 * 每个压阻点实际参与平均的ADC采样次数。
 */
#define TACTILE_ADC_AVERAGE_SAMPLE_NUM    3U

#define TACTILE_ADC_TIMEOUT_MS            2U

static ADC_HandleTypeDef *s_hadc = NULL;

/* Y0~Y5对应的GPIO端口 */
static GPIO_TypeDef * const s_y_ports[TACTILE_ROW_NUM] =
{
    Y0_GPIO_Port,
    Y1_GPIO_Port,
    Y2_GPIO_Port,
    Y3_GPIO_Port,
    Y4_GPIO_Port,
    Y5_GPIO_Port
};

/* Y0~Y5对应的GPIO引脚 */
static const uint16_t s_y_pins[TACTILE_ROW_NUM] =
{
    Y0_Pin,
    Y1_Pin,
    Y2_Pin,
    Y3_Pin,
    Y4_Pin,
    Y5_Pin
};

static void TactileSense_MuxEnable(void);
static void TactileSense_MuxDisable(void);
static void TactileSense_MuxSelect(uint8_t channel);

static void TactileSense_SetAllRowsHighImpedance(void);
static void TactileSense_SelectRow(uint8_t row);

static HAL_StatusTypeDef TactileSense_ReadADCOnce(
    uint16_t *adc_value);

static HAL_StatusTypeDef TactileSense_ReadADCAverage(
    uint16_t *adc_value);

/**
 * @brief 初始化触觉采集模块
 */
HAL_StatusTypeDef TactileSense_Init(ADC_HandleTypeDef *hadc)
{
    if (hadc == NULL)
        return HAL_ERROR;

    s_hadc = hadc;

    /* RS2251的ENABLE#低电平有效。
     * 初始化时先关闭模拟开关。*/
    TactileSense_MuxDisable();

    /* 未选中的Y行必须保持高阻态。*/
    TactileSense_SetAllRowsHighImpedance();

    /* 默认选择X0。*/
    TactileSense_MuxSelect(0U);

    return HAL_OK;
}

/**
 * @brief 扫描整个6×6压阻阵列
 */
HAL_StatusTypeDef TactileSense_Scan(uint16_t data[TACTILE_POINT_NUM])
{
    uint8_t row;
    uint8_t col;
    uint8_t point_index;
    HAL_StatusTypeDef status;

    if ((s_hadc == NULL) || (data == NULL))
        return HAL_ERROR;

    TactileSense_MuxDisable();
    TactileSense_SetAllRowsHighImpedance();

    for (row = 0U; row < TACTILE_ROW_NUM; row++)
    {
        /* 切换Y行前先关闭模拟开关。*/
        TactileSense_MuxDisable();

        /* 当前Y行输出低电平，
         * 其余Y行保持高阻状态。*/
        TactileSense_SelectRow(row);

        for (col = 0U; col < TACTILE_COL_NUM; col++)
        {
            /* 先关闭模拟开关，再切换S0~S2。*/
            TactileSense_MuxDisable();
            TactileSense_MuxSelect(col);
            TactileSense_MuxEnable();

            point_index = (uint8_t)(row * TACTILE_COL_NUM + col);

            status = TactileSense_ReadADCAverage(&data[point_index]);

            if (status != HAL_OK)
            {
                TactileSense_MuxDisable();
                TactileSense_SetAllRowsHighImpedance();

                return status;
            }
        }
    }

    /* 一帧扫描结束后关闭MUX，
     * 并释放所有Y行。*/
    TactileSense_MuxDisable();
    TactileSense_SetAllRowsHighImpedance();

    return HAL_OK;
}

/**
 * @brief 使能RS2251模拟开关
 *
 * ENABLE#为低电平有效。
 */
static void TactileSense_MuxEnable(void)
{
    HAL_GPIO_WritePin(EN_GPIO_Port, EN_Pin, GPIO_PIN_RESET);
}

/**
 * @brief 关闭RS2251模拟开关
 */
static void TactileSense_MuxDisable(void)
{
    HAL_GPIO_WritePin(EN_GPIO_Port, EN_Pin, GPIO_PIN_SET);
}

/**
 * @brief 选择RS2251输入通道
 *
 * channel = 0：X0
 * channel = 1：X1
 * ...
 * channel = 5：X5
 */
static void TactileSense_MuxSelect(uint8_t channel)
{
    HAL_GPIO_WritePin(S0_GPIO_Port, S0_Pin, ((channel & 0x01U) != 0U) ?
        GPIO_PIN_SET : GPIO_PIN_RESET);

    HAL_GPIO_WritePin(S1_GPIO_Port, S1_Pin, ((channel & 0x02U) != 0U) ?
        GPIO_PIN_SET : GPIO_PIN_RESET);

    HAL_GPIO_WritePin(S2_GPIO_Port, S2_Pin, ((channel & 0x04U) != 0U) ?
        GPIO_PIN_SET : GPIO_PIN_RESET);
}

/**
 * @brief 将所有Y行设置为高阻状态
 *
 * GPIO的模拟输入模式关闭数字输入缓冲和上下拉，
 * 可以作为较好的高阻状态使用。
 */
static void TactileSense_SetAllRowsHighImpedance(void)
{
    GPIO_InitTypeDef gpio_init = {0};
    uint8_t row;

    gpio_init.Mode = GPIO_MODE_ANALOG;
    gpio_init.Pull = GPIO_NOPULL;

    for (row = 0U; row < TACTILE_ROW_NUM; row++)
    {
        gpio_init.Pin = s_y_pins[row];

        HAL_GPIO_Init(
            s_y_ports[row],
            &gpio_init);
    }
}

/**
 * @brief 选择一条Y行
 *
 * 当前Y行输出低电平，其余Y行保持高阻。
 */
static void TactileSense_SelectRow(uint8_t row)
{
    GPIO_InitTypeDef gpio_init = {0};

    if (row >= TACTILE_ROW_NUM)
        return;

    /* 所有行先恢复高阻。*/
    TactileSense_SetAllRowsHighImpedance();

    /* 在切换到输出模式之前，
     * 预先将GPIO输出寄存器写为低。*/
    HAL_GPIO_WritePin(s_y_ports[row], s_y_pins[row], GPIO_PIN_RESET);

    gpio_init.Pin   = s_y_pins[row];
    gpio_init.Mode  = GPIO_MODE_OUTPUT_PP;
    gpio_init.Pull  = GPIO_NOPULL;
    gpio_init.Speed = GPIO_SPEED_FREQ_LOW;

    HAL_GPIO_Init(s_y_ports[row], &gpio_init);

    HAL_GPIO_WritePin(s_y_ports[row], s_y_pins[row], GPIO_PIN_RESET);
}

/**
 * @brief 执行一次ADC转换
 */
static HAL_StatusTypeDef TactileSense_ReadADCOnce(uint16_t *adc_value)
{
    HAL_StatusTypeDef status;

    if ((s_hadc == NULL) || (adc_value == NULL))
        return HAL_ERROR;

    status = HAL_ADC_Start(s_hadc);

    if (status != HAL_OK)
        return status;

    status = HAL_ADC_PollForConversion(s_hadc, TACTILE_ADC_TIMEOUT_MS);

    if (status != HAL_OK)
    {
        (void)HAL_ADC_Stop(s_hadc);

        return status;
    }

    *adc_value = (uint16_t)HAL_ADC_GetValue(s_hadc);

    status = HAL_ADC_Stop(s_hadc);

    return status;
}

/**
 * @brief 对单个压阻单元进行多次ADC采样并取平均值
 */
static HAL_StatusTypeDef TactileSense_ReadADCAverage(uint16_t *adc_value)
{
    uint8_t sample_index;
    uint16_t adc_temp;
    uint32_t adc_sum = 0U;
    HAL_StatusTypeDef status;

    if (adc_value == NULL)
        return HAL_ERROR;

    /* 切换模拟开关后，
     * 丢弃前几次ADC转换结果。*/
    for (sample_index = 0U;
         sample_index < TACTILE_ADC_DUMMY_SAMPLE_NUM;
         sample_index++)
    {
        status = TactileSense_ReadADCOnce(&adc_temp);

        if (status != HAL_OK)
            return status;
    }

    /* 对后续转换结果取平均值。*/
    for (sample_index = 0U;
         sample_index < TACTILE_ADC_AVERAGE_SAMPLE_NUM;
         sample_index++)
    {
        status = TactileSense_ReadADCOnce(&adc_temp);

        if (status != HAL_OK)
            return status;

        adc_sum += adc_temp;
    }

    /* 加入除数的一半，实现四舍五入。*/
    *adc_value = (uint16_t)((adc_sum + 
            TACTILE_ADC_AVERAGE_SAMPLE_NUM / 2U) /
            TACTILE_ADC_AVERAGE_SAMPLE_NUM);

    return HAL_OK;
}

void RawDataToForce(uint16_t data[TACTILE_POINT_NUM], uint16_t force[TACTILE_POINT_NUM])
{
    for(uint8_t i = 0U; i < TACTILE_POINT_NUM; i++) {
        if (data[i] == 0U) {
            force[i] = UINT16_MAX;
            continue;
        }

        float res_reciprocal = (float)(ADC_RANGE - data[i]) / data[i] / REF_RESISTOR;
        float force_f = res_reciprocal * R_F_RATIO;
        if(force_f > UINT16_MAX)  force_f = UINT16_MAX;
        
        force[i] = (uint16_t)force_f;
    }
}
