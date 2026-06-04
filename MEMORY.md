# 小芳智能體 FunConnect AIOT — 記憶體使用報告

## CyberPi ESP32 資源配置

| 資源 | 總量 | 已用 | 剩餘 | 使用率 |
|------|------|------|------|--------|
| **Flash** | 4 MB | 2.63 MB | 1.37 MB | 66% |
| **PSRAM** | 8 MB | ~4.8 MB | ~3.2 MB | 60% |
| **Internal SRAM** | 520 KB | ~280 KB | ~240 KB | 54% |
| **CPU** | 240 MHz | -O2 優化 | — | — |

---

## Flash 用量明細（2.63 MB binary）

| 組件 | 大小 | 說明 |
|------|------|------|
| **Unifont 16x16 點陣字型** | 714 KB | efont_supp.h：20,992 CJK 字符，二進位搜尋查找 |
| **libopus 編解碼** | ~80 KB | CELT + SILK encoder/decoder，complexity=1 |
| **mbedtls TLS** | ~60 KB | WSS 加密連線所需 |
| **WiFi + lwIP 協議棧** | ~55 KB | TCP/IP + WiFi station mode |
| **GT30L24A3W 字庫驅動** | 50 KB | SPI 字庫晶片 library（後備字型） |
| **WebSocket client** | ~35 KB | esp_websocket_client v1.7.0 |
| **主程式** | ~35 KB | main + audio_pipeline + xiaozhi_protocol + mqtt |
| **MQTT client** | ~8 KB | esp-mqtt（連接 EMQX.io） |
| **cJSON** | ~8 KB | JSON 解析/構造 |
| **aw9523b + es8218e** | ~5 KB | GPIO expander + MEMS mic codec 驅動 |
| **ESP-IDF 框架** | ~200 KB | FreeRTOS, SPI, I2C, I2S, GPIO 驅動 |

### Flash Partition 配置

```
Offset   Size      Partition
0x1000   0x7000    bootloader (28KB)
0x8000   0x1000    partition table
0x9000   0x5000    nvs (20KB)
0xE000   0x2000    otadata (8KB)
0x10000  0x1000    phy_init (4KB)
0x20000  0x3C0000  factory app (3.75MB)  ← firmware
────────────────────────────────
Total:   4MB flash
```

---

## PSRAM 用量明細（8 MB 外部 SPI RAM）

| 緩衝區 | 大小 | 說明 |
|------|------|------|
| **WAV 錄音 buffer** | 3.84 MB | 120 秒 @ 16kHz 16-bit mono |
| **PCM TTS 播放 buffer** | 960 KB | 30 秒 TTS 音頻緩衝 |
| **Opus ring buffer** | 48 KB | 32 frames × 1500 bytes |
| **剩餘可用** | ~3.2 MB | 擴展空間 |

### 分配策略
- `wav_buf`：`heap_caps_malloc(WAV_BUF_SIZE, MALLOC_CAP_SPIRAM)` → fallback `malloc()`
- `p_pcm_buf`：同上，優先 PSRAM
- Opus ring buffer (`p_tts_buf`)：static BSS → 編譯時分配

---

## Internal SRAM 用量明細（520 KB 內置 RAM）

| 用途 | 大小 | 說明 |
|------|------|------|
| **Main task stack** | 24 KB | `CONFIG_ESP_MAIN_TASK_STACK_SIZE=24576` |
| **Opus encoder state** | ~40 KB | SILK encoder internal state |
| **Opus decoder state** | ~20 KB | CELT decoder internal state |
| **FreeRTOS kernel** | ~40 KB | Scheduler, queues, timers |
| **WiFi + TCP buffers** | ~80 KB | lwIP heap + WiFi 驅動 |
| **SPI/I2C/I2S DMA** | ~20 KB | 各驅動 DMA buffer |
| **Event loop** | ~10 KB | 系統事件處理 |
| **Heap 剩餘** | ~240 KB | `malloc()` 動態分配 |

### 關鍵配置
- `CONFIG_FREERTOS_HZ=1000`（1ms tick）
- `CONFIG_ESP_TASK_WDT_TIMEOUT_S=30`
- `CONFIG_SPIRAM_CACHE_WORKAROUND_STRATEGY_MEMW`（PSRAM 快取策略）
- `CONFIG_HEAP_POISONING_DISABLED=y`（不檢查 heap，節省 RAM）
- `CONFIG_COMPILER_OPTIMIZATION_PERF=y`（-O2 優化）

---

## Runtime 記憶體流程

```
[啟動]
  1. bootloader → partition table → factory app
  2. FreeRTOS init (40KB SRAM)
  3. WiFi connect → TCP/IP stack init (80KB SRAM)

[錄音模式]
  1. I2S1 DMA → wav_buf (3.84MB PSRAM)
  2. Opus encoder state (40KB SRAM)
  3. encode: 960 samples → ~200 bytes Opus
  4. WebSocket send: 4-byte header + Opus payload

[TTS 播放模式]
  1. WebSocket receive → Opus frame buffer (48KB) or PCM buffer (960KB PSRAM)
  2. Opus decoder state (20KB SRAM)
  3. decode → I2S0 DAC (GPIO25)

[CJK 文字渲染]
  1. efont_supp_lookup() → binary search 20,992 entries (flash, fast)
  2. fallback: font_chip_get_16x16() → SPI GT30L24A3W
  3. fallback: font_chip_get_24x24() → 24x24 點陣

[MQTT IoT]
  1. esp-mqtt background task → EMQX.io
  2. Publish sensor data on timer
  3. Subscribe command topics for device control
```

---

*文件版本：v1.0 | 2026-06-05 | FunConnect AIOT Platform*
