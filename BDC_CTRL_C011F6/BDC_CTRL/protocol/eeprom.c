#include "stm32c0xx_hal.h"
#include "eeprom.h"

HAL_StatusTypeDef Flash_Write_Data(uint16_t data)
{
    HAL_StatusTypeDef status;
    FLASH_EraseInitTypeDef eraseInitStruct = {0};
    uint32_t pageError = 0;
    uint64_t data64 = 0xFFFFFFFF00000000ULL |
                      ((uint64_t)ZERO_OFFSET_FLASH_MAGIC << 16U) |
                      (uint64_t)data;

    status = HAL_FLASH_Unlock();
    if (status != HAL_OK)
    {
        return status;
    }

    eraseInitStruct.TypeErase   = FLASH_TYPEERASE_PAGES;
    eraseInitStruct.Page        = ZERO_OFFSET_FLASH_PAGE;
    eraseInitStruct.NbPages     = 1;

    status = HAL_FLASHEx_Erase(&eraseInitStruct, &pageError);
    if (status != HAL_OK)
    {
        HAL_FLASH_Lock();
        return status;
    }


    status = HAL_FLASH_Program(FLASH_TYPEPROGRAM_DOUBLEWORD, ZERO_OFFSET_FLASH_ADDRESS, data64);

    HAL_FLASH_Lock();

    return status;
}


HAL_StatusTypeDef Flash_Read_Data(uint16_t *pData)
{
    uint64_t rawData;
    uint16_t magic;

    if (pData == NULL)
    {
        return HAL_ERROR;
    }

    rawData = *(__IO const uint64_t *)ZERO_OFFSET_FLASH_ADDRESS;
    *pData = (uint16_t)rawData;
    magic = (uint16_t)(rawData >> 16U);

    if ((magic != ZERO_OFFSET_FLASH_MAGIC) || (*pData == ZERO_OFFSET_FLASH_ERASED_VALUE))
    {
        return HAL_ERROR;
    }

    return HAL_OK;
}
