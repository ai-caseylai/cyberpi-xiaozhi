# CyberPi ESP32 小智固件

ESP-IDF C 固件，比 CyberPi 原生 WiFi + I2S 錄音 + HTTP POST upload + ST7735 顯示。

## 硬件需求

- Makeblock CyberPi (ESP32)
- USB-C cable

## 功能

| 操作 | 效果 |
|------|------|
| 按 A | I2S 錄音 3 秒 → POST WAV → server ASR → 顯示文字 → LLM 回答 → TTS |
| 按 B | 預設問候 → server chat → TTS |
| LED | 綠=待命, 紫=錄音, 藍=上傳, 黃=LLM, 紅=error |

## 編譯步驟

### 1. 安裝 ESP-IDF v5.4+

```bash
git clone --recursive https://github.com/espressif/esp-idf
cd esp-idf
./install.sh esp32
source export.sh
```

### 2. 編譯

```bash
cd cyberpi_firmware
idf.py set-target esp32
idf.py build
```

### 3. Flash

```bash
idf.py -p /dev/ttyUSB0 flash monitor
```

## Pin 配置 (from Makeblock Arduino Library ✅)

| 功能 | 接腳 | 晶片 |
|------|------|------|
| LCD MOSI | GPIO 2 | ESP32 SPI |
| LCD CLK | GPIO 4 | ESP32 SPI |
| LCD CS | GPIO 12 | ESP32 SPI |
| LCD DC | P1_4 | AW9523B I2C expander |
| LCD RST | P1_5 | AW9523B I2C expander |
| LCD BL | P1_7 | AW9523B I2C expander |
| Mic BCK | GPIO 13 | I2S1 |
| Mic WS | GPIO 14 | I2S1 |
| Mic DIN | GPIO 35 | I2S1 (ES8218E codec) |
| Speaker | Internal DAC | I2S0 DAC |
| Speaker EN | P1_3 | AW9523B |
| Button A | P0_6 | AW9523B |
| Button B | P0_5 | AW9523B |
| LED RGB x4 | I2C 0x5B | LED driver |
| I2C SDA | GPIO 21 | AW9523B + LED |
| I2C SCL | GPIO 22 | AW9523B + LED |
| Light sensor | GPIO 33 | ADC |

**來源: [CyberPi Arduino Library](https://github.com/Makeblock-official/CyberPi-Library-for-Arduino)**

## TODO (如果你要完善)

1. **LVGL 整合** — 目前 `display_text()` 係 placeholder，需要加字庫
2. **mbedtls base64** — 用 `mbedtls_base64_encode()` 代替手寫
3. **TTS speaker** — 加 I2S speaker 播放 MP3 (需要解碼)
4. **URL encode** — 完整 UTF-8 URL encode
5. **FreeRTOS tasks** — 錄音放獨立 task 避免 block
