/**
 * cyberpi_firmware/main/aw9523b.h — GPIO expander driver
 */
#ifndef AW9523B_H
#define AW9523B_H
#include <stdint.h>
#include "driver/i2c.h"

#define AW9523B_ADDR1 0x5B  // LED driver
#define AW9523B_ADDR2 0x58  // GPIO expander

#define AW_GPIO_MODE_INPUT  0
#define AW_GPIO_MODE_OUTPUT 1

typedef enum {
    AW_P0_0=0x00, AW_P0_1=0x01, AW_P0_2=0x02, AW_P0_3=0x03,
    AW_P0_4=0x04, AW_P0_5=0x05, AW_P0_6=0x06, AW_P0_7=0x07,
    AW_P1_0=0x08, AW_P1_1=0x09, AW_P1_2=0x0a, AW_P1_3=0x0b,
    AW_P1_4=0x0c, AW_P1_5=0x0d, AW_P1_6=0x0e, AW_P1_7=0x0f,
} aw_gpio_num_t;

// Registers
#define REG_INPUT_P0   0x00
#define REG_OUTPUT_P0  0x02
#define REG_CONFIG_P0  0x04
#define REG_CTRL       0x11
#define REG_WORK_MODE_P0 0x12
#define REG_WORK_MODE_P1 0x13
#define REG_DIM00      0x20
#define REG_SWRST      0x7F

void aw9523b_init(void);
void aw_pinMode(aw_gpio_num_t pin, uint8_t mode);
void aw_digitalWrite(aw_gpio_num_t pin, uint8_t value);
int  aw_digitalRead(aw_gpio_num_t pin);
void led_set_rgb(int idx, uint8_t r, uint8_t g, uint8_t b);
uint8_t aw_read_reg(uint8_t addr, uint8_t reg);

#endif
