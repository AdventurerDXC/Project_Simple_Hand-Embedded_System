#ifndef EEPROM_H
#define EEPROM_H

#include "main.h"

/* Reserve the final 2 KiB Flash page exclusively for the encoder zero offset. */
#define ZERO_OFFSET_FLASH_PAGE_SIZE       FLASH_PAGE_SIZE
#define ZERO_OFFSET_FLASH_PAGE             ((FLASH_SIZE / ZERO_OFFSET_FLASH_PAGE_SIZE) - 1U)
#define ZERO_OFFSET_FLASH_ADDRESS          (FLASH_BASE + FLASH_SIZE - sizeof(uint64_t))
#define ZERO_OFFSET_FLASH_MAGIC            0x5A3CU
#define ZERO_OFFSET_FLASH_ERASED_VALUE     0xFFFFU

/**
 * @brief Stores an encoder zero offset in the reserved final Flash page.
 * @note The application image must not use the final Flash page.
 */
HAL_StatusTypeDef Flash_Write_Data(uint16_t data);

/**
 * @brief Reads the stored encoder zero offset.
 * @retval HAL_OK if a valid value is present; HAL_ERROR if the storage is erased.
 */
HAL_StatusTypeDef Flash_Read_Data(uint16_t *pData);



#endif
