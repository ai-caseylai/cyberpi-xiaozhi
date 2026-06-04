/**
 * 小芳智能體 FunConnect AIOT 平台
 * CyberPi ESP32 韌體 — Opus 語音 + xiaozhi-esp32 協議 v3
 *
 * 硬件: ST7735 LCD, I2S ES8218E mic, I2S DAC speaker, AW9523B GPIO/LED
 * 通訊: WSS (Cloudflare Worker) + MQTT (EMQX.io)
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include "esp_mac.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
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
#include "opus_codec.h"
#include "xiaozhi_protocol.h"
#include "audio_pipeline.h"
#include "fmqtt_client.h"
#include "efont_supp.h"
static const char *TAG = "FunConnect";

/* ═══════════════════════════════════════
 * 設定
 * ═══════════════════════════════════════ */
#define WIFI_SSID      "SmarTone_HBB_3A74"
#define WIFI_PASS      "6J25GJ2GB5"
#define WS_URL         "wss://funconnect-backend.ai-caseylai.workers.dev/xiaozhi/v1/"
#define XZ_TOKEN       "funconnect-token"
#define DEVICE_ID      "cyberpi-esp32"
#define MQTT_BROKER    "mqtt://broker.emqx.io:1883"

#define SAMPLE_RATE     16000
#define RECORD_SEC      120                              // 2 分鐘錄音（用盡 PSRAM）
#define WAV_BUF_SIZE    (SAMPLE_RATE * RECORD_SEC * 2)  // 3.84MB PSRAM

/* ═══════════════════════════════════════
 * 狀態機
 * ═══════════════════════════════════════ */
typedef enum {
    STATE_IDLE,
    STATE_LISTENING,
    STATE_UPLOADING,
    STATE_WAITING_STT,
    STATE_WAITING_LLM,
    STATE_WAITING_TTS,
    STATE_PLAYING,
    STATE_ERROR,
} system_state_t;

static system_state_t state = STATE_IDLE;

/* ═══════════════════════════════════════
 * 全局變數
 * ═══════════════════════════════════════ */
static int16_t *wav_buf;
static bool wifi_ok = false;
static char wifi_ip[16] = {0};

/* WebSocket */
static esp_websocket_client_handle_t ws_client;
static bool ws_connected = false;
static bool ws_hello_done = false;
static char ws_stt_text[XZ_TEXT_MAX] = {0};
static char ws_llm_text[XZ_TEXT_MAX] = {0};
static char ws_llm_emotion[XZ_EMOTION_MAX] = {0};
static bool ws_stt_done = false;
static bool ws_llm_done = false;
static bool ws_tts_active = false;
static bool ws_tts_done = false;
static char xz_session_id[XZ_SESSION_ID_MAX] = {0};
static int  xz_downlink_rate = 24000;

/* Recording */
static size_t rec_len = 0;

static void ws_init(void);
static void ws_send_json(const char *json_str);

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
        wifi_ok = false;
        ws_connected = false;
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
}

/* ═══════════════════════════════════════
 * LCD (ST7735 128x128) — raw SPI
 * ═══════════════════════════════════════ */
static spi_device_handle_t lcd;

