/**
 * cyberpi_firmware/main/main.c
 * =============================
 * 小芬 CyberPi ESP32 韌體
 *
 * 硬件: ST7735 LCD, I2S mic (ES8218E), I2S DAC speaker, AW9523B buttons/LED
 *
 * 編譯: idf.py set-target esp32 && idf.py build && idf.py flash
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "driver/gpio.h"
#include "driver/i2s.h"
#include "driver/spi_master.h"
#include "esp_websocket_client.h"
#include "cJSON.h"
#include "aw9523b.h"
#include "es8218e.h"
#include "font_chip.h"
#include "soc/io_mux_reg.h"
#include "rom/gpio.h"
static const char *TAG = "XIAOZHI";

/* ═══════════════════════════════════════
 * 設定
 * ═══════════════════════════════════════ */
#define WIFI_SSID      "SmarTone_HBB_3A74"
#define WIFI_PASS      "6J25GJ2GB5"
#define WS_URL         "ws://192.168.0.194:8000/ws"
#define DEVICE_ID      "cyberpi-esp32"

#define SAMPLE_RATE     16000
#define RECORD_SEC      2
#define WAV_BUF_SIZE    (SAMPLE_RATE * RECORD_SEC * 2)  // 64KB

static int16_t *wav_buf;
static bool wifi_ok = false;
static char wifi_ip[16] = {0};
static void ws_init(void);

/* ═══════════════════════════════════════
 * WiFi
 * ═══════════════════════════════════════ */
static void wifi_cb(void *a, esp_event_base_t b, int32_t c, void *d) {
    if (b == WIFI_EVENT && c == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (b == IP_EVENT && c == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *evt = (ip_event_got_ip_t *)d;
        snprintf(wifi_ip, sizeof(wifi_ip), IPSTR, IP2STR(&evt->ip_info.ip));
        wifi_ok = true;
        ESP_LOGI(TAG,"WiFi OK %s", wifi_ip);
        ws_init();
    } else if (b == WIFI_EVENT && c == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG,"WiFi disconnected, retrying...");
        esp_wifi_connect();
    }
}

static void wifi_init(void) {
    nvs_flash_init();
    esp_netif_init();
    esp_event_loop_create_default();
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t wc = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&wc);
    esp_event_handler_instance_t h;
    esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_cb, NULL, &h);
    esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_cb, NULL, &h);
    wifi_config_t cfg = {.sta={.ssid=WIFI_SSID,.password=WIFI_PASS}};
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(WIFI_IF_STA, &cfg);
    esp_wifi_start();
    // Don't block - let WiFi connect in background
}

/* ═══════════════════════════════════════
 * LCD (ST7735 128x128) — raw SPI, no LVGL
 * ═══════════════════════════════════════ */
static spi_device_handle_t lcd;

static void lcd_cmd(uint8_t c) {
    aw_digitalWrite(AW_P1_4, 0); // DC low
    spi_transaction_t t = {.length=8, .tx_buffer=&c};
    spi_device_transmit(lcd, &t);
}
static void lcd_data(uint8_t *d, int len) {
    aw_digitalWrite(AW_P1_4, 1); // DC high
    spi_transaction_t t = {.length=len*8, .tx_buffer=d};
    spi_device_transmit(lcd, &t);
}
static void lcd_data16(uint16_t color, int n) {
    aw_digitalWrite(AW_P1_4, 1);
    uint16_t buf[128];
    for(int i=0;i<128&&i<n;i++) buf[i]=color;
    while(n>0) {
        int s = (n>128)?128:n;
        spi_transaction_t t = {.length=s*16, .tx_buffer=buf};
        spi_device_transmit(lcd, &t);
        n-=s;
    }
}

static void lcd_write_cmd_data(uint8_t cmd, const uint8_t *data, int len) {
    lcd_cmd(cmd);
    if(len) lcd_data((uint8_t*)data, len);
}

