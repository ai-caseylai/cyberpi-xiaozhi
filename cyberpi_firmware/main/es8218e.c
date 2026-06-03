/**
 * cyberpi_firmware/main/es8218e.c — ES8218E ADC codec driver
 * Exact register map from Makeblock CyberPi Arduino Library
 */
#include "es8218e.h"
#include "driver/i2c.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static void i2c_w(uint8_t reg, uint8_t v) {
    uint8_t b[2]={reg,v};
    i2c_master_write_to_device(I2C_NUM_1, ES8218E_ADDR, b, 2, pdMS_TO_TICKS(100));
}

void es8218e_init(void) {
    ESP_LOGI("ES8218E","Init addr=0x%02X", ES8218E_ADDR);

    // === Exact sequence from official es8218e_start() ===

    // Reset
    i2c_w(0x00, 0x3f);
    i2c_w(0x00, 0x00);

    // Clock manager: slave mode, BCLK/LRCK from ESP32 I2S master
    i2c_w(0x01, 0x10); vTaskDelay(pdMS_TO_TICKS(1));
    i2c_w(0x01, 0x00);
    i2c_w(0x01, 0x0f);   // slave mode
    i2c_w(0x02, 0x01);   // CLK_MANAGER2
    i2c_w(0x03, 0x20);   // CLK_MANAGER3: 4096000/16000/8=32

    // Serial data: 16-bit I2S format
    i2c_w(0x07, 0x0c);   // 16-bit, I2S format

    // ADC control
    i2c_w(0x10, 0x18);   // ADC_CONTROL2: high pass filter + soft ramp
    i2c_w(0x14, 0xA0);   // ADC_CONTROL6: ALC level -1.5dB
    i2c_w(0x0D, 0x30);   // SYSTEM_CONTROL6: power-ini time
    i2c_w(0x0E, 0x20);   // SYSTEM_CONTROL7: power-up time
    i2c_w(0x18, 0x04);   // ADC_CONTROL10: HPF slow coeff
    i2c_w(0x19, 0x04);   // ADC_CONTROL11: HPF fast coeff
    i2c_w(0x0F, 0x30);   // ADC_CONTROL1: LIN2/RIN2, PGA=0dB (prevent clipping)

    // Power on
    i2c_w(0x08, 0x00);   // SYSTEM_CONTROL1: power on
    i2c_w(0x00, 0x80);   // IC start

    // ALC
    uint8_t pga = 0xc0 | (uint8_t)((20.5+6.5)/1.5);
    i2c_w(0x12, pga);    // ADC_CONTROL4: ALC ON
    i2c_w(0x11, 0x00);   // ADC volume 0dB

    ESP_LOGI("ES8218E","Ready");
}
