/**
 * cyberpi_firmware/main/font_chip.c — GT30L24A3W SPI font chip driver
 * Chip CS=GPIO27, shares SPI bus with LCD (MOSI=2, MISO=26, CLK=4)
 */
#include "font_chip.h"
#include "efont_supp.h"
#include "esp_log.h"
#include "driver/spi_master.h"
#include "driver/gpio.h"
#include <string.h>

#define FONT_CS_GPIO    27
#define FONT_MISO_GPIO  26
#define FONT_MOSI_GPIO  2
#define FONT_CLK_GPIO   4

static spi_device_handle_t font_spi;

/* Pre-compiled GT30L24A3W library */
extern unsigned long U2G_GetData_16X16(unsigned int unicode, unsigned char *DZ_Data);
extern unsigned long U2G_GetData_24X24(unsigned int unicode, unsigned char *DZ_Data);

/*
 * r_dat_bat — read from GT30L24A3W SPI font chip
 * Called by the pre-compiled library internally
 */
unsigned char r_dat_bat(unsigned long ReadAddr, unsigned int NumByteToRead, unsigned char *pBuffer)
{
    gpio_set_level(FONT_CS_GPIO, 0);

    uint8_t cmd[4] = {
        0x03,
        (uint8_t)(ReadAddr >> 16),
        (uint8_t)(ReadAddr >> 8),
        (uint8_t)(ReadAddr)
    };
    spi_transaction_t t = {.length = 32, .tx_buffer = cmd};
    spi_device_transmit(font_spi, &t);

    memset(&t, 0, sizeof(t));
    t.rxlength = NumByteToRead * 8;
    t.rx_buffer = pBuffer;
    spi_device_transmit(font_spi, &t);

    gpio_set_level(FONT_CS_GPIO, 1);
    return 0;
}

void font_chip_init(void)
{
    gpio_set_direction(FONT_CS_GPIO, GPIO_MODE_OUTPUT);
    gpio_set_level(FONT_CS_GPIO, 1);

    spi_device_interface_config_t devcfg = {
        .clock_speed_hz = 20 * 1000 * 1000,
        .mode = 0,
        .spics_io_num = -1,
        .queue_size = 7,
        .flags = SPI_DEVICE_HALFDUPLEX,
    };
    spi_bus_add_device(SPI2_HOST, &devcfg, &font_spi);
    ESP_LOGI("FONT", "GT30L24A3W ready");
}

int font_chip_get_16x16(uint16_t unicode, uint8_t *bitmap_out)
{
    if (unicode < 0x80) return -1; // ASCII

    // Try efont supplement first — covers 20,992 CJK characters
    if (efont_supp_lookup(unicode, bitmap_out) == 0) return 0;

    // Fall back to GT30L24A3W font chip (GB2312)
    unsigned long gb_code = U2G_GetData_16X16(unicode, bitmap_out);
    if (gb_code == 0) return -2;

    // Only trust GB2312 codes (both bytes >= 0xA1)
    uint8_t hi = gb_code >> 8;
    uint8_t lo = gb_code & 0xFF;
    if (hi < 0xA1 || lo < 0xA1) return -2;

    // Verify bitmap has actual data
    int sum = 0;
    for (int j = 0; j < 32; j++) sum += bitmap_out[j];
    if (sum == 0) return -2;

    return 0;
}

int font_chip_get_24x24(uint16_t unicode, uint8_t *bitmap_out)
{
    if (unicode < 0x80) return -1;

    // GB18030 24x24 covers all Chinese including Traditional
    unsigned long gb_code = U2G_GetData_24X24(unicode, bitmap_out);
    if (gb_code == 0) return -2;

    int sum = 0;
    for (int j = 0; j < 72; j++) sum += bitmap_out[j];
    if (sum == 0) return -2;

    return 0;
}