static void lcd_init(void) {
    spi_bus_config_t bc = {.mosi_io_num=2,.miso_io_num=26,.sclk_io_num=4,.max_transfer_sz=128*128*2};
    spi_bus_initialize(SPI2_HOST, &bc, SPI_DMA_CH_AUTO);
    spi_device_interface_config_t dc = {
        .clock_speed_hz = 60 * 1000 * 1000,
        .mode = 0,
        .spics_io_num = 12,
        .queue_size = 7,
        .flags = SPI_DEVICE_HALFDUPLEX,
    };
    spi_bus_add_device(SPI2_HOST, &dc, &lcd);

    // ST7735 init from official CyberPi library
    lcd_cmd(0x01); vTaskDelay(pdMS_TO_TICKS(150)); // SWRESET
    lcd_cmd(0x11); vTaskDelay(pdMS_TO_TICKS(150)); // SLPOUT
    lcd_write_cmd_data(0xB1, (uint8_t[]){0x01,0x2C,0x2D}, 3); // FRMCTR1
    lcd_write_cmd_data(0xB2, (uint8_t[]){0x01,0x2C,0x2D}, 3); // FRMCTR2
    lcd_write_cmd_data(0xB3, (uint8_t[]){0x01,0x2C,0x2D,0x01,0x2C,0x2D}, 6); // FRMCTR3
    lcd_write_cmd_data(0xB4, (uint8_t[]){0x07}, 1); // INVCTR
    lcd_write_cmd_data(0xC0, (uint8_t[]){0xA2,0x02,0x84}, 3); // PWCTR1
    lcd_write_cmd_data(0xC1, (uint8_t[]){0xC5}, 1); // PWCTR2
    lcd_write_cmd_data(0xC2, (uint8_t[]){0x0A,0x00}, 2); // PWCTR3
    lcd_write_cmd_data(0xC3, (uint8_t[]){0x8A,0x2A}, 2); // PWCTR4
    lcd_write_cmd_data(0xC4, (uint8_t[]){0x8A,0xEE}, 2); // PWCTR5
    lcd_write_cmd_data(0xC5, (uint8_t[]){0x0E}, 1); // VMCTR1
    lcd_cmd(0x20); // INVOFF
    lcd_write_cmd_data(0x36, (uint8_t[]){0xA8}, 1); // MADCTL
    lcd_write_cmd_data(0x3A, (uint8_t[]){0x05}, 1); // COLMOD RGB565
    lcd_write_cmd_data(0x2A, (uint8_t[]){0x00,0x02,0x00,0x81}, 4); // CASET 2-129
    lcd_write_cmd_data(0x2B, (uint8_t[]){0x00,0x01,0x00,0xA0}, 4); // RASET 1-160
    lcd_write_cmd_data(0xE0, (uint8_t[]){0x02,0x1c,0x07,0x12,0x37,0x32,0x29,0x2d,0x29,0x25,0x2B,0x39,0x00,0x01,0x03,0x10}, 16);
    lcd_write_cmd_data(0xE1, (uint8_t[]){0x03,0x1d,0x07,0x06,0x2E,0x2C,0x29,0x2D,0x2E,0x2E,0x37,0x3F,0x00,0x00,0x02,0x10}, 16);
    lcd_cmd(0x13); vTaskDelay(pdMS_TO_TICKS(10)); // NORON
    lcd_cmd(0x29); vTaskDelay(pdMS_TO_TICKS(10)); // DISPON
    ESP_LOGI(TAG,"LCD ready");
}

#define LCD_XSTART 2
#define LCD_YSTART 1

static void lcd_fill(uint16_t color) {
    // Fill entire 132x162 native area to clear all memory
    lcd_cmd(0x2A); uint8_t ca[]={0,0x00,0x00,0x84}; lcd_data(ca,4); // 132 cols
    lcd_cmd(0x2B); uint8_t ra[]={0,0x00,0x00,0xA2}; lcd_data(ra,4); // 162 rows
    lcd_cmd(0x2C);
    lcd_data16(color, 132*162);
    // Set visible 128x128 window
    lcd_cmd(0x2A); uint8_t cva[]={0,LCD_XSTART,0,LCD_XSTART+127}; lcd_data(cva,4);
    lcd_cmd(0x2B); uint8_t rva[]={0,LCD_YSTART,0,LCD_YSTART+127}; lcd_data(rva,4);
}

/* ═══════════════════════════════════════
 * 5x7 ASCII font (96 chars, 0x20-0x7F)
 * ═══════════════════════════════════════ */