static void lcd_cmd(uint8_t c) {
    aw_digitalWrite(AW_P1_4, 0);
    spi_transaction_t t = {.length=8, .tx_buffer=&c};
    spi_device_transmit(lcd, &t);
}
static void lcd_data(uint8_t *d, int len) {
    aw_digitalWrite(AW_P1_4, 1);
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

static void lcd_init(void) {
    spi_bus_config_t bc = {.mosi_io_num=2,.miso_io_num=26,.sclk_io_num=4,.max_transfer_sz=128*128*2};
    spi_bus_initialize(SPI2_HOST, &bc, SPI_DMA_CH_AUTO);
    spi_device_interface_config_t dc = {
        .clock_speed_hz = 60 * 1000 * 1000,
        .mode = 0, .spics_io_num = 12, .queue_size = 7,
        .flags = SPI_DEVICE_HALFDUPLEX,
    };
    spi_bus_add_device(SPI2_HOST, &dc, &lcd);
    lcd_cmd(0x01); vTaskDelay(pdMS_TO_TICKS(150));
    lcd_cmd(0x11); vTaskDelay(pdMS_TO_TICKS(150));
    uint8_t d[32];
    memcpy(d,(uint8_t[]){0x01,0x2C,0x2D},3); lcd_cmd(0xB1); lcd_data(d,3);
    memcpy(d,(uint8_t[]){0x01,0x2C,0x2D},3); lcd_cmd(0xB2); lcd_data(d,3);
    memcpy(d,(uint8_t[]){0x01,0x2C,0x2D,0x01,0x2C,0x2D},6); lcd_cmd(0xB3); lcd_data(d,6);
    memcpy(d,(uint8_t[]){0x07},1); lcd_cmd(0xB4); lcd_data(d,1);
    memcpy(d,(uint8_t[]){0xA2,0x02,0x84},3); lcd_cmd(0xC0); lcd_data(d,3);
    memcpy(d,(uint8_t[]){0xC5},1); lcd_cmd(0xC1); lcd_data(d,1);
    memcpy(d,(uint8_t[]){0x0A,0x00},2); lcd_cmd(0xC2); lcd_data(d,2);
    memcpy(d,(uint8_t[]){0x8A,0x2A},2); lcd_cmd(0xC3); lcd_data(d,2);
    memcpy(d,(uint8_t[]){0x8A,0xEE},2); lcd_cmd(0xC4); lcd_data(d,2);
    memcpy(d,(uint8_t[]){0x0E},1); lcd_cmd(0xC5); lcd_data(d,1);
    lcd_cmd(0x20);
    memcpy(d,(uint8_t[]){0xA8},1); lcd_cmd(0x36); lcd_data(d,1);
    memcpy(d,(uint8_t[]){0x05},1); lcd_cmd(0x3A); lcd_data(d,1);
    memcpy(d,(uint8_t[]){0x00,0x02,0x00,0x81},4); lcd_cmd(0x2A); lcd_data(d,4);
    memcpy(d,(uint8_t[]){0x00,0x01,0x00,0xA0},4); lcd_cmd(0x2B); lcd_data(d,4);
    memcpy(d,(uint8_t[]){0x02,0x1c,0x07,0x12,0x37,0x32,0x29,0x2d,0x29,0x25,0x2B,0x39,0x00,0x01,0x03,0x10},16); lcd_cmd(0xE0); lcd_data(d,16);
    memcpy(d,(uint8_t[]){0x03,0x1d,0x07,0x06,0x2E,0x2C,0x29,0x2D,0x2E,0x2E,0x37,0x3F,0x00,0x00,0x02,0x10},16); lcd_cmd(0xE1); lcd_data(d,16);
    lcd_cmd(0x13); vTaskDelay(pdMS_TO_TICKS(10));
    lcd_cmd(0x29); vTaskDelay(pdMS_TO_TICKS(10));
    ESP_LOGI(TAG,"LCD ready");
}

#define LCD_XSTART 2
#define LCD_YSTART 1

static void lcd_fill(uint16_t color) {
    lcd_cmd(0x2A); uint8_t ca[]={0,0x00,0x00,0x84}; lcd_data(ca,4);
    lcd_cmd(0x2B); uint8_t ra[]={0,0x00,0x00,0xA2}; lcd_data(ra,4);
    lcd_cmd(0x2C); lcd_data16(color, 132*162);
    lcd_cmd(0x2A); uint8_t cva[]={0,LCD_XSTART,0,LCD_XSTART+127}; lcd_data(cva,4);
    lcd_cmd(0x2B); uint8_t rva[]={0,LCD_YSTART,0,LCD_YSTART+127}; lcd_data(rva,4);
}

/* ═══════════════════════════════════════
 * 5x7 ASCII font + CJK rendering
 * ═══════════════════════════════════════ */
static const uint8_t font5x7[96][5] = {
    {0x00,0x00,0x00,0x00,0x00},{0x00,0x00,0x5F,0x00,0x00},{0x00,0x07,0x00,0x07,0x00},{0x14,0x7F,0x14,0x7F,0x14},
    {0x24,0x2A,0x7F,0x2A,0x12},{0x23,0x13,0x08,0x64,0x62},{0x36,0x49,0x55,0x22,0x50},{0x00,0x05,0x03,0x00,0x00},
    {0x00,0x1C,0x22,0x41,0x00},{0x00,0x41,0x22,0x1C,0x00},{0x08,0x2A,0x1C,0x2A,0x08},{0x08,0x08,0x3E,0x08,0x08},
    {0x00,0x50,0x30,0x00,0x00},{0x08,0x08,0x08,0x08,0x08},{0x00,0x60,0x60,0x00,0x00},{0x20,0x10,0x08,0x04,0x02},
    {0x3E,0x51,0x49,0x45,0x3E},{0x00,0x42,0x7F,0x40,0x00},{0x42,0x61,0x51,0x49,0x46},{0x21,0x41,0x45,0x4B,0x31},
    {0x18,0x14,0x12,0x7F,0x10},{0x27,0x45,0x45,0x45,0x39},{0x3C,0x4A,0x49,0x49,0x30},{0x01,0x71,0x09,0x05,0x03},
    {0x36,0x49,0x49,0x49,0x36},{0x06,0x49,0x49,0x29,0x1E},{0x00,0x36,0x36,0x00,0x00},{0x00,0x56,0x36,0x00,0x00},
    {0x00,0x08,0x14,0x22,0x41},{0x14,0x14,0x14,0x14,0x14},{0x41,0x22,0x14,0x08,0x00},{0x02,0x01,0x51,0x09,0x06},
    {0x32,0x49,0x79,0x41,0x3E},{0x7E,0x11,0x11,0x11,0x7E},{0x7F,0x49,0x49,0x49,0x36},{0x3E,0x41,0x41,0x41,0x22},
    {0x7F,0x41,0x41,0x22,0x1C},{0x7F,0x49,0x49,0x49,0x41},{0x7F,0x09,0x09,0x01,0x01},{0x3E,0x41,0x41,0x51,0x32},
    {0x7F,0x08,0x08,0x08,0x7F},{0x00,0x41,0x7F,0x41,0x00},{0x20,0x40,0x41,0x3F,0x01},{0x7F,0x08,0x14,0x22,0x41},
    {0x7F,0x40,0x40,0x40,0x40},{0x7F,0x02,0x04,0x02,0x7F},{0x7F,0x04,0x08,0x10,0x7F},{0x3E,0x41,0x41,0x41,0x3E},
    {0x7F,0x09,0x09,0x09,0x06},{0x3E,0x41,0x51,0x21,0x5E},{0x7F,0x09,0x19,0x29,0x46},{0x46,0x49,0x49,0x49,0x31},
    {0x01,0x01,0x7F,0x01,0x01},{0x3F,0x40,0x40,0x40,0x3F},{0x1F,0x20,0x40,0x20,0x1F},{0x7F,0x20,0x18,0x20,0x7F},
    {0x63,0x14,0x08,0x14,0x63},{0x03,0x04,0x78,0x04,0x03},{0x61,0x51,0x49,0x45,0x43},{0x00,0x7F,0x41,0x41,0x00},
    {0x02,0x04,0x08,0x10,0x20},{0x00,0x41,0x41,0x7F,0x00},{0x04,0x02,0x01,0x02,0x04},{0x40,0x40,0x40,0x40,0x40},
    {0x00,0x01,0x02,0x04,0x00},{0x20,0x54,0x54,0x54,0x78},{0x7F,0x48,0x44,0x44,0x38},{0x38,0x44,0x44,0x44,0x20},
    {0x38,0x44,0x44,0x48,0x7F},{0x38,0x54,0x54,0x54,0x18},{0x08,0x7E,0x09,0x01,0x02},{0x08,0x14,0x54,0x54,0x3C},
    {0x7F,0x08,0x04,0x04,0x78},{0x00,0x44,0x7D,0x40,0x00},{0x20,0x40,0x44,0x3D,0x00},{0x7F,0x10,0x28,0x44,0x00},
    {0x00,0x41,0x7F,0x40,0x00},{0x7C,0x04,0x18,0x04,0x78},{0x7C,0x08,0x04,0x04,0x78},{0x38,0x44,0x44,0x44,0x38},
    {0x7C,0x14,0x14,0x14,0x08},{0x08,0x14,0x14,0x18,0x7C},{0x7C,0x08,0x04,0x04,0x08},{0x48,0x54,0x54,0x54,0x20},
    {0x04,0x3F,0x44,0x40,0x20},{0x3C,0x40,0x40,0x20,0x7C},{0x1C,0x20,0x40,0x20,0x1C},{0x3C,0x40,0x30,0x40,0x3C},
    {0x44,0x28,0x10,0x28,0x44},{0x0C,0x50,0x50,0x50,0x3C},{0x44,0x64,0x54,0x4C,0x44},{0x00,0x08,0x36,0x41,0x00},
    {0x00,0x00,0x7F,0x00,0x00},{0x00,0x41,0x36,0x08,0x00},{0x08,0x04,0x08,0x10,0x08},
};

#define CHAR_W 6
#define CHAR_H 8

static void lcd_set_window(int x, int y, int w, int h) {
    lcd_cmd(0x2A);
    uint8_t ca[] = {0, LCD_XSTART + x, 0, LCD_XSTART + x + w - 1}; lcd_data(ca, 4);
    lcd_cmd(0x2B);
    uint8_t ra[] = {0, LCD_YSTART + y, 0, LCD_YSTART + y + h - 1}; lcd_data(ra, 4);
    lcd_cmd(0x2C);
}

static void lcd_draw_char(char c, int x, int y, uint16_t color, uint16_t bg) {
    if (c < 32 || c > 127) return;
    const uint8_t *glyph = font5x7[c - 32];
    uint16_t buf[5 * 7]; int idx = 0;
    for (int row = 0; row < 7; row++)
        for (int col = 0; col < 5; col++)
            buf[idx++] = (glyph[col] & (1 << row)) ? color : bg;
    lcd_set_window(x, y, 5, 7);
    aw_digitalWrite(AW_P1_4, 1);
    spi_transaction_t t = {.length = 5 * 7 * 16, .tx_buffer = buf};
    spi_device_transmit(lcd, &t);
}

static void lcd_draw_bitmap16(const uint8_t *bitmap, int x, int y, uint16_t color, uint16_t bg) {
    uint16_t buf[16 * 16]; int idx = 0;
    for (int row = 0; row < 16; row++) {
        uint8_t b0 = bitmap[row * 2], b1 = bitmap[row * 2 + 1];
        for (int col = 0; col < 8; col++) buf[idx++] = (b0 & (0x80 >> col)) ? color : bg;
        for (int col = 0; col < 8; col++) buf[idx++] = (b1 & (0x80 >> col)) ? color : bg;
    }
    lcd_set_window(x, y, 16, 16);
    aw_digitalWrite(AW_P1_4, 1);
    spi_transaction_t t = {.length = 16 * 16 * 16, .tx_buffer = buf};
    spi_device_transmit(lcd, &t);
}

static void lcd_draw_bitmap24(const uint8_t *bitmap, int x, int y, uint16_t color, uint16_t bg) {
    static uint16_t buf[24 * 24]; int idx = 0;
    for (int row = 0; row < 24; row++) {
        uint8_t b0 = bitmap[row * 3], b1 = bitmap[row * 3 + 1], b2 = bitmap[row * 3 + 2];
        for (int col = 0; col < 8; col++) buf[idx++] = (b0 & (0x80 >> col)) ? color : bg;
        for (int col = 0; col < 8; col++) buf[idx++] = (b1 & (0x80 >> col)) ? color : bg;
        for (int col = 0; col < 8; col++) buf[idx++] = (b2 & (0x80 >> col)) ? color : bg;
    }
    lcd_set_window(x, y, 24, 24);
    aw_digitalWrite(AW_P1_4, 1);
    spi_transaction_t t = {.length = 24 * 24 * 16, .tx_buffer = buf};
    spi_device_transmit(lcd, &t);
}

static void lcd_draw_text(const char *str, int x, int y, uint16_t color, uint16_t bg) {
    int cx = x, cy = y;
    for (int i = 0; str[i]; ) {
        if (str[i] == '\n') { cx = x; cy += CHAR_H; i++; continue; }
        uint8_t c = (uint8_t)str[i];
        if (c < 0x80) {
            if (cx + CHAR_W > 128) { cx = x; cy += CHAR_H; }
            if (cy + CHAR_H > 128) return;
            if (c >= 32) lcd_draw_char(c, cx, cy, color, bg);
            cx += CHAR_W; i++;
        } else if ((c & 0xE0) == 0xC0) {
            i += 2;
        } else if ((c & 0xF0) == 0xE0 && str[i+1] && str[i+2]) {
            uint16_t unicode = ((c & 0x0F) << 12) | (((uint8_t)str[i+1] & 0x3F) << 6) | ((uint8_t)str[i+2] & 0x3F);
            if (cx + 16 > 128) { cx = x; cy += 18; if (cy + 18 > 128) return; }
            uint8_t bitmap[72];
            // Unifont 16x16 原生點陣（20992 CJK，嵌入式 flash，快速）
            if (efont_supp_lookup(unicode, bitmap) == 0) {
                lcd_draw_bitmap16(bitmap, cx, cy, color, bg); cx += 16;
            } else if (font_chip_get_16x16(unicode, bitmap) == 0) {
                lcd_draw_bitmap16(bitmap, cx, cy, color, bg); cx += 16;
            } else if (font_chip_get_24x24(unicode, bitmap) == 0) {
                if (cx + 24 > 128) { cx = x; cy += 26; if (cy + 26 > 128) { i += 3; continue; } }
                lcd_draw_bitmap24(bitmap, cx, cy, color, bg); cx += 24;
            } else { cx += 16; }
            i += 3;
        } else { i++; }
    }
}

static void lcd_show_state(const char *line1, const char *line2, const char *line3, uint16_t c1) {
    lcd_fill(0x0000);
    if (line1) lcd_draw_text(line1, 2, 4, c1, 0x0000);
    if (line2) lcd_draw_text(line2, 2, 38, 0xFFFF, 0x0000);
    if (line3) lcd_draw_text(line3, 2, 110, 0x07E0, 0x0000);
}

/* ═══════════════════════════════════════
 * Mic I2S + Speaker I2S
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
    PIN_FUNC_SELECT(PERIPHS_IO_MUX_GPIO0_U, FUNC_GPIO0_CLK_OUT1);
    wav_buf = (int16_t *)heap_caps_malloc(WAV_BUF_SIZE, MALLOC_CAP_SPIRAM);
    if (!wav_buf) wav_buf = (int16_t *)malloc(WAV_BUF_SIZE);
    if(!wav_buf) ESP_LOGE(TAG,"FATAL: malloc WAV buffer failed!");
    else ESP_LOGI(TAG,"Mic ready (%d bytes buffer)", WAV_BUF_SIZE);
}

static bool speaker_ok = false;
static void speaker_init(void) {
    i2s_config_t c = {
        .mode = I2S_MODE_MASTER | I2S_MODE_TX | I2S_MODE_DAC_BUILT_IN,
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT,
        .communication_format = I2S_COMM_FORMAT_STAND_MSB,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 4, .dma_buf_len = 256, .use_apll = true,
    };
    esp_err_t r = i2s_driver_install(I2S_NUM_0, &c, 0, NULL);
    if (r != ESP_OK) { ESP_LOGE(TAG,"Speaker I2S failed"); return; }
    i2s_set_dac_mode(I2S_DAC_CHANNEL_RIGHT_EN);
    aw_digitalWrite(AW_P1_3, 1);
    speaker_ok = true;
}

static void speaker_play(const int16_t *data, size_t samples) {
    if (!speaker_ok || !data) return;
    int16_t buf[256]; size_t offset = 0;
    while(offset < samples) {
        size_t n = samples - offset; if(n > 128) n = 128;
        for(size_t i = 0; i < n; i++) {
            int16_t v = (int16_t)((uint16_t)data[offset+i] ^ 0x8000);
            buf[i*2] = v; buf[i*2+1] = v;
        }
        size_t written;
        i2s_write(I2S_NUM_0, buf, n * 4, &written, portMAX_DELAY);
        offset += n;
    }
}

static void speaker_deinit(void) {
    if (!speaker_ok) return;
    i2s_driver_uninstall(I2S_NUM_0);
    speaker_ok = false;
    gpio_set_direction(26, GPIO_MODE_INPUT);
    gpio_set_pull_mode(26, GPIO_FLOATING);
}

/* ═══════════════════════════════════════
 * WebSocket 事件處理器
 * ═══════════════════════════════════════ */
static int ws_send_bin_wrapper(void *client, const uint8_t *data, size_t len) {
    return esp_websocket_client_send_bin((esp_websocket_client_handle_t)client,
                                         (const char *)data, len, portMAX_DELAY);
}

static void ws_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data) {
    esp_websocket_event_data_t *evt = (esp_websocket_event_data_t *)data;
    switch (id) {
    case WEBSOCKET_EVENT_CONNECTED:
        ESP_LOGI(TAG, "WS connected");
        ws_connected = true;
        ws_hello_done = false;
        {
            // Send hello with full headers
            char *hello = xz_build_hello();
            ws_send_json(hello);
            free(hello);
        }
        break;

    case WEBSOCKET_EVENT_DISCONNECTED:
        ESP_LOGI(TAG, "WS disconnected");
        ws_connected = false;
        ws_hello_done = false;
        break;

    case WEBSOCKET_EVENT_DATA:
        if (evt->op_code == 0x01) {
            // Text frame (JSON)
            char text[XZ_TEXT_MAX], emotion[XZ_EMOTION_MAX];
            xz_server_hello_t hello;
            xz_message_type_t type = xz_parse_server_message(
                (const char *)evt->data_ptr, evt->data_len,
                &hello, text, sizeof(text), emotion, sizeof(emotion));

            switch (type) {
            case XZ_MSG_HELLO:
                strncpy(xz_session_id, hello.session_id, XZ_SESSION_ID_MAX - 1);
                xz_downlink_rate = hello.sample_rate > 0 ? hello.sample_rate : 24000;
                audio_pipeline_set_downlink_rate(xz_downlink_rate);
                ws_hello_done = true;
                ESP_LOGI(TAG, "Server hello: session=%s rate=%d",
                         xz_session_id, xz_downlink_rate);
                break;
            case XZ_MSG_STT:
                strncpy(ws_stt_text, text, XZ_TEXT_MAX - 1);
                ws_stt_done = true;
                ESP_LOGI(TAG, "STT: %s", ws_stt_text);
                break;
            case XZ_MSG_LLM:
                strncpy(ws_llm_text, text, XZ_TEXT_MAX - 1);
                strncpy(ws_llm_emotion, emotion, XZ_EMOTION_MAX - 1);
                ws_llm_done = true;
                ws_tts_active = false;
                ws_tts_done = false;
                ESP_LOGI(TAG, "LLM: %s [%s]", ws_llm_text, ws_llm_emotion);
                break;
            case XZ_MSG_TTS_START:
                ws_tts_active = true;
                ws_tts_done = false;
                ESP_LOGI(TAG, "TTS start");
                break;
            case XZ_MSG_TTS_STOP:
                ws_tts_active = false;
                ws_tts_done = true;
                ESP_LOGI(TAG, "TTS stop");
                break;
            case XZ_MSG_TTS_SENTENCE:
                if (text[0])
                    ESP_LOGI(TAG, "TTS sentence: %s", text);
                break;
            case XZ_MSG_SYSTEM:
                if (strcmp(text, "reboot") == 0) esp_restart();
                ESP_LOGI(TAG, "System: %s", text);
                break;
            case XZ_MSG_ALERT:
                ESP_LOGW(TAG, "Alert [%s]: %s", emotion, text);
                break;
            default:
                break;
            }
        } else if (evt->op_code == 0x02) {
            // Binary frame: parse 4-byte v3 header
            if (evt->data_len < 4) break;
            const uint8_t *d = (const uint8_t *)evt->data_ptr;
            uint8_t frame_type = d[0];
            uint16_t payload_size = (d[2] << 8) | d[3];
            if (frame_type == 0 && ws_tts_active && payload_size > 0 && payload_size <= evt->data_len - 4) {
                audio_pipeline_push_opus(d + 4, payload_size);
            } else if (frame_type == 1 && ws_tts_active && payload_size > 0 && payload_size <= evt->data_len - 4) {
                // Raw PCM frame from server (no Opus encode on server side)
                audio_pipeline_push_pcm((const int16_t *)(d + 4), payload_size / 2);
            }
        }
        break;

    case WEBSOCKET_EVENT_ERROR:
        ESP_LOGE(TAG, "WS error");
        break;
    }
}

