/**
 * cyberpi_firmware/main/font_chip.h — GT30L24A3W font chip driver
 * SPI shared with LCD, separate CS on GPIO 27
 */
#ifndef FONT_CHIP_H
#define FONT_CHIP_H
#include <stdint.h>

void font_chip_init(void);
int  font_chip_get_16x16(uint16_t unicode, uint8_t *bitmap_out);
int  font_chip_get_24x24(uint16_t unicode, uint8_t *bitmap_out);

#endif