static const uint8_t font5x7[96][5] = {
    {0x00,0x00,0x00,0x00,0x00}, // space
    {0x00,0x00,0x5F,0x00,0x00}, // !
    {0x00,0x07,0x00,0x07,0x00}, // "
    {0x14,0x7F,0x14,0x7F,0x14}, // #
    {0x24,0x2A,0x7F,0x2A,0x12}, // $
    {0x23,0x13,0x08,0x64,0x62}, // %
    {0x36,0x49,0x55,0x22,0x50}, // &
    {0x00,0x05,0x03,0x00,0x00}, // '
    {0x00,0x1C,0x22,0x41,0x00}, // (
    {0x00,0x41,0x22,0x1C,0x00}, // )
    {0x08,0x2A,0x1C,0x2A,0x08}, // *
    {0x08,0x08,0x3E,0x08,0x08}, // +
    {0x00,0x50,0x30,0x00,0x00}, // ,
    {0x08,0x08,0x08,0x08,0x08}, // -
    {0x00,0x60,0x60,0x00,0x00}, // .
    {0x20,0x10,0x08,0x04,0x02}, // /
    {0x3E,0x51,0x49,0x45,0x3E}, // 0
    {0x00,0x42,0x7F,0x40,0x00}, // 1
    {0x42,0x61,0x51,0x49,0x46}, // 2
    {0x21,0x41,0x45,0x4B,0x31}, // 3
    {0x18,0x14,0x12,0x7F,0x10}, // 4
    {0x27,0x45,0x45,0x45,0x39}, // 5
    {0x3C,0x4A,0x49,0x49,0x30}, // 6
    {0x01,0x71,0x09,0x05,0x03}, // 7
    {0x36,0x49,0x49,0x49,0x36}, // 8
    {0x06,0x49,0x49,0x29,0x1E}, // 9
    {0x00,0x36,0x36,0x00,0x00}, // :
    {0x00,0x56,0x36,0x00,0x00}, // ;
    {0x00,0x08,0x14,0x22,0x41}, // <
    {0x14,0x14,0x14,0x14,0x14}, // =
    {0x41,0x22,0x14,0x08,0x00}, // >
    {0x02,0x01,0x51,0x09,0x06}, // ?
    {0x32,0x49,0x79,0x41,0x3E}, // @
    {0x7E,0x11,0x11,0x11,0x7E}, // A
    {0x7F,0x49,0x49,0x49,0x36}, // B
    {0x3E,0x41,0x41,0x41,0x22}, // C
    {0x7F,0x41,0x41,0x22,0x1C}, // D
    {0x7F,0x49,0x49,0x49,0x41}, // E
    {0x7F,0x09,0x09,0x01,0x01}, // F
    {0x3E,0x41,0x41,0x51,0x32}, // G
    {0x7F,0x08,0x08,0x08,0x7F}, // H
    {0x00,0x41,0x7F,0x41,0x00}, // I
    {0x20,0x40,0x41,0x3F,0x01}, // J
    {0x7F,0x08,0x14,0x22,0x41}, // K
    {0x7F,0x40,0x40,0x40,0x40}, // L
    {0x7F,0x02,0x04,0x02,0x7F}, // M
    {0x7F,0x04,0x08,0x10,0x7F}, // N
    {0x3E,0x41,0x41,0x41,0x3E}, // O
    {0x7F,0x09,0x09,0x09,0x06}, // P
    {0x3E,0x41,0x51,0x21,0x5E}, // Q
    {0x7F,0x09,0x19,0x29,0x46}, // R
    {0x46,0x49,0x49,0x49,0x31}, // S
    {0x01,0x01,0x7F,0x01,0x01}, // T
    {0x3F,0x40,0x40,0x40,0x3F}, // U
    {0x1F,0x20,0x40,0x20,0x1F}, // V
    {0x7F,0x20,0x18,0x20,0x7F}, // W
    {0x63,0x14,0x08,0x14,0x63}, // X
    {0x03,0x04,0x78,0x04,0x03}, // Y
    {0x61,0x51,0x49,0x45,0x43}, // Z
    {0x00,0x7F,0x41,0x41,0x00}, // [
    {0x02,0x04,0x08,0x10,0x20}, // backslash
    {0x00,0x41,0x41,0x7F,0x00}, // ]
    {0x04,0x02,0x01,0x02,0x04}, // ^
    {0x40,0x40,0x40,0x40,0x40}, // _
    {0x00,0x01,0x02,0x04,0x00}, // `
    {0x20,0x54,0x54,0x54,0x78}, // a
    {0x7F,0x48,0x44,0x44,0x38}, // b
    {0x38,0x44,0x44,0x44,0x20}, // c
    {0x38,0x44,0x44,0x48,0x7F}, // d
    {0x38,0x54,0x54,0x54,0x18}, // e
    {0x08,0x7E,0x09,0x01,0x02}, // f
    {0x08,0x14,0x54,0x54,0x3C}, // g
    {0x7F,0x08,0x04,0x04,0x78}, // h
    {0x00,0x44,0x7D,0x40,0x00}, // i
    {0x20,0x40,0x44,0x3D,0x00}, // j
    {0x7F,0x10,0x28,0x44,0x00}, // k
    {0x00,0x41,0x7F,0x40,0x00}, // l
    {0x7C,0x04,0x18,0x04,0x78}, // m
    {0x7C,0x08,0x04,0x04,0x78}, // n
    {0x38,0x44,0x44,0x44,0x38}, // o
    {0x7C,0x14,0x14,0x14,0x08}, // p
    {0x08,0x14,0x14,0x18,0x7C}, // q
    {0x7C,0x08,0x04,0x04,0x08}, // r
    {0x48,0x54,0x54,0x54,0x20}, // s
    {0x04,0x3F,0x44,0x40,0x20}, // t
    {0x3C,0x40,0x40,0x20,0x7C}, // u
    {0x1C,0x20,0x40,0x20,0x1C}, // v
    {0x3C,0x40,0x30,0x40,0x3C}, // w
    {0x44,0x28,0x10,0x28,0x44}, // x
    {0x0C,0x50,0x50,0x50,0x3C}, // y
    {0x44,0x64,0x54,0x4C,0x44}, // z
    {0x00,0x08,0x36,0x41,0x00}, // {
    {0x00,0x00,0x7F,0x00,0x00}, // |
    {0x00,0x41,0x36,0x08,0x00}, // }
    {0x08,0x04,0x08,0x10,0x08}, // ~
};

#define CHAR_W  6  // 5px glyph + 1px gap
#define CHAR_H  8  // 7px glyph + 1px gap

