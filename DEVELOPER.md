# 小芳智能體 FunConnect AIOT 平台 — 開發者文件

## 目錄
1. [系統架構](#1-系統架構)
2. [硬體規格](#2-硬體規格)
3. [通訊協議](#3-通訊協議)
4. [Firmware 開發](#4-firmware-開發)
5. [Cloudflare 後端開發](#5-cloudflare-後端開發)
6. [API 參考](#6-api-參考)
7. [MQTT IoT 協議](#7-mqtt-iot-協議)
8. [編譯與部署](#8-編譯與部署)
9. [除錯指南](#9-除錯指南)

---

## 1. 系統架構

```
┌─────────────────────────┐        ┌──────────────────────────────┐
│  CyberPi ESP32          │        │  Cloudflare Edge              │
│                          │        │                              │
│  ┌──────────────────┐   │  WSS   │  ┌────────────────────────┐  │
│  │ I2S Mic (16kHz)  │───┼────────▶│  │ Worker (index.ts)      │  │
│  │   ↓ Opus encode  │   │ Opus   │  │  ├ auth + upgrade       │  │
│  │ WebSocket send    │   │ 16kHz  │  │  └→ Durable Object      │  │
│  └──────────────────┘   │        │  └──────────┬─────────────┘  │
│                          │        │             │                │
│  ┌──────────────────┐   │  WSS   │  ┌──────────▼─────────────┐  │
│  │ WebSocket recv   │◄──┼────────│  │ FunConnectSession (DO) │  │
│  │   ↓ Opus/PCM dec │   │ PCM    │  │  ├ hello handshake     │  │
│  │ I2S DAC Speaker  │   │ 16kHz  │  │  ├ listen→audio buffer │  │
│  └──────────────────┘   │        │  │  ├ STT (Nova-3)        │  │
│                          │        │  │  ├ LLM (Qwen)          │  │
│  ┌──────────────────┐   │  MQTT  │  │  └ TTS (Aura-1)→PCM   │  │
│  │ MQTT Client      │───┼────────▶│  └───────────────────────┘  │
│  │ (EMQX.io)        │   │        │                              │
│  │ pub sensor/state │   │        │  ┌────────────────────────┐  │
│  │ sub cmd/#        │   │        │  │ EMQX.io MQTT Broker    │  │
│  └──────────────────┘   │        │  │ (IoT device control)   │  │
└─────────────────────────┘        │  └────────────────────────┘  │
                                   └──────────────────────────────┘
```

### 數據流（一次完整語音對話）

```
用戶按 A 掣 → 錄音開始
    │
    ▼
I2S1 RX (ES8218E codec) → 16kHz 16-bit PCM
    │
    ▼
WAV buffer (PSRAM 3.84MB) → 每 960 samples 一個 Opus frame
    │
    ▼
WebSocket binary frame (4-byte v3 header + Opus)
    │
    ▼ WSS → Cloudflare Worker → Durable Object
    │
    ├─▶ Nova-3 STT → 文字
    ├─▶ Qwen LLM → 粵語回覆
    └─▶ Aura-1 TTS → WAV → PCM chunks → WebSocket binary frames
            │
            ▼ WSS → CyberPi
    WebSocket receive → PCM buffer → I2S0 DAC → Speaker 播放
```

---

## 2. 硬體規格

### CyberPi (Makeblock)

| 元件 | 規格 | 接腳 |
|------|------|------|
| **MCU** | ESP32 雙核 Xtensa LX6 @ 240MHz | — |
| **Flash** | 4MB SPI | — |
| **PSRAM** | 8MB Quad SPI @ 40MHz | CLK=GPIO17, CS=GPIO16 |
| **Internal SRAM** | 520KB | — |
| **LCD** | ST7735 128x128 RGB565 | SPI2: MOSI=2, CLK=4, CS=12 |
| **LCD control** | AW9523B I2C expander | DC=P1_4, RST=P1_5, BL=P1_7 |
| **Microphone** | ES8218E MEMS codec | I2S1: BCK=13, WS=14, DIN=35, MCLK=GPIO0 |
| **Speaker** | Internal DAC | I2S0 DAC: GPIO25 |
| **Speaker EN** | AW9523B | P1_3 |
| **Button A** | AW9523B | P0_6 (active low) |
| **Button B** | AW9523B | P0_5 (active low) |
| **Joystick center** | AW9523B | P0_3 (active low) |
| **RGB LEDs x4** | AW9523B @ 0x5B | LED mode DIM00-DIM11 |
| **I2C bus** | I2C_NUM_1 @ 400kHz | SDA=19, SCL=18 |
| **Font chip** | GT30L24A3W SPI | SPI2: CS=27 |
| **Light sensor** | ADC | GPIO33 |

### AW9523B 暫存器

| Address | Chip | Function |
|---------|------|----------|
| 0x5B | LED driver | DIM00-DIM11 = 4x RGB (12 channels) |
| 0x58 | GPIO expander | P0_0-P0_7, P1_0-P1_7 |
| 0x58 P0 | Input | P0_3(joystick), P0_5(B), P0_6(A) |
| 0x58 P1 | Output | P1_3(spk EN), P1_4(LCD DC), P1_5(LCD RST), P1_7(LCD BL) |

---

## 3. 通訊協議

### 3.1 xiaozhi-esp32 WebSocket 協議 v3

**連線**：
```
URL: wss://funconnect-backend.ai-caseylai.workers.dev/xiaozhi/v1/
Headers:
  Authorization: Bearer <token>
  Protocol-Version: 3
  Device-Id: <MAC address>
  Client-Id: <device UUID>
```

**Binary frame format (4-byte header)**：
```
Byte 0: type (0=Opus, 1=PCM)
Byte 1: reserved (0)
Byte 2-3: payload_size (big-endian uint16)
Bytes 4+: payload
```

**JSON 消息流程**：

```
Device → Server (hello):
{
  "type": "hello",
  "version": 3,
  "transport": "websocket",
  "features": {"mcp": true},
  "audio_params": {
    "format": "opus",
    "sample_rate": 16000,
    "channels": 1,
    "frame_duration": 60
  }
}

Server → Device (hello):
{
  "type": "hello",
  "session_id": "uuid",
  "audio_params": {
    "format": "opus",
    "sample_rate": 16000,
    "channels": 1,
    "frame_duration": 60
  }
}

Device → Server (listen start):
{"type": "listen", "state": "start", "mode": "manual"}

Device → Server (listen stop):
{"type": "listen", "state": "stop", "mode": "manual"}

Server → Device (STT result):
{"type": "stt", "text": "transcribed text"}

Server → Device (LLM response):
{"type": "llm", "emotion": "happy", "text": "response text"}

Server → Device (TTS lifecycle):
{"type": "tts", "state": "start"}
{"type": "tts", "state": "stop"}

Device → Server (abort):
{"type": "abort", "reason": "button_pressed"}

Device → Server (text query):
{"type": "listen", "state": "detect", "text": "你好"}

Server → Device (system command):
{"type": "system", "command": "reboot"}

Server → Device (alert):
{"type": "alert", "status": "Warning", "message": "...", "emotion": "sad"}
```

### 3.2 Opus 音頻參數

| 參數 | 上行（錄音） | 下行（播放） |
|------|------------|------------|
| 採樣率 | 16000 Hz | 16000 Hz |
| 聲道 | 1 (mono) | 1 (mono) |
| Frame duration | 60 ms | 60 ms |
| Frame samples | 960 | 960 |
| Encoder complexity | 1 (最低 CPU) | — |
| Bitrate | 32000 bps (CBR) | — |
| Application | OPUS_APPLICATION_VOIP | — |

---

## 4. Firmware 開發

### 4.1 目錄結構

```
cyberpi_firmware/
├── main/
│   ├── main.c              # 主程式：狀態機、LCD、WiFi、WebSocket
│   ├── aw9523b.c/h         # AW9523B GPIO expander + LED 驅動
│   ├── es8218e.c/h         # ES8218E MEMS mic codec 驅動
│   ├── font_chip.c/h       # GT30L24A3W SPI 字庫晶片驅動
│   ├── efont_supp.h        # Unifont 16x16 嵌入式點陣字型（20,992 CJK）
│   ├── libGT30L24A3W.a     # 預編譯字庫 library
│   ├── opus_codec.c/h      # Opus 編解碼包裝層
│   ├── xiaozhi_protocol.c/h # xiaozhi-esp32 協議層
│   ├── audio_pipeline.c/h  # 音頻流水線（I2S↔Opus↔WS）
│   ├── fmqtt_client.c/h    # MQTT IoT client
│   ├── CMakeLists.txt      # 組件建構
│   └── idf_component.yml   # 依賴管理
├── partitions.csv          # Flash 分區表
├── sdkconfig               # ESP-IDF 配置
├── sdkconfig.defaults      # 預設配置覆寫
├── dependencies.lock       # 依賴鎖定
└── managed_components/     # 託管組件（自動下載）
    ├── 78__esp-opus/       # libopus for ESP32
    └── espressif__esp_websocket_client/  # WebSocket client
```

### 4.2 狀態機

```
                    ┌─────────┐
          ┌────────▶│  IDLE   │◀────────┐
          │         └────┬────┘         │
          │         A 按下│              │ 完成
          │              ▼              │
          │     ┌────────────┐          │
          │     │ LISTENING  │          │
          │     │ (錄音+Opus) │          │
          │     └─────┬──────┘          │
          │      A 放開│                │
          │           ▼                 │
          │   ┌──────────────┐          │
          │   │ WAITING_STT  │          │
          │   │ (等辨識結果)  │          │
          │   └──────┬───────┘          │
          │      STT │                  │
          │          ▼                  │
          │   ┌──────────────┐   ┌──────────┐
          │   │ WAITING_LLM  │   │  ERROR   │
          │   │ (等LLM回覆)   │   │ (超時/斷線)│
          │   └──────┬───────┘   └──────────┘
          │      LLM │                  ▲
          │          ▼                  │
          │   ┌──────────────┐          │
          │   │ WAITING_TTS  │          │
          │   └──────┬───────┘          │
          │     TTS  │                  │
          │          ▼                  │
          │   ┌──────────┐              │
          └───│ PLAYING  │──────────────┘
              │ (喇叭播放) │
              └──────────┘
```

### 4.3 LED 狀態指示

| 顏色 | 狀態 | RGB |
|------|------|-----|
| 綠色 | IDLE 待命 | (0, 255, 0) |
| 紅色 | LISTENING 錄音中 | (255, 0, 0) |
| 黃色 | 處理中（STT/LLM/TTS） | (255, 255, 0) |
| 藍色 | PLAYING 播放中 | (0, 0, 255) |
| 紫色 | 初始化中 | (128, 0, 128) |
| 紅色閃爍 | ERROR 錯誤 | (255, 0, 0) |

### 4.4 按鍵功能

| 按鍵 | IDLE 狀態 | 其他狀態 |
|------|----------|---------|
| **A** | 按住開始錄音，放開停止並發送 | 中斷當前操作 |
| **B** | 發送文字問候（無錄音） | — |
| **搖桿中心** | 播放上一次錄音（本地回放） | — |

### 4.5 關鍵函數

#### opus_codec.h
```c
// 創建 encoder (16kHz, 60ms frames)
opus_codec_ctx_t *x_opus_encoder_create(int sample_rate, int frame_ms);

// 編碼 PCM → Opus，返回 encoded bytes
int opus_encode_frame(ctx, pcm, samples, out, out_max);

// 創建 decoder
opus_codec_ctx_t *x_opus_decoder_create(int sample_rate, int frame_ms);

// 解碼 Opus → PCM，返回 sample count
int opus_decode_frame(ctx, opus_data, len, pcm_out, pcm_max);
```

#### audio_pipeline.h
```c
// 初始化（建立 encoder + decoder）
esp_err_t audio_pipeline_init(void);

// 上行：編碼 PCM frame 並 send via WebSocket
esp_err_t audio_pipeline_encode_and_send(pcm, samples);

// 下行：push Opus/PCM frame 到播放緩衝
esp_err_t audio_pipeline_push_opus(opus_data, len);
esp_err_t audio_pipeline_push_pcm(pcm, samples);

// 播放：從緩衝讀取並解碼/播放
int audio_pipeline_play_one_frame(pcm_out, max);
int audio_pipeline_read_pcm(pcm_out, max);
```

#### xiaozhi_protocol.h
```c
// 建立 WebSocket headers
void xz_build_headers(buf, size, token, device_id, client_id);

// 建立 JSON 消息（返回 malloc'd string）
char *xz_build_hello(void);
char *xz_build_listen(state, mode);
char *xz_build_detect(text, mode);
char *xz_build_abort(reason);

// 解析 server JSON → message type enum
xz_message_type_t xz_parse_server_message(json, len, hello, text, emotion);

// 建立 binary frame header（4 bytes, type=0 for Opus, 1 for PCM）
static inline void xz_build_binary_header(buf, payload_size);
```

---

## 5. Cloudflare 後端開發

### 5.1 目錄結構

```
cloudflare/
├── wrangler.toml         # Worker + DO + AI 配置
├── package.json          # npm 依賴
├── tsconfig.json         # TypeScript 配置
├── .gitignore
└── src/
    ├── index.ts           # Worker 入口（路由 + auth）
    ├── durable_object.ts  # DO session handler
    ├── protocol.ts        # xiaozhi-esp32 協議 types
    ├── ai.ts              # AI helpers（RAG prompt、安全過濾）
    └── aliyun_asr.ts      # 阿里雲 ASR 模組（待 credential）
```

### 5.2 Durable Object 生命週期

```typescript
class FunConnectSession extends DurableObject {
  // 狀態：hello → idle → listening → processing → speaking → idle
  private state: SessionState;

  async fetch(request: Request): Promise<Response> {
    // 1. WebSocket upgrade
    // 2. Accept connection
    // 3. Register event handlers
  }

  private async onJsonMessage(msg): Promise<void> {
    switch (msg.type) {
      case 'hello':   → 握手，回覆 session_id + audio_params
      case 'listen':  → start (開始緩衝) / stop (觸發 AI) / detect (純文字)
      case 'abort':   → 重置狀態
    }
  }

  private async processAudio(): Promise<void> {
    // 1. Concat Opus chunks → single buffer
    // 2. Workers AI Nova-3 STT
    // 3. Send stt message to device
    // 4. Qwen LLM → send llm message
    // 5. Aura-1 TTS → WAV → PCM chunks → binary frames
    // 6. Send tts stop
  }
}
```

### 5.3 環境變數

| Variable | 用途 | 預設值 |
|----------|------|--------|
| `AUTH_TOKEN` | WebSocket 認證 token | `funconnect-token` |
| `QWEN_API_KEY` | 阿里雲百煉 API key | `sk-4f18...` |
| `QWEN_MODEL` | Qwen 模型 | `qwen-plus` |
| `LLM_MODEL` | Workers AI LLM (fallback) | `@cf/meta/llama-4-scout-17b-16e-instruct` |
| `TTS_MODEL` | Workers AI TTS | `@cf/deepgram/aura-1` |
| `STT_MODEL` | Workers AI STT | `@cf/deepgram/nova-3` |

### 5.4 部署指令

```bash
cd cloudflare
npm install
npx wrangler deploy                    # 部署到 workers.dev
npx wrangler tail                      # 即時日誌
npx wrangler dev --local               # 本地測試（需 Miniflare）
```

---

## 6. API 參考

### 6.1 Worker REST Endpoints

| Method | Path | Auth | Response |
|--------|------|------|----------|
| GET | `/api/health` | None | `{"status":"ok","timestamp":...}` |
| GET | `/xiaozhi/v1/` | WebSocket Upgrade + Bearer token | 101 Switching Protocols |

### 6.2 外部 API 調用

#### Qwen LLM (DashScope)
```
POST https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions
Authorization: Bearer <QWEN_API_KEY>
Content-Type: application/json

{
  "model": "qwen-plus",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "max_tokens": 500,
  "temperature": 0.7
}
```

#### Workers AI STT (Nova-3)
```typescript
const result = await env.AI.run('@cf/deepgram/nova-3', {
  audio: { data: [...opusBytes], contentType: 'audio/opus' },
  detect_language: true,
});
// result.text → transcribed text
```

#### Workers AI TTS (Aura-1)
```typescript
const result = await env.AI.run('@cf/deepgram/aura-1', {
  text: llmResponse,
  encoding: 'linear16',
  container: 'wav',
  sample_rate: 16000,
});
// result → ReadableStream<Uint8Array> (WAV bytes)
```

### 6.3 Alibaba Cloud ASR (預備)

```typescript
// aliyun_asr.ts — REST API
const text = await aliyunAsrWithParams(audioData, {
  accessKeyId: '...',
  accessKeySecret: '...',
  appKey: '...',
}, {
  format: 'opus',
  sampleRate: 16000,
  language: 'cantonese',
});
```

---

## 7. MQTT IoT 協議

### 7.1 Topic 設計

```
funconnect/{school_id}/{device_id}/cmd/light       # 燈光控制
funconnect/{school_id}/{device_id}/cmd/motor       # 馬達控制
funconnect/{school_id}/{device_id}/cmd/relay       # 繼電器控制
funconnect/{school_id}/{device_id}/state/light     # 燈光狀態
funconnect/{school_id}/{device_id}/state/temp      # 溫度數據
funconnect/{school_id}/{device_id}/state/humidity  # 濕度數據
funconnect/{school_id}/broadcast                   # 全校廣播
```

### 7.2 MQTT 連線參數

| 參數 | 值 |
|------|-----|
| Broker URL | `mqtt://broker.emqx.io:1883` |
| Client ID | MAC address (lowercase hex) |
| QoS | 0 (at most once) |
| Keepalive | 60s |

### 7.3 Sensor 數據格式

```json
{
  "temp": 28,
  "humidity": 65,
  "timestamp": 1700000000
}
```

### 7.4 IoT 控制指令格式

```json
{
  "action": "on",
  "value": 255,
  "duration_ms": 5000
}
```

---

## 8. 編譯與部署

### 8.1 環境需求

| 工具 | 版本 | 安裝 |
|------|------|------|
| ESP-IDF | 5.5+ | `git clone --recursive https://github.com/espressif/esp-idf` |
| Python | 3.8+ | ESP-IDF installer 自帶 |
| Xtensa toolchain | esp32-elf | `./install.sh esp32` |
| Node.js | 18+ | `brew install node` |
| Wrangler | 4.x | `npm install -g wrangler` |

### 8.2 Firmware 編譯

```bash
cd cyberpi_firmware

# 1. 設定 ESP-IDF 環境
source ~/esp/esp-idf/export.sh

# 2. 設定 target（首次）
idf.py set-target esp32

# 3. 拉取依賴（esp-opus, websocket client）
idf.py reconfigure

# 4. 編譯
idf.py build

# 5. Flash（CyberPi 接 USB-C）
idf.py -p /dev/ttyUSB0 flash

# 6. Monitor serial output
idf.py -p /dev/ttyUSB0 monitor
```

### 8.3 完整部署檢查清單

- [ ] ESP-IDF v5.5 已安裝並 source export.sh
- [ ] `idf.py reconfigure` 成功拉取 78/esp-opus
- [ ] `idf.py build` 無錯誤
- [ ] `cyberpi_xiaozhi.bin` < 3.75MB (factory partition)
- [ ] Cloudflare: `npx wrangler deploy` 成功
- [ ] Worker health check: `curl https://<worker>/api/health` → 200 OK
- [ ] Qwen API key 有效：`curl` DashScope endpoint → 粵語回覆
- [ ] MQTT broker 可達：`mqtt://broker.emqx.io:1883`
- [ ] CyberPi USB-C 連接，`/dev/ttyUSB0` 出現
- [ ] Flash 完成，serial monitor 顯示 "FunConnect v1.0" + IP

---

## 9. 除錯指南

### 9.1 常見問題

| 問題 | 可能原因 | 解決方案 |
|------|---------|---------|
| `idf.py build` 找不到 opus.h | 78/esp-opus 未拉取 | `idf.py reconfigure` |
| `idf.py build` esp_mac.h not found | ESP-IDF v5.x API 變更 | 已修正：`#include "esp_mac.h"` |
| Binary too large for partition | Flash 溢出 | 檢查 `partitions.csv` factory size |
| WiFi 連接失敗 | SSID/password 錯誤 | 檢查 `main.c` 中 `WIFI_SSID`/`WIFI_PASS` |
| WebSocket 連不上 | Worker URL 錯誤或未部署 | 檢查 `WS_URL`，確認 `wrangler deploy` 成功 |
| 錄音無聲 | ES8218E 未初始化 | 檢查 I2C 通訊（I2C scan 輸出） |
| TTS 喇叭無聲 | Speaker I2S 衝突 | 檢查 `speaker_init/deinit` 時序 |
| LCD 不顯示 | SPI 衝突或 AW9523B 未初始化 | 檢查 RST/DC/BL pin 狀態 |
| STT 回覆空白 | 網絡延遲或 ASR 失敗 | 檢查 Worker tail log |
| MQTT 不連接 | Broker URL 錯誤 | 檢查 `MQTT_BROKER`，測試 `telnet broker.emqx.io 1883` |

### 9.2 Serial Monitor 關鍵日誌

```
I (1234) FunConnect: WiFi OK 192.168.1.100     ← WiFi 成功
I (1235) FunConnect: WS connected               ← WebSocket 連上
I (1236) FunConnect: Server hello: session=xxx  ← 握手完成
I (2000) AUDIO: Pipeline ready: enc=16kHz       ← Opus 就緒
I (2001) MQTT: Connected to broker              ← MQTT 連上
I (3000) FunConnect: STT: 你好                  ← 語音辨識成功
I (3001) FunConnect: LLM: 你好呀！              ← LLM 回覆
I (4000) AUDIO: TTS start                       ← 語音播放開始
```

### 9.3 Cloudflare Worker 日誌

```bash
npx wrangler tail
# 會顯示：
# Session started: uuid device=cyberpi-esp32
# Hello complete: session=uuid
# Processing audio: 12345 bytes Opus
# STT result: "transcribed text"
# TTS complete: 24000 samples
```

### 9.4 效能指標

| 階段 | 預期延遲 | 瓶頸 |
|------|---------|------|
| Opus encode (60ms frame) | <5ms | ESP32 CPU |
| WebSocket send | <50ms | WiFi |
| STT (Nova-3) | 200-500ms | Cloudflare AI |
| LLM (Qwen) | 500-2000ms | API latency |
| TTS (Aura-1) | 300-1000ms | Cloudflare AI |
| Opus decode (60ms frame) | <5ms | ESP32 CPU |
| **End-to-end** | **2-5 秒** | 主要係 LLM + TTS |

---

*文件版本：v1.0 | 2026-06-05 | FunConnect AIOT Platform*