static void ws_send_json(const char *json_str) {
    if (!ws_connected || !json_str) return;
    esp_websocket_client_send_text(ws_client, json_str, strlen(json_str), portMAX_DELAY);
}

static void ws_init(void) {
    char headers[XZ_AUTH_HEADER_MAX];
    uint8_t mac[6]; char mac_str[18];
    esp_efuse_mac_get_default(mac);
    snprintf(mac_str, sizeof(mac_str), "%02X:%02X:%02X:%02X:%02X:%02X",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    xz_build_headers(headers, sizeof(headers), XZ_TOKEN, mac_str, DEVICE_ID);

    esp_websocket_client_config_t cfg = {
        .uri = WS_URL,
        .headers = headers,
        .skip_cert_common_name_check = true,
        .reconnect_timeout_ms = 10000,
        .network_timeout_ms = 10000,
    };
    ws_client = esp_websocket_client_init(&cfg);
    esp_websocket_register_events(ws_client, WEBSOCKET_EVENT_ANY, ws_event_handler, NULL);
    esp_websocket_client_start(ws_client);

    audio_pipeline_set_ws_sender(ws_client, ws_send_bin_wrapper);
}

/* ═══════════════════════════════════════
 * 狀態機 helpers
 * ═══════════════════════════════════════ */
static void set_led_state(uint8_t r, uint8_t g, uint8_t b) {
    led_set_rgb(0, r, g, b);
}

static void enter_listening(void) {
    ESP_LOGI(TAG, "DBG enter_listening: heap=%d free", (int)xPortGetFreeHeapSize());
    state = STATE_LISTENING;
    set_led_state(255, 0, 0);
    lcd_show_state("聆聽中...", NULL, "放開A掣完成", 0xF800);
    rec_len = 0;

    char *msg = xz_build_listen("start", "manual");
    ESP_LOGI(TAG, "DBG enter_listening: ws_send start (ws_ok=%d)", ws_connected);
    ws_send_json(msg);
    free(msg);

    ESP_LOGI(TAG, "DBG enter_listening: i2s_start");
    i2s_start(I2S_NUM_1);
    i2s_zero_dma_buffer(I2S_NUM_1);
    vTaskDelay(pdMS_TO_TICKS(50));
    audio_pipeline_start_capture();
    ESP_LOGI(TAG, "DBG enter_listening: done, capturing=%d", audio_pipeline_is_capturing());
}

static void exit_listening(void) {
    ESP_LOGI(TAG, "DBG exit_listening: stop capture (frames=%d)", audio_pipeline_captured_frames());
    audio_pipeline_stop_capture();
    ESP_LOGI(TAG, "DBG exit_listening: i2s_stop");
    i2s_stop(I2S_NUM_1);

    char *msg = xz_build_listen("stop", "manual");
    ESP_LOGI(TAG, "DBG exit_listening: ws_send stop (ws_ok=%d)", ws_connected);
    ws_send_json(msg);
    free(msg);

    ESP_LOGI(TAG, "DBG exit_listening: done. frames=%d raw=%d heap=%d",
             audio_pipeline_captured_frames(), (int)rec_len, (int)xPortGetFreeHeapSize());
}

static void send_text_query(const char *text) {
    if (!ws_connected || !ws_hello_done) return;
    ws_stt_done = false; ws_stt_text[0] = 0;
    ws_llm_done = false; ws_llm_text[0] = 0;
    ws_tts_done = false;
    char *msg = xz_build_detect(text, "auto");
    ws_send_json(msg);
    free(msg);
}

/* ═══════════════════════════════════════
 * Main
 * ═══════════════════════════════════════ */
void app_main(void) {
    ESP_LOGI(TAG, "FunConnect starting...");

    // Hardware init
    aw9523b_init();
    aw_pinMode(AW_P1_4, AW_GPIO_MODE_OUTPUT); // DC
    aw_pinMode(AW_P1_5, AW_GPIO_MODE_OUTPUT); // RST
    aw_pinMode(AW_P1_7, AW_GPIO_MODE_OUTPUT); // BL
    aw_pinMode(AW_P1_3, AW_GPIO_MODE_OUTPUT); // Speaker EN

    aw_digitalWrite(AW_P1_5, 0); vTaskDelay(pdMS_TO_TICKS(120));
    aw_digitalWrite(AW_P1_5, 1); vTaskDelay(pdMS_TO_TICKS(120));
    aw_digitalWrite(AW_P1_7, 1);
    aw_digitalWrite(AW_P1_3, 1);

    set_led_state(0, 0, 128); // Blue during init

    lcd_init();
    font_chip_init();

    aw_pinMode(AW_P0_6, AW_GPIO_MODE_INPUT);
    aw_pinMode(AW_P0_5, AW_GPIO_MODE_INPUT);
    aw_pinMode(AW_P0_3, AW_GPIO_MODE_INPUT);

    // WiFi
    lcd_show_state("FunConnect v1.02", "WiFi連接中...", NULL, 0xFFFF);
    wifi_init();
    while (!wifi_ok) vTaskDelay(pdMS_TO_TICKS(200));

    lcd_show_state("WiFi已連接", wifi_ip, NULL, 0x07E0);
    vTaskDelay(pdMS_TO_TICKS(2000));

    // I2C scan
    ESP_LOGI(TAG,"I2C scan:");
    for(uint8_t addr=1; addr<127; addr++) {
        i2c_cmd_handle_t cmd = i2c_cmd_link_create();
        i2c_master_start(cmd);
        i2c_master_write_byte(cmd, (addr<<1)|0, true);
        i2c_master_stop(cmd);
        if(i2c_master_cmd_begin(I2C_NUM_1, cmd, pdMS_TO_TICKS(20)) == ESP_OK)
            ESP_LOGI(TAG,"  I2C dev: 0x%02X", addr);
        i2c_cmd_link_delete(cmd);
    }

    // Mic + Codec
    mic_init();
    i2s_start(I2S_NUM_1);
    vTaskDelay(pdMS_TO_TICKS(100));
    es8218e_init();
    vTaskDelay(pdMS_TO_TICKS(100));
    i2s_zero_dma_buffer(I2S_NUM_1);
    i2s_stop(I2S_NUM_1);

    // Audio pipeline (Opus codec)
    audio_pipeline_init();

    // MQTT — IoT control (non-blocking, background)
    mqtt_client_init(MQTT_BROKER);
    ESP_LOGI(TAG, "MQTT connecting to %s...", MQTT_BROKER);

    // Home screen
    state = STATE_IDLE;
    lcd_show_state("FunConnect v1.02", "小芳智能體 AIOT", "A=錄音 B=提問 C=播放", 0xFFFF);
    set_led_state(0, 255, 0);
    ESP_LOGI(TAG, "=== READY ===");

    int tts_timeout = 0;

    /* ── Main state machine loop ── */
    while (1) {
        int a = aw_digitalRead(AW_P0_6);
        int b = aw_digitalRead(AW_P0_5);
        int j = aw_digitalRead(AW_P0_3);

        switch (state) {

        case STATE_IDLE:
            if (a) {
                enter_listening();
            } else if (b) {
                if (!ws_connected || !ws_hello_done) {
                    lcd_show_state("未連接", "等待伺服器...", NULL, 0xF800);
                    vTaskDelay(pdMS_TO_TICKS(2000));
                    lcd_show_state("FunConnect v1.02", "小芳智能體 AIOT", "A=錄音 B=提問 C=播放", 0xFFFF);
                } else {
                    set_led_state(255, 255, 0);
                    lcd_show_state("發送中...", NULL, NULL, 0xFFC0);
                    send_text_query("你好請用廣東話回答");
                    state = STATE_WAITING_LLM;
                    tts_timeout = 0;
                }
            }
            break;

        case STATE_LISTENING: {
            int chunk_samples = SAMPLE_RATE / 2; // 8000 = 500ms
            size_t chunk_bytes = chunk_samples * sizeof(int16_t);
            if (rec_len + chunk_bytes > WAV_BUF_SIZE)
                chunk_bytes = WAV_BUF_SIZE - rec_len;
            size_t done = 0;
            while (done < chunk_bytes) {
                size_t r;
                i2s_read(I2S_NUM_1, (uint8_t*)wav_buf + rec_len + done,
                         chunk_bytes - done, &r, pdMS_TO_TICKS(20));
                done += r;
            }
            int16_t *p = wav_buf + rec_len / sizeof(int16_t);
            int total = (int)(done / sizeof(int16_t));
            int pos = 0;
            while (pos + XZ_FRAME_SAMPLES <= total) {
                audio_pipeline_encode_and_send(p + pos, XZ_FRAME_SAMPLES);
                pos += XZ_FRAME_SAMPLES;
            }
            rec_len += pos * sizeof(int16_t);
            // Pause I2S for reliable I2C button check
            ESP_LOGI(TAG, "DBG chunk: read=%d enc=%d rec=%d btn=%d heap=%d",
                     (int)done, pos, (int)rec_len, a, (int)xPortGetFreeHeapSize());
            i2s_stop(I2S_NUM_1);
            if (!a || rec_len >= WAV_BUF_SIZE) {
                ESP_LOGI(TAG, "DBG chunk: STOP (btn=%d rec=%d)", a, (int)rec_len);
                exit_listening();
                if (audio_pipeline_captured_frames() > 0) {
                    state = STATE_WAITING_STT;
                    set_led_state(255, 255, 0);
                    lcd_show_state("辨識中...", NULL, NULL, 0xFFC0);
                } else {
                    state = STATE_IDLE;
                    set_led_state(0, 255, 0);
                    lcd_show_state("太短，請重試", NULL, "A=錄音", 0xF800);
                    vTaskDelay(pdMS_TO_TICKS(1500));
                    lcd_show_state("FunConnect v1.02", "小芳智能體 AIOT", "A=錄音 B=提問 C=播放", 0xFFFF);
                }
            } else {
                i2s_start(I2S_NUM_1);
                vTaskDelay(pdMS_TO_TICKS(10));
            }
            break;
        }

        case STATE_WAITING_STT:
            if (ws_stt_done) {
                ws_stt_done = false;
                lcd_show_state("你說:", ws_stt_text, NULL, 0xFFFF);
                state = STATE_WAITING_LLM;
                tts_timeout = 0;
            } else {
                tts_timeout++;
                if (tts_timeout > 150) { // 15s timeout
                    state = STATE_ERROR;
                }
            }
            break;

        case STATE_WAITING_LLM:
            if (ws_llm_done) {
                ws_llm_done = false;
                lcd_show_state("小芳:", ws_llm_text, NULL, 0xFFFF);
                if (ws_tts_active) {
                    speaker_init();
                    audio_pipeline_start_playback();
                    state = STATE_PLAYING;
                    set_led_state(0, 0, 255);
                    ESP_LOGI(TAG, "TTS playback started");
                } else {
                    state = STATE_WAITING_TTS;
                    tts_timeout = 0;
                }
            } else {
                tts_timeout++;
                if (tts_timeout > 120) { // 12s timeout
                    state = STATE_ERROR;
                }
            }
            break;

        case STATE_WAITING_TTS:
            if (ws_tts_active) {
                speaker_init();
                audio_pipeline_start_playback();
                state = STATE_PLAYING;
                set_led_state(0, 0, 255);
            } else if (ws_tts_done) {
                ws_tts_done = false;
                state = STATE_IDLE;
                set_led_state(0, 255, 0);
                vTaskDelay(pdMS_TO_TICKS(2000));
                lcd_show_state("FunConnect v1.02", "小芳智能體 AIOT", "A=錄音 B=提問 C=播放", 0xFFFF);
            }
            break;

        case STATE_PLAYING:
            if (audio_pipeline_is_playing() && ws_tts_active) {
                // Try Opus frames first, then PCM
                int16_t pcm[1440];
                int samples = audio_pipeline_play_one_frame(pcm, 1440);
                if (samples > 0) {
                    speaker_play(pcm, samples);
                } else {
                    // Check PCM buffer
                    samples = audio_pipeline_read_pcm(pcm, 1024);
                    if (samples > 0) speaker_play(pcm, samples);
                }
            } else if (ws_tts_done || !ws_tts_active) {
                // Drain remaining Opus frames
                while (audio_pipeline_tts_buffered() > 0) {
                    int16_t pcm[1440];
                    int samples = audio_pipeline_play_one_frame(pcm, 1440);
                    if (samples > 0) speaker_play(pcm, samples);
                    else break;
                }
                // Drain remaining PCM
                while (audio_pipeline_pcm_buffered() > 0) {
                    int16_t pcm[1024];
                    int samples = audio_pipeline_read_pcm(pcm, 1024);
                    if (samples > 0) speaker_play(pcm, samples);
                    else break;
                }
                audio_pipeline_stop_playback();
                speaker_deinit();
                ws_tts_done = false;
                state = STATE_IDLE;
                set_led_state(0, 255, 0);
                vTaskDelay(pdMS_TO_TICKS(1000));
                lcd_show_state("FunConnect v1.02", "小芳智能體 AIOT", "A=錄音 B=提問 C=播放", 0xFFFF);
                ESP_LOGI(TAG, "Playback complete, back to IDLE");
            }
            break;

        case STATE_UPLOADING:
            break;

        case STATE_ERROR:
            set_led_state(255, 0, 0);
            lcd_show_state("錯誤/超時", "請檢查網絡", "任意掣重試", 0xF800);
            if (a || b || j) {
                audio_pipeline_reset();
                audio_pipeline_init();
                audio_pipeline_set_ws_sender(ws_client, ws_send_bin_wrapper);
                state = STATE_IDLE;
                set_led_state(0, 255, 0);
                lcd_show_state("FunConnect v1.02", "小芳智能體 AIOT", "A=錄音 B=提問 C=播放", 0xFFFF);
            }
            break;
        }

        // Joystick center: play back raw recording (local echo)
        if (j && rec_len > 0 && state == STATE_IDLE) {
            set_led_state(128, 128, 0);
            lcd_show_state("播放中...", NULL, NULL, 0xFFC0);
            speaker_init();
            speaker_play(wav_buf, rec_len / 2);
            speaker_deinit();
            set_led_state(0, 255, 0);
            lcd_show_state("FunConnect v1.02", "小芳智能體 AIOT", "A=錄音 B=提問 C=播放", 0xFFFF);
        }

        vTaskDelay(pdMS_TO_TICKS(50));
    }
}