static void lcd_set_window(int x, int y, int w, int h) {
    lcd_cmd(0x2A);
    uint8_t ca[] = {0, LCD_XSTART + x, 0, LCD_XSTART + x + w - 1};
    lcd_data(ca, 4);
    lcd_cmd(0x2B);
    uint8_t ra[] = {0, LCD_YSTART + y, 0, LCD_YSTART + y + h - 1};
    lcd_data(ra, 4);
    lcd_cmd(0x2C);
}

static void lcd_draw_char(char c, int x, int y, uint16_t color, uint16_t bg) {
    if (c < 32 || c > 127) return;
    const uint8_t *glyph = font5x7[c - 32];
    uint16_t buf[5 * 7];
    int idx = 0;
    for (int row = 0; row < 7; row++) {
        for (int col = 0; col < 5; col++) {
            buf[idx++] = (glyph[col] & (1 << row)) ? color : bg;
        }
    }
    lcd_set_window(x, y, 5, 7);
    aw_digitalWrite(AW_P1_4, 1);
    spi_transaction_t t = {.length = 5 * 7 * 16, .tx_buffer = buf};
    spi_device_transmit(lcd, &t);
}

static void lcd_draw_bitmap16(const uint8_t *bitmap, int x, int y, uint16_t color, uint16_t bg) {
    // GT30L24A3W 16x16 font: 32 bytes
    // Try multiple layouts to handle both GB2312 and BIG5
    uint16_t buf[16 * 16];
    int idx = 0;
    for (int row = 0; row < 16; row++) {
        uint8_t b0 = bitmap[row * 2];
        uint8_t b1 = bitmap[row * 2 + 1];
        // Layout 1: MSB=left (standard for GB2312)
        for (int col = 0; col < 8; col++) {
            buf[idx++] = (b0 & (0x80 >> col)) ? color : bg;
        }
        for (int col = 0; col < 8; col++) {
            buf[idx++] = (b1 & (0x80 >> col)) ? color : bg;
        }
    }
    lcd_set_window(x, y, 16, 16);
    aw_digitalWrite(AW_P1_4, 1);
    spi_transaction_t t = {.length = 16 * 16 * 16, .tx_buffer = buf};
    spi_device_transmit(lcd, &t);
}

static void lcd_draw_bitmap24(const uint8_t *bitmap, int x, int y, uint16_t color, uint16_t bg) {
    // 24x24 font: 72 bytes, row-major, 3 bytes per row (24 bits)
    static uint16_t buf[24 * 24]; // static to avoid stack overflow
    int idx = 0;
    for (int row = 0; row < 24; row++) {
        uint8_t b0 = bitmap[row * 3];
        uint8_t b1 = bitmap[row * 3 + 1];
        uint8_t b2 = bitmap[row * 3 + 2];
        for (int col = 0; col < 8; col++)
            buf[idx++] = (b0 & (0x80 >> col)) ? color : bg;
        for (int col = 0; col < 8; col++)
            buf[idx++] = (b1 & (0x80 >> col)) ? color : bg;
        for (int col = 0; col < 8; col++)
            buf[idx++] = (b2 & (0x80 >> col)) ? color : bg;
    }
    lcd_set_window(x, y, 24, 24);
    aw_digitalWrite(AW_P1_4, 1);
    spi_transaction_t t = {.length = 24 * 24 * 16, .tx_buffer = buf};
    spi_device_transmit(lcd, &t);
}

static void lcd_draw_text(const char *str, int x, int y, uint16_t color, uint16_t bg) {
    int cx = x, cy = y;
    for (int i = 0; str[i]; ) {
        if (str[i] == '\n') {
            cx = x; cy += CHAR_H;
            if (cy + CHAR_H > 128) return;
            i++; continue;
        }
        uint8_t c = (uint8_t)str[i];
        if (c < 0x80) {
            // ASCII
            if (cx + CHAR_W > 128) { cx = x; cy += CHAR_H; if (cy + CHAR_H > 128) return; }
            if (c >= 32) lcd_draw_char(c, cx, cy, color, bg);
            cx += CHAR_W;
            i++;
        } else if ((c & 0xE0) == 0xC0) {
            i += 2; // skip 2-byte UTF-8
        } else if ((c & 0xF0) == 0xE0 && str[i+1] && str[i+2]) {
            // 3-byte UTF-8 → decode to Unicode, get bitmap from font chip
            uint16_t unicode = ((c & 0x0F) << 12) | (((uint8_t)str[i+1] & 0x3F) << 6) | ((uint8_t)str[i+2] & 0x3F);
            if (cx + 16 > 128) { cx = x; cy += 18; if (cy + 18 > 128) return; }
            // Try 16x16 first, fall back to 24x24
            uint8_t bitmap[72];
            if (font_chip_get_16x16(unicode, bitmap) == 0) {
                lcd_draw_bitmap16(bitmap, cx, cy, color, bg);
                cx += 16;
            } else if (font_chip_get_24x24(unicode, bitmap) == 0) {
                if (cx + 24 > 128) { cx = x; cy += 26; if (cy + 26 > 128) { i += 3; continue; } }
                lcd_draw_bitmap24(bitmap, cx, cy, color, bg);
                cx += 24;
            } else {
                cx += 16; // skip char, leave space
            }
            i += 3;
        } else {
            i++; // skip unknown
        }
    }
}

