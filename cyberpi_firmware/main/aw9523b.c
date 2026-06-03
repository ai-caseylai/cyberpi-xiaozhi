/**
 * cyberpi_firmware/main/aw9523b.c — AW9523B GPIO expander + LED driver
 * Fixed based on Makeblock CyberPi Arduino Library
 */
#include "aw9523b.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2c.h"

#define I2C_MASTER_NUM I2C_NUM_1  // was I2C_NUM_0
#define I2C_SDA_IO    19          // was 21
#define I2C_SCL_IO    18          // was 22
#define I2C_FREQ      400000      // was 100000

static uint8_t pinDataP0, pinDataP1, pinModeP0 = 0xff, pinModeP1 = 0xff;

static esp_err_t i2c_write_reg(uint8_t addr, uint8_t reg, uint8_t val) {
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, addr << 1, 1);
    i2c_master_write_byte(cmd, reg, 1);
    i2c_master_write_byte(cmd, val, 1);
    i2c_master_stop(cmd);
    esp_err_t r = i2c_master_cmd_begin(I2C_MASTER_NUM, cmd, pdMS_TO_TICKS(100));
    i2c_cmd_link_delete(cmd);
    return r;
}
static uint8_t i2c_read_reg(uint8_t addr, uint8_t reg) {
    uint8_t data = 0;
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (addr << 1) | 0, 1);
    i2c_master_write_byte(cmd, reg, 1);
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (addr << 1) | 1, 1);
    i2c_master_read_byte(cmd, &data, 1);
    i2c_master_stop(cmd);
    i2c_master_cmd_begin(I2C_MASTER_NUM, cmd, pdMS_TO_TICKS(100));
    i2c_cmd_link_delete(cmd);
    return data;
}
static int modifyBit(int v, int pos, int bit) {
    return (v & ~(1<<pos)) | ((bit<<pos) & (1<<pos));
}

void aw9523b_init(void) {
    i2c_config_t cfg = {.mode=I2C_MODE_MASTER, .sda_io_num=I2C_SDA_IO, .scl_io_num=I2C_SCL_IO,
                        .sda_pullup_en=GPIO_PULLUP_ENABLE, .scl_pullup_en=GPIO_PULLUP_ENABLE,
                        .master.clk_speed=I2C_FREQ};
    i2c_param_config(I2C_MASTER_NUM, &cfg);
    i2c_driver_install(I2C_MASTER_NUM, cfg.mode, 0, 0, 0);

    // Chip 0: LED driver (0x5B) — all pins in LED mode (work_mode: 0=LED, 1=GPIO)
    i2c_write_reg(AW9523B_ADDR1, REG_SWRST, 0x00);
    vTaskDelay(pdMS_TO_TICKS(10));
    i2c_write_reg(AW9523B_ADDR1, REG_WORK_MODE_P0, 0x00);
    i2c_write_reg(AW9523B_ADDR1, REG_WORK_MODE_P1, 0x00);
    i2c_write_reg(AW9523B_ADDR1, REG_CTRL, 0x00);

    // Chip 1: GPIO expander (0x58) — mixed GPIO/LED mode
    i2c_write_reg(AW9523B_ADDR2, REG_SWRST, 0x00);
    vTaskDelay(pdMS_TO_TICKS(10));
    i2c_write_reg(AW9523B_ADDR2, REG_OUTPUT_P0, 0x00);
    i2c_write_reg(AW9523B_ADDR2, REG_OUTPUT_P0+1, 0x00);
    i2c_write_reg(AW9523B_ADDR2, REG_WORK_MODE_P0, 0xFF); // P0 all GPIO
    i2c_write_reg(AW9523B_ADDR2, REG_WORK_MODE_P1, 0xF9); // P1 mostly GPIO, P1_1+P1_2 LED
    i2c_write_reg(AW9523B_ADDR2, REG_CTRL, 0x00);

    ESP_LOGI("AW9523B", "Init done (I2C_1, SCL=18, SDA=19)");
}

void aw_pinMode(aw_gpio_num_t pin, uint8_t mode) {
    if(pin < 8) {
        pinModeP0 = modifyBit(pinModeP0, pin, !mode);
        i2c_write_reg(AW9523B_ADDR2, REG_CONFIG_P0, pinModeP0);
    } else {
        pinModeP1 = modifyBit(pinModeP1, pin-8, !mode);
        i2c_write_reg(AW9523B_ADDR2, REG_CONFIG_P0+1, pinModeP1);
    }
}

void aw_digitalWrite(aw_gpio_num_t pin, uint8_t val) {
    if(pin < 8) {
        pinDataP0 = modifyBit(pinDataP0, pin, val);
        i2c_write_reg(AW9523B_ADDR2, REG_OUTPUT_P0, pinDataP0);
    } else {
        pinDataP1 = modifyBit(pinDataP1, pin-8, val);
        i2c_write_reg(AW9523B_ADDR2, REG_OUTPUT_P0+1, pinDataP1);
    }
}

int aw_digitalRead(aw_gpio_num_t pin) {
    uint8_t reg = (pin < 8) ? REG_INPUT_P0 : REG_INPUT_P0+1;
    uint8_t val = i2c_read_reg(AW9523B_ADDR2, reg);
    int bit = (pin < 8) ? pin : pin-8;
    return !((val >> bit) & 1);  // inverted: pressed = 1
}

uint8_t aw_read_reg(uint8_t addr, uint8_t reg) {
    return i2c_read_reg(addr, reg);
}

void led_set_rgb(int idx, uint8_t r, uint8_t g, uint8_t b) {
    i2c_write_reg(AW9523B_ADDR1, REG_DIM00 + idx*3, r);
    i2c_write_reg(AW9523B_ADDR1, REG_DIM00 + idx*3 + 1, g);
    i2c_write_reg(AW9523B_ADDR1, REG_DIM00 + idx*3 + 2, b);
}