static void show_home(void) {
    lcd_fill(0x0000);
    lcd_draw_text("小芬v0.52", 2, 10, 0xFFFF, 0x0000);
    lcd_draw_text("A=錄/播 B=發送", 2, 112, 0x07E0, 0x0000);
}

/* ═══════════════════════════════════════
 * Mic I2S Recording
 * ═══════════════════════════════════════ */
static void mic_init(void) {
    i2s_config_t c = {.mode=I2S_MODE_MASTER|I2S_MODE_RX,.sample_rate=SAMPLE_RATE,
                      .bits_per_sample=I2S_BITS_PER_SAMPLE_16BIT,.channel_format=I2S_CHANNEL_FMT_ONLY_RIGHT,
                      .communication_format=I2S_COMM_FORMAT_STAND_I2S,
                      .intr_alloc_flags=ESP_INTR_FLAG_LEVEL1,
                      .dma_buf_count=4,.dma_buf_len=256,.use_apll=false};
    i2s_driver_install(I2S_NUM_1, &c, 0, NULL);
    i2s_pin_config_t p = {.bck_io_num=13,.ws_io_num=14,.data_out_num=-1,.data_in_num=35};
    i2s_set_pin(I2S_NUM_1, &p);
    // GPIO0 = MCLK for ES8218E codec
    PIN_FUNC_SELECT(PERIPHS_IO_MUX_GPIO0_U, FUNC_GPIO0_CLK_OUT1);
    wav_buf = malloc(WAV_BUF_SIZE);
    if(!wav_buf) ESP_LOGE(TAG,"FATAL: malloc WAV buffer failed!");
    else ESP_LOGI(TAG,"Mic ready (buffer %d bytes)", WAV_BUF_SIZE);
}

/* Simple speaker playback via I2S0 internal DAC */
static bool speaker_ok = false;
static void speaker_init(void) {
    // Exact match with official CyberPi Arduino library
    i2s_config_t c = {
        .mode = I2S_MODE_MASTER | I2S_MODE_TX | I2S_MODE_DAC_BUILT_IN,
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT,
        .communication_format = I2S_COMM_FORMAT_STAND_MSB,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 4,
        .dma_buf_len = 256,
        .use_apll = true,
    };
    esp_err_t r = i2s_driver_install(I2S_NUM_0, &c, 0, NULL);
    if (r != ESP_OK) { ESP_LOGE(TAG,"Speaker I2S failed"); return; }
    i2s_set_dac_mode(I2S_DAC_CHANNEL_RIGHT_EN);
    aw_digitalWrite(AW_P1_3, 1);
    speaker_ok = true;
    ESP_LOGI(TAG,"Speaker ready");
}

static void speaker_play(const int16_t *data, size_t samples) {
    if (!speaker_ok || !data) return;
    // Write stereo: each sample duplicated for L+R, sign bit flipped for DAC
    int16_t buf[256]; // 128 stereo pairs
    size_t offset = 0;
    while(offset < samples) {
        size_t n = samples - offset;
        if(n > 128) n = 128;
        for(size_t i = 0; i < n; i++) {
            int16_t v = (int16_t)((uint16_t)data[offset+i] ^ 0x8000);
            buf[i*2] = v;     // left
            buf[i*2+1] = v;   // right
        }
        size_t written;
        i2s_write(I2S_NUM_0, buf, n * 4, &written, portMAX_DELAY); // n*2 samples * 2 bytes
        offset += n;
    }
}

static void speaker_stop(void) {
    if (!speaker_ok) return;
    i2s_zero_dma_buffer(I2S_NUM_0);
}

static void speaker_deinit(void) {
    if (!speaker_ok) return;
    i2s_driver_uninstall(I2S_NUM_0);
    speaker_ok = false;
    // Restore GPIO26 to SPI MISO for font chip
    gpio_set_direction(26, GPIO_MODE_INPUT);
    gpio_set_pull_mode(26, GPIO_FLOATING);
    ESP_LOGI(TAG,"Speaker off, GPIO26 restored");
}

/* ═══════════════════════════════════════
 * WebSocket Client (xiaozhi-esp32 protocol)
 * ═══════════════════════════════════════ */
static esp_websocket_client_handle_t ws_client;
static char ws_stt_text[512] = {0};
static char ws_llm_text[512] = {0};
static bool ws_stt_done = false;
static bool ws_llm_done = false;
static bool ws_connected = false;

static void ws_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data) {
    esp_websocket_event_data_t *evt = (esp_websocket_event_data_t *)data;
    switch (id) {
    case WEBSOCKET_EVENT_CONNECTED:
        ESP_LOGI(TAG, "WS connected");
        ws_connected = true;
        // Send hello
        cJSON *hello = cJSON_CreateObject();
        cJSON_AddStringToObject(hello, "type", "hello");
        cJSON_AddNumberToObject(hello, "version", 3);
        cJSON_AddStringToObject(hello, "transport", "websocket");
        cJSON *ap = cJSON_CreateObject();
        cJSON_AddStringToObject(ap, "format", "pcm");
        cJSON_AddNumberToObject(ap, "sample_rate", 16000);
        cJSON_AddNumberToObject(ap, "channels", 1);
        cJSON_AddNumberToObject(ap, "frame_duration", 60);
        cJSON_AddItemToObject(hello, "audio_params", ap);
        char *s = cJSON_PrintUnformatted(hello);
        esp_websocket_client_send_text(ws_client, s, strlen(s), portMAX_DELAY);
        free(s); cJSON_Delete(hello);
        break;
    case WEBSOCKET_EVENT_DISCONNECTED:
        ESP_LOGI(TAG, "WS disconnected");
        ws_connected = false;
        break;
    case WEBSOCKET_EVENT_DATA:
        if (evt->op_code == 0x01 || evt->op_code == 0x02) { // text or binary
            if (evt->data_len < 8) break;
            char *json_str = strndup((char*)evt->data_ptr, evt->data_len);
            cJSON *msg = cJSON_Parse(json_str);
            if (msg) {
                cJSON *type = cJSON_GetObjectItem(msg, "type");
                if (type && type->valuestring) {
                    if (strcmp(type->valuestring, "stt") == 0) {
                        cJSON *t = cJSON_GetObjectItem(msg, "text");
                        if (t && t->valuestring) {
                            strncpy(ws_stt_text, t->valuestring, sizeof(ws_stt_text)-1);
                            ws_stt_done = true;
                            ESP_LOGI(TAG, "STT: %s", ws_stt_text);
                        }
                    } else if (strcmp(type->valuestring, "llm") == 0) {
                        cJSON *t = cJSON_GetObjectItem(msg, "text");
                        if (t && t->valuestring) {
                            strncpy(ws_llm_text, t->valuestring, sizeof(ws_llm_text)-1);
                            ws_llm_done = true;
                            ESP_LOGI(TAG, "LLM: %s", ws_llm_text);
                        }
                    }
                }
                cJSON_Delete(msg);
            }
            free(json_str);
        }
        break;
    }
}

static void ws_init(void) {
    esp_websocket_client_config_t cfg = {
        .uri = WS_URL,
        .skip_cert_common_name_check = true,
        .reconnect_timeout_ms = 10000,
        .network_timeout_ms = 10000,
    };
    ws_client = esp_websocket_client_init(&cfg);
    esp_websocket_register_events(ws_client, WEBSOCKET_EVENT_ANY, ws_event_handler, NULL);
    esp_websocket_client_start(ws_client);
}

static bool ws_send_audio_and_wait(size_t wav_sz, char *text_out, int max) {
    if (!ws_connected) { ESP_LOGE(TAG,"WS not connected"); return false; }
    ESP_LOGE(TAG,"WS send audio: %d bytes", (int)wav_sz);

    ws_stt_done = false; ws_stt_text[0] = 0;
    ws_llm_done = false; ws_llm_text[0] = 0;

    // Send listen start
    cJSON *start = cJSON_CreateObject();
    cJSON_AddStringToObject(start, "type", "listen");
    cJSON_AddStringToObject(start, "state", "start");
    cJSON_AddStringToObject(start, "mode", "manual");
    char *s = cJSON_PrintUnformatted(start);
    esp_websocket_client_send_text(ws_client, s, strlen(s), portMAX_DELAY);
    free(s); cJSON_Delete(start);
    vTaskDelay(pdMS_TO_TICKS(50));

    // Send PCM audio as binary frames (1024 bytes each)
    uint8_t *audio = (uint8_t*)wav_buf;
    size_t offset = 0;
    while(offset < wav_sz) {
        size_t n = wav_sz - offset;
        if(n > 1024) n = 1024;
        esp_websocket_client_send_bin(ws_client, (char*)(audio + offset), n, portMAX_DELAY);
        offset += n;
        vTaskDelay(pdMS_TO_TICKS(10));
    }

    // Send listen stop
    cJSON *stop = cJSON_CreateObject();
    cJSON_AddStringToObject(stop, "type", "listen");
    cJSON_AddStringToObject(stop, "state", "stop");
    cJSON_AddStringToObject(stop, "mode", "manual");
    s = cJSON_PrintUnformatted(stop);
    esp_websocket_client_send_text(ws_client, s, strlen(s), portMAX_DELAY);
    free(s); cJSON_Delete(stop);

    // Wait for STT response
    int timeout = 0;
    while(!ws_stt_done && timeout < 150) { vTaskDelay(pdMS_TO_TICKS(100)); timeout++; }
    if(ws_stt_done && ws_stt_text[0]) {
        strncpy(text_out, ws_stt_text, max - 1);
        return true;
    }
    return false;
}

/* ═══════════════════════════════════════
 * Main
 * ═══════════════════════════════════════ */
void app_main(void) {
    ESP_LOGI(TAG,"Starting...");

    // 1. AW9523B (buttons, LCD controls, LEDs)
    aw9523b_init();

    // LCD DC/RST/BL via AW9523B
    aw_pinMode(AW_P1_4, AW_GPIO_MODE_OUTPUT); // DC
    aw_pinMode(AW_P1_5, AW_GPIO_MODE_OUTPUT); // RST
    aw_pinMode(AW_P1_7, AW_GPIO_MODE_OUTPUT); // BL
    aw_pinMode(AW_P1_3, AW_GPIO_MODE_OUTPUT); // Speaker EN

    // LCD RST sequence: low pulse then high
    aw_digitalWrite(AW_P1_5, 0); // RST low
    vTaskDelay(pdMS_TO_TICKS(120));
    aw_digitalWrite(AW_P1_5, 1); // RST high
    vTaskDelay(pdMS_TO_TICKS(120));
    aw_digitalWrite(AW_P1_7, 1); // BL on
    aw_digitalWrite(AW_P1_3, 1); // Speaker on

    // LEDs: all 4 blue
    led_set_rgb(0, 0, 0, 128);
    led_set_rgb(1, 0, 0, 128);
    led_set_rgb(2, 0, 0, 128);
    led_set_rgb(3, 0, 0, 128);

    // 3. LCD
    lcd_init();
    font_chip_init();

    // Buttons (input)
    aw_pinMode(AW_P0_6, AW_GPIO_MODE_INPUT); // A
    aw_pinMode(AW_P0_5, AW_GPIO_MODE_INPUT); // B
    aw_pinMode(AW_P0_3, AW_GPIO_MODE_INPUT); // Joystick center

    // 4. WiFi — show status on LCD while connecting
    ESP_LOGI(TAG,"WiFi...");
    lcd_fill(0x0000);
    lcd_draw_text("WiFi連接中...", 2, 40, 0xFFFF, 0x0000);
    wifi_init();

    // Wait for WiFi with status
    while (!wifi_ok) {
        vTaskDelay(pdMS_TO_TICKS(200));
    }

    // Show IP for 3 seconds
    lcd_fill(0x0000);
    lcd_draw_text("WiFi已連接", 2, 30, 0x07E0, 0x0000);
    lcd_draw_text(wifi_ip, 2, 50, 0xFFFF, 0x0000);
    vTaskDelay(pdMS_TO_TICKS(3000));

    // Home screen
    show_home();

    // 5. Scan I2C bus for devices
    ESP_LOGI(TAG,"I2C scan on I2C_NUM_1:");
    for(uint8_t addr=1; addr<127; addr++) {
        i2c_cmd_handle_t cmd = i2c_cmd_link_create();
        i2c_master_start(cmd);
        i2c_master_write_byte(cmd, (addr<<1)|0, true);
        i2c_master_stop(cmd);
        if(i2c_master_cmd_begin(I2C_NUM_1, cmd, pdMS_TO_TICKS(20)) == ESP_OK)
            ESP_LOGI(TAG,"  I2C dev: 0x%02X", addr);
        i2c_cmd_link_delete(cmd);
    }

    // 6. Mic: start I2S to generate MCLK, then init codec
    mic_init();      // I2S driver + pins + GPIO0 MCLK routing
    i2s_start(I2S_NUM_1);  // Start I2S to generate MCLK for codec
    vTaskDelay(pdMS_TO_TICKS(100)); // let clocks stabilize
    es8218e_init();  // Codec init while MCLK is active
    vTaskDelay(pdMS_TO_TICKS(100)); // let codec settle
    i2s_zero_dma_buffer(I2S_NUM_1); // flush stale data
    i2s_stop(I2S_NUM_1);
    // speaker_init() called on-demand for playback

    // 6. Ready
    led_set_rgb(0,0,255,0);
    ESP_LOGI(TAG,"=== READY === A=hold record, B=send");
    size_t rec_len = 0;

    while(1) {
        // A: press-hold record, release to stop
        int a_state = aw_digitalRead(AW_P0_6);
        if(a_state) {
            if(!wav_buf) {
                lcd_fill(0x0000); lcd_draw_text("記憶體不足", 2, 10, 0xF800, 0x0000);
                vTaskDelay(2000);
            } else {
                lcd_fill(0x0000);
                lcd_draw_text("錄音中...", 2, 10, 0xFFFF, 0x0000);
                led_set_rgb(0,255,0,255);
                int64_t t0 = esp_timer_get_time();
                rec_len = 0;
                i2s_start(I2S_NUM_1);
                i2s_zero_dma_buffer(I2S_NUM_1); // clear stale data
                vTaskDelay(pdMS_TO_TICKS(50));  // let ES8218E lock to MCLK
                while(aw_digitalRead(AW_P0_6) && rec_len < WAV_BUF_SIZE) {
                    size_t r;
                    i2s_read(I2S_NUM_1, (uint8_t*)wav_buf+rec_len, WAV_BUF_SIZE-rec_len, &r, pdMS_TO_TICKS(100));
                    rec_len += r;
                }
                i2s_stop(I2S_NUM_1);
                int64_t t1 = esp_timer_get_time();
                int rec_ms = (int)((t1 - t0) / 1000);
                int wav_ms = (int)(rec_len / 32);
                led_set_rgb(0,0,255,0);
                // Auto-playback after recording
                if(rec_len > 8000) {
                    lcd_fill(0x0000);
                    lcd_draw_text("播放中...", 2, 10, 0xFFFF, 0x0000);
                    speaker_init();
                    speaker_play(wav_buf, rec_len/2);
                    speaker_stop();
                    speaker_deinit();
                }
                lcd_fill(0x0000);
                if(rec_len > 8000) {
                    lcd_draw_text("B=發送 A=重錄", 2, 40, 0xFFFF, 0x0000);
                } else {
                    lcd_draw_text("太短 A=重錄", 2, 40, 0xF800, 0x0000);
                }
                lcd_draw_text("A=錄/播 B=發送", 2, 112, 0x07E0, 0x0000);
                ESP_LOGI(TAG,"Rec: %d bytes %dms", rec_len, wav_ms);
            }
        }
        // B: send to server
        if(aw_digitalRead(AW_P0_5)) {
            if(!wifi_ok || !ws_connected) {
                lcd_fill(0x0000);
                lcd_draw_text("WiFi未連接", 2, 10, 0xF800, 0x0000);
                vTaskDelay(pdMS_TO_TICKS(2000));
                lcd_fill(0x0000);
                lcd_draw_text("小芬v0.52", 2, 10, 0xFFFF, 0x0000);
                lcd_draw_text("A=錄/播 B=發送", 2, 112, 0x07E0, 0x0000);
                vTaskDelay(pdMS_TO_TICKS(500));
                continue;
            }
            if(rec_len == 0) {
                // No recording: send text hello
                led_set_rgb(0,255,255,0);
                lcd_fill(0x0000);
                lcd_draw_text("發送中...", 2, 10, 0xFFFF, 0x0000);
                cJSON *msg = cJSON_CreateObject();
                cJSON_AddStringToObject(msg, "type", "listen");
                cJSON_AddStringToObject(msg, "state", "detect");
                cJSON_AddStringToObject(msg, "text", "你好請用廣東話回答");
                char *s = cJSON_PrintUnformatted(msg);
                esp_websocket_client_send_text(ws_client, s, strlen(s), portMAX_DELAY);
                free(s); cJSON_Delete(msg);
                ws_llm_done = false; ws_llm_text[0] = 0;
                int to = 0;
                while (!ws_llm_done && to < 120) { vTaskDelay(pdMS_TO_TICKS(100)); to++; }
                if (ws_llm_done && ws_llm_text[0]) {
                    lcd_fill(0x0000);
                    lcd_draw_text("小芬:", 0, 0, 0x07E0, 0x0000);
                    lcd_draw_text(ws_llm_text, 0, 18, 0xFFFF, 0x0000);
                }
                vTaskDelay(pdMS_TO_TICKS(4000));
            } else {
                // Send recorded WAV to ASR server
                led_set_rgb(0,255,255,0);
                lcd_fill(0x0000);
                lcd_draw_text("發送中...", 2, 10, 0xFFFF, 0x0000);
                ESP_LOGE(TAG,"BTN_B: ws send %d bytes", rec_len);
                char asr_text[256] = {0};
                bool ok = ws_send_audio_and_wait(rec_len, asr_text, sizeof(asr_text));
                rec_len = 0;
                ESP_LOGE(TAG,"BTN_B: ok=%d text=%s", ok, asr_text);
                if (ok && asr_text[0]) {
                    led_set_rgb(0,0,255,0);
                    lcd_fill(0x0000);
                    lcd_draw_text("你說:", 0, 0, 0x07E0, 0x0000);
                    lcd_draw_text(asr_text, 0, 18, 0xFFFF, 0x0000);
                    vTaskDelay(pdMS_TO_TICKS(3000));
                } else {
                    led_set_rgb(0,255,0,0);
                    lcd_fill(0x0000);
                    lcd_draw_text("無回應", 2, 10, 0xF800, 0x0000);
                    vTaskDelay(pdMS_TO_TICKS(2000));
                }
            }
            led_set_rgb(0,0,255,0);
            show_home();
        }
        // Joystick center: play back recording
        if(aw_digitalRead(AW_P0_3) && rec_len > 0) {
            led_set_rgb(0,128,128,0);
            lcd_fill(0x0000);
            lcd_draw_text("播放中...", 2, 10, 0xFFFF, 0x0000);
            speaker_init();
            speaker_play(wav_buf, rec_len/2);
            speaker_stop();
            speaker_deinit();
            led_set_rgb(0,0,255,0);
            show_home();
            vTaskDelay(pdMS_TO_TICKS(500));
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}
