# 小芳智能體 FunConnect AIOT 平台

## 香港中小學 AI + IoT 教育解決方案

---

## 一、項目願景

「小芳智能體 FunConnect AIOT 平台」係一個專為香港中小學設計嘅 **AI + IoT 教育平台**，支援 **CyberPi、Micro:bit、Arduino** 三種主流教育硬件，Cloudflare 為雲端基礎設施，實現兩個核心目標：

1. **學 AI** — 學生透過動手編程同實體裝置，理解人工智能同物聯網嘅基本原理
2. **用 AI 學習** — AI 成為每個學生嘅個人導師，支援粵語/英文/普通話，結合課本知識庫（RAG）提供個人化學習體驗

### 三級硬件能力分層

| 等級 | 硬件 | 語音輸入 | 語音輸出 | 文字互動 | IoT 控制 | 適合 |
|------|------|---------|---------|---------|---------|------|
| **Tier 1** | CyberPi | 全語音 Opus | 全語音 TTS | LCD 顯示 | MQTT | 高小/初中/高中 |
| **Tier 2** | Arduino (WiFi) | WAV 錄音 | — | LCD/OLED | MQTT | 初中/高中 |
| **Tier 3** | Micro:bit | — | — | LED 矩陣/UART | MQTT | 初小/高小 |

**共同點**：所有硬件共用同一 Cloudflare 後端、EMQX.io MQTT broker、教師 dashboard、RAG 知識庫。

---

## 二、平台架構總覽

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         學校課室（多種硬件混合）                           │
│                                                                         │
│  Tier 1: CyberPi (語音互動)    Tier 2: Arduino (錄音+顯示)   Tier 3: Micro:bit (文字+IoT) │
│  ┌──────────┐  ┌──────────┐   ┌──────────┐  ┌──────────┐   ┌──────────┐  ┌──────────┐  │
│  │CyberPi#1 │  │CyberPi#2 │   │ Arduino#1│  │ Arduino#2│   │Microbit#1│  │Microbit#2│  │
│  │ WSS+MQTT │  │ WSS+MQTT │   │ MQTT+HTTP│  │ MQTT+HTTP│   │  MQTT    │  │  MQTT    │  │
│  └────┬─────┘  └────┬─────┘   └────┬─────┘  └────┬─────┘   └────┬─────┘  └────┬─────┘  │
│       └──────────────┼──────────────┴──────────────┼──────────────┴──────────────┘       │
│                      │              MQTT (IoT 控制 / 文字互動)              │              │
│                      │     燈 / 馬達 / 溫濕度 sensor / 風扇 / 繼電器         │              │
└──────────────────────┼────────────────────────────────────────────────────┘              │
                       │                                                                │
              ┌────────┴──────────────────────────┐                                     │
              │          Cloudflare 邊緣網絡        │                                     │
              │  ┌──────────────────────────────┐  │                                     │
              │  │ Worker：WSS + HTTP + REST API │  │                                     │
              │  │  ┌─────────────────────────┐ │  │                                     │
              │  │  │ Durable Object (per-dev) │ │  │                                     │
              │  │  │  ├─ Nova-3 STT (ASR)     │ │  │                                     │
              │  │  │  ├─ Vectorize RAG        │ │  │                                     │
              │  │  │  ├─ LLM (Llama/DeepSeek) │ │  │                                     │
              │  │  │  ├─ Aura-1 TTS           │ │  │                                     │
              │  │  │  └─ MCP → MQTT Bridge    │ │  │                                     │
              │  │  └─────────────────────────┘ │  │                                     │
              │  └──────────────────────────────┘  │                                     │
              │  ┌──────┐ ┌────┐ ┌───────┐ ┌───────┐│                                     │
              │  │Vectorize│ │ D1 │ │  R2   │ │ Pages ││                                     │
              │  │向量庫  │ │DB │ │物件存儲│ │教師後台││                                     │
              │  └──────┘ └────┘ └───────┘ └───────┘│                                     │
              │           │                         │                                     │
              │  ┌────────▼──────────┐              │                                     │
              │  │  MQTT Bridge ────▶ EMQX.io       │                                     │
              │  └───────────────────┘              │                                     │
              └─────────────────────────────────────┘                                     │
```

---

## 三、硬件配置

### 3.1 三種硬件平台對比

| 項目 | CyberPi | Micro:bit V2 | Arduino (Uno R4 WiFi) |
|------|---------|-------------|----------------------|
| **MCU** | ESP32 雙核 240MHz | nRF52833 64MHz | RA4M1 48MHz + ESP32-S3 |
| **RAM** | 520KB + 8MB PSRAM | 128KB | 256KB + ESP32-S3 |
| **Flash** | 4MB | 512KB | 256KB + 16MB |
| **WiFi** | 內置 2.4GHz | 需外置（BLE gateway） | 內置 2.4/5GHz |
| **藍牙** | BLE 4.2 | BLE 5.1 | BLE 5.0 |
| **顯示** | 128x128 彩色 LCD | 5x5 LED 矩陣 | 外接 LCD/OLED |
| **麥克風** | ES8218E MEMS | 內置 MEMS（低質） | 需外置 I2S mic |
| **喇叭** | 內置 DAC 喇叭 | 內置蜂鳴器 | 需外置 |
| **按鍵** | A/B + 搖桿 | A/B + 觸控 logo | 需外接 |
| **LED** | 4 顆 RGB | 25 顆單色 LED | 內置 1 顆 |
| **GPIO** | I2C (AW9523B) | 3x GPIO + I2C/SPI | 14x GPIO + I2C/SPI |
| **USB** | USB-C 供電+編程 | Micro USB | USB-C 供電+編程 |
| **價格** | ~HK$350 | ~HK$150 | ~HK$250 |
| **編程工具** | mBlock5 / Arduino IDE / ESP-IDF | MakeCode / MicroPython | Arduino IDE / PlatformIO |
| **語音互動** | 全 Opus 語音雙向 | ❌ | WAV 錄音上傳 |
| **適合年級** | 高小/初中/高中 | 初小/高小 | 初中/高中 |

### 3.2 Tier 1 — CyberPi（全語音 AI 互動）⭐ 主力

**通訊協議**：
- **WSS**（WebSocket Secure）→ 連接 Cloudflare Worker，行 xiaozhi-esp32 協議 v3
  - Opus 編碼語音雙向串流（16kHz 上行 / 24kHz 下行）
  - JSON 控制消息（hello / listen / stt / llm / tts / mcp）
- **MQTT** → 連接 EMQX.io
  - 接收 IoT 控制指令（燈 / 馬達 / 繼電器）
  - 發佈 sensor 數據（溫濕度）

**核心功能**：
- 按 A 掣錄音 → Opus 編碼 → WSS 上傳 → STT 辨識 → LLM 回覆 → TTS Opus 下載 → 喇叭播放
- 按 B 掣文字提問（無需錄音）
- LCD 顯示辨識文字 + LLM 回覆
- MCP IoT 控制（LED / 馬達 / sensor 讀取）

### 3.3 Tier 2 — Arduino（錄音 + 文字 AI 互動）

**通訊協議**：
- **MQTT** → 連接 EMQX.io（文字互動 + IoT 控制）
- **HTTP POST** → Cloudflare Worker REST API（上傳 WAV 錄音、獲取文字回覆）

**核心功能**：
- 按掣錄音 → WAV → HTTP POST → STT 辨識 → LLM 回覆（文字） → LCD 顯示
- MQTT 文字提問（用 UART 終端機 / 手機藍牙輸入）
- IoT 控制（GPIO 燈 / 馬達 / 繼電器 / sensor）
- OLED/LCD 顯示回覆文字

**推薦型號**：Arduino Uno R4 WiFi（內置 ESP32-S3 WiFi + BLE）

**MQTT 文字互動流程**：
```
Arduino → MQTT publish "funconnect/school01/arduino01/text" → "光合作用係咩？"
EMQX.io → Cloudflare Worker subscribe → LLM 生成回覆
Worker → MQTT publish "funconnect/school01/arduino01/reply" → "光合作用係..."
Arduino subscribe → OLED 顯示回覆
```

### 3.4 Tier 3 — Micro:bit（純文字 AI + IoT 控制）

**通訊協議**：
- **MQTT** → 連接 EMQX.io（必須透過外部 gateway，因 Micro:bit 無 WiFi）
- **BLE ↔ WiFi Gateway**：Micro:bit BLE UART → Raspberry Pi / ESP32 gateway → MQTT

**核心功能**：
- 按 A/B 掣觸發預設問題 → MQTT → LLM 文字回覆 → LED 矩陣顯示
- IoT 控制（GPIO 燈 / 馬達 / sensor）
- 溫濕度 sensor 讀取 + 上傳
- LED 矩陣顯示簡單 emoji / 文字

**BLE Gateway 方案**：
```
Micro:bit ←→ BLE UART ←→ Raspberry Pi Zero W ($100) ←→ WiFi MQTT → EMQX.io
```
每間課室只需 1 部 Pi Zero W 做 gateway，可同時服務全班 Micro:bit。

**MQTT 文字互動**：
```
Micro:bit 按 A → BLE UART → Pi Gateway → MQTT → Cloudflare Worker → LLM
Cloudflare Worker → MQTT → Pi Gateway → BLE UART → Micro:bit LED scroll text
```

### 3.5 共用 IoT 模組（三種硬件通用）

| 模組 | 用途 | CyberPi | Micro:bit | Arduino |
|------|------|---------|-----------|---------|
| LED 燈帶 | 燈光控制 | AW9523B | GPIO PWM | GPIO PWM |
| 伺服馬達 SG90 | 風扇/窗簾 | GPIO PWM | GPIO PWM | GPIO PWM |
| DHT22 | 溫濕度 sensor | I2C/GPIO | GPIO | GPIO |
| 繼電器模組 | 開關電器 | GPIO | GPIO | GPIO |
| 超聲波 HC-SR04 | 距離測量 | GPIO | GPIO | GPIO |
| mBuild 模組 | Makeblock 擴展 | I2C | — | — |
| OLED SSD1306 | 128x64 顯示 | （已有 LCD） | — | I2C |

### 3.6 各硬件通訊協議總覽

| 硬件 | AI 語音通道 | AI 文字通道 | IoT 控制通道 |
|------|-----------|-----------|-------------|
| **CyberPi** | WSS (Opus) | WSS (JSON) | MQTT |
| **Arduino** | HTTP POST (WAV) | MQTT | MQTT |
| **Micro:bit** | — | MQTT (via BLE GW) | MQTT (via BLE GW) |

---

## 四、八個核心用法與用例

### 用例 1：AI 課堂問答（全硬件適用）

**場景**：常識課教緊「香港嘅水資源」，學生有唔明可以即時問 AI。

| 硬件 | 操作方式 | 體驗 |
|------|---------|------|
| CyberPi | 㩒 A 掣 → 錄音「香港飲用水喺邊度嚟㗎？」→ 聽答案 | 語音一問一答 |
| Arduino | 㩒掣 → 錄音 → LCD 顯示答案 | 錄音問、睇字答 |
| Micro:bit | 㩒 A+B → 發預設問題 → LED 走字 | 㩒掣問、走字答 |

**後台流程**：ASR → RAG 檢索水務署教材 → LLM 用粵語解釋東江水同本地水庫 → TTS/文字回覆

---

### 用例 2：智能溫室監控（IoT + AI 分析）

**場景**：學生建立一個迷你溫室，用 sensor 監測溫度濕度，AI 自動分析同建議。

```
硬件：CyberPi / Arduino + DHT22 + 風扇 + LED 燈
MQTT Topic：
  funconnect/school01/groupA/state/temp      → 28.5
  funconnect/school01/groupA/state/humidity   → 65.2
  funconnect/school01/groupA/cmd/fan          → ON  （AI 決定開風扇）
  funconnect/school01/groupA/cmd/light        → OFF
```

**功能**：
- 每 5 分鐘自動上報溫濕度
- 溫度 > 28°C → AI 自動開風扇 + 提示「溫度偏高，已開啟通風」
- 學生問「今朝溫度變化係點？」→ AI 查返 D1 記錄 → 回答走勢
- 歷史數據可視化（Cloudflare Pages chart）

---

### 用例 3：英文口語練習（Tier 1 CyberPi）

**場景**：英文堂練 oral，AI 做對話夥伴，幫學生糾正發音同文法。

```
學生撳 A：「What is your favorite hobby?」
    ↓ ASR (Nova-3, language=en)
    ↓ LLM (system prompt: 你係英文口語教練，用適合小五程度嘅英文回應)
    ↓ TTS (Aura-1, English voice)
CyberPi 喇叭：「I enjoy reading books! What about you?」
```

**功能**：
- 三種難度（小學 P4-P6 / 初中 S1-S3 / 高中 DSE）
- 糾正模式：LLM detect 文法錯誤 → 溫和提示「Try saying 'I went' instead of 'I go'」
- 發音評分：ASR confidence score → 鼓勵學生
- 教師 dashboard 睇到學生練習記錄

---

### 用例 4：校本 FAQ 客服機器人

**場景**：將學校特定資訊（校規、時間表、活動日期、考試範圍）導入 RAG，變成 24/7 校務助理。

**RAG 知識來源**：
| 類型 | 例子 |
|------|------|
| 校規 | 校服要求、請假程序、遲到處理 |
| 時間表 | 上課時間、午膳安排、課外活動 |
| 考試 | 考試範圍、日期、規矩 |
| 活動 | 運動會、開放日、家長日 |

**學生問**：「聽日使唔使著體育服？」
**AI 答**：「聽日係星期三，根據校曆表，你班 4B 有體育堂，要著體育服㗎。」

---

### 用例 5：課室 IoT 智能控制（跨硬件協作）

**場景**：一組學生用 CyberPi 語音控制，另一組用 Micro:bit 做 sensor node，一齊打造智能課室。

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  CyberPi (主控)  │     │  Micro:bit (sensor)│   │  Arduino (執行) │
│  語音指令輸入     │     │  溫濕度 + 光線 sensor│   │  風扇 + LED 燈   │
│  「開燈」        │     │  定時上報數據       │   │  MQTT 接收指令   │
└────┬────────────┘     └────────┬────────┘     └────────┬────────┘
     │          MQTT (EMQX.io)          │                  │
     └──────────────┼──────────────────┼──────────────────┘
                    │                  │
              ┌─────▼──────────────────▼──────────┐
              │  Cloudflare Worker                │
              │  ├─ 接收語音 → 理解意圖              │
              │  ├─ 分析 sensor 數據                │
              │  ├─ 自動化規則引擎                   │
              │  └─ 發佈 IoT 指令                   │
              └────────────────────────────────────┘
```

**自動化規則**：
- 光線 < 200 lux → 自動開燈
- 溫度 > 28°C → 自動開風扇
- 濕度 > 80% → 提示「可能就嚟落雨，記得閂窗」

---

### 用例 6：跨學科專題研習（STEM Project）

**場景**：高中 DSE ICT/SBA 專題，學生由零開始設計一個 AIOT 系統。

**專題題目例子**：

| 題目 | 硬件 | AI 功能 | IoT 功能 |
|------|------|---------|---------|
| 智能老人家居助手 | CyberPi | 語音對話、食藥提醒 | 溫濕度、跌倒 sensor |
| 校園能源監控 | Arduino | 用電量分析預測 | 電流 sensor、繼電器 |
| 智能排隊系統 | Micro:bit | 排隊時間預測 | 超聲波 sensor 偵測人數 |
| AI 垃圾分類 | CyberPi + Arduino | 影相辨識垃圾種類 | 伺服摩打開蓋 |
| 智能魚菜共生 | Arduino | AI 分析水質數據 | pH/TDS sensor、水泵 |

**學生學到嘅技能**：
- MQTT 通訊協議設計
- Cloudflare Worker API 開發（JavaScript/TypeScript）
- RAG 知識庫建立（Vectorize + Embedding）
- IoT sensor 數據採集同分析
- 系統整合測試

---

### 用例 7：教師 AI 備課助手

**場景**：教師專用功能（非學生），協助備課同出題。

**功能**：
- **教案生成**：「幫我設計一個 40 分鐘嘅小四常識課，主題係水的循環，要有實驗環節」
- **出卷輔助**：「根據今次考試範圍，出 10 條多項選擇題，程度係中三數學科」
- **差異化教學**：「呢條題目對於 SEN 學生太難，幫我改寫一個簡單版本」
- **跨學科連接**：「光合作用呢個課題，有咩數學元素可以連接？」

**技術**：LLM prompt engineering + RAG 教育局課程指引 + 校本教材

**權限**：教師帳號功能，學生裝置不可用。

---

### 用例 8：家長日 AI 展示 + 親子工作坊

**場景**：學校開放日/家長日，展示學生 AIOT 作品，設親子互動體驗區。

**展示活動設計**：

| 活動 | 硬件 | 體驗 |
|------|------|------|
| 「同 AI 鬥快答問題」 | CyberPi | 家長提問 → AI 回答 vs 學生回答，鬥快鬥準 |
| 「用把聲控制世界」 | CyberPi + IoT | 講「紅色」→ LED 變紅 / 講「大風啲」→ 風扇加速 |
| 「親子 AI 繪本」 | CyberPi + Micro:bit | 家長講故事開頭 → AI 續寫 → Micro:bit 顯示插圖 |
| 「我嘅第一個 IoT 裝置」 | Micro:bit | 15 分鐘工作坊，砌一個溫度警報器 |

---

## 五、「學 AI」— AI 教育課程體系

### 5.1 課程分級與硬件配對

```
小學高年級（P4-P6）          初中（S1-S3）              高中（S4-S6）
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ ● 什麼是 AI      │    │ ● ASR 語音辨識   │    │ ● Transformer   │
│ ● 圖形化編程     │    │ ● NLP 文字處理   │    │ ● Embedding     │
│ ● IoT 概念       │    │ ● LLM 原理初探   │    │ ● RAG 架構      │
│ ● 感應器與輸出    │    │ ● MQTT 協議      │    │ ● Vector DB     │
│ ● 錄音與播放     │    │ ● MCP 工具調用   │    │ ● API 設計      │
│ ● LED 動畫       │    │ ● 數據可視化     │    │ ● TypeScript    │
│                  │    │                 │    │ ● Cloudflare Dev │
│ 硬件：Micro:bit  │    │ 硬件：CyberPi /  │    │ 硬件：CyberPi / │
│ 　　　CyberPi    │    │ 　　　Arduino    │    │ 　　　Arduino   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### 5.2 課程模組詳情

#### 模組 A：AI 基礎概念（小學）— Micro:bit / CyberPi
- **A1** — 什麼是人工智能：用 CyberPi 錄音播返出嚟、Micro:bit LED 顯示笑面
- **A2** — 機器點樣睇嘢：CyberPi LCD 顯示 emoji / Micro:bit LED 動畫
- **A3** — IoT 智能燈：MakeCode/mBlock5 拖積木控制 LED 顏色同亮度
- **A4** — 智能風扇：讀取溫濕度 → 溫度高過 28°C 自動開風扇（sensor + 摩打）
- **A5** — AI 猜拳遊戲：Micro:bit 隨機出拳 vs 學生，學乜嘢係「機器決策」

#### 模組 B：AI 通訊協議（初中）— CyberPi / Arduino
- **B1** — 語音辨識 ASR：CyberPi 錄音 → Cloudflare 辨識 → LCD 顯示中文
- **B2** — 文字 AI 互動：Arduino 透過 MQTT 同 AI 對話
- **B3** — MQTT 通訊：多部裝置透過 EMQX.io 互相 send message
- **B4** — 智能教室：跨硬件協作（CyberPi 語音控制 + Arduino 執行）
- **B5** — 數據可視化：溫濕度 sensor 數據 → Cloudflare Pages 圖表

#### 模組 C：AI 系統設計（高中）— CyberPi / Arduino + Cloudflare
- **C1** — RAG 原理與實作：上載筆記 → Vectorize 建立向量庫 → 檢索回答
- **C2** — Embedding 與向量空間：Workers AI 將文字轉成數字向量
- **C3** — API 設計與測試：用 TypeScript 寫 Cloudflare Worker
- **C4** — MCP 工具調用：LLM 透過 MCP 控制 IoT 裝置
- **C5** — Capstone 專題：設計一個校園 AIOT 系統（詳見用例 6）

### 5.3 開發工具鏈（按硬件）

| 硬件 | 初小/高小 | 初中 | 高中 |
|------|----------|------|------|
| **Micro:bit** | MakeCode 積木 | MakeCode + MicroPython | MicroPython |
| **CyberPi** | mBlock5 積木 | mBlock5 Python / Arduino IDE | ESP-IDF C / MicroPython |
| **Arduino** | — | Arduino IDE C++ | PlatformIO / ESP-IDF |
| **Cloudflare** | — | — | Wrangler CLI / TypeScript |

---

## 五、「用 AI 來學習」— AI 輔助教學功能

### 5.1 RAG 知識庫引擎

#### 知識來源
| 類型 | 內容 | 格式 | 儲存 |
|------|------|------|------|
| 課本 | 各科教科書（經出版社授權） | PDF / TXT | R2 |
| 筆記 | 教師備課筆記 | Markdown | D1 |
| FAQ | 學校常見問題（校規、活動） | JSON | D1 |
| 試題庫 | 歷屆試卷（可選） | PDF | R2 |

#### RAG 流程

```
用戶語音問題
    │
    ▼
ASR (Nova-3 / Whisper) ──▶ 文字查詢
    │
    ├──▶ Embedding Model (bge-base-zh)
    │         │
    │         ▼
    │    Vectorize 向量搜尋 (topK=3-5)
    │         │
    │         ▼
    │    取出最相關文檔段落
    │         │
    └─────────┼──────────┐
              │          │
              ▼          ▼
        檢索結果    原始問題
              │          │
              └────┬─────┘
                   ▼
         ┌─────────────────────┐
         │ RAG Prompt Template  │
         │                      │
         │ 你係香港中小學AI助教。 │
         │ 請根據以下資料回答：   │
         │                      │
         │ 【參考資料】          │
         │ {retrieved_context}   │
         │                      │
         │ 【學生問題】          │
         │ {student_question}    │
         │                      │
         │ 要求：               │
         │ - 用粵語/繁體中文回答  │
         │ - 適合{grade}程度    │
         │ - 可引用參考資料章節   │
         │ - 如資料不足請誠實說明 │
         └─────────────────────┘
                   │
                   ▼
            LLM 生成回答
                   │
                   ▼
            TTS 語音輸出 (Aura-1)
```

### 5.2 學科應用場景

| 學科 | 場景 | 例子 |
|------|------|------|
| **中文** | 古詩解釋、成語學習 | 「解釋靜夜思嘅意思」→ RAG 課文 + 粵語朗讀 |
| **英文** | 口語練習、文法糾正 | 「How to use past tense?」→ 英文回答 + 例句 |
| **數學** | 解題步驟引導 | 「點樣計三角形面積？」→ 逐步引導，不直接俾答案 |
| **科學** | 實驗步驟、原理查詢 | 「光合作用點樣運作？」→ RAG 課本圖表 + 解釋 |
| **常識/通識** | 社會議題、時事討論 | 「香港水資源點樣管理？」→ 多角度資料整合 |
| **資訊科技** | 編程概念、除錯協助 | 「loop 同 if 有咩分別？」→ 用 CyberPi 例子解釋 |

### 5.3 個人化學習路徑

- 每學生一個 profile（D1 記錄）
- 追蹤提問歷史 → 分析弱項 → 推薦練習
- 教師 dashboard 睇到全班學生嘅學習進度

---

## 六、內容安全與學童保護（關鍵）

### 6.1 多層安全過濾

```
學生語音 → ASR 文字
              │
    ┌─────────▼─────────┐
    │ Layer 1: 關鍵詞過濾 │ ← 屏蔽暴力/色情/自殘關鍵詞
    └─────────┬─────────┘
              │
    ┌─────────▼─────────┐
    │ Layer 2: LLM 分類  │ ← 判斷意圖（學術/閒聊/違規）
    └─────────┬─────────┘
              │
    ┌─────────▼─────────┐
    │ Layer 3: Prompt    │ ← 系統 prompt 約束只回答學術問題
    │ Guardrails         │
    └─────────┬─────────┘
              │
    ┌─────────▼─────────┐
    │ Layer 4: 輸出過濾   │ ← 檢查 LLM 回覆內容
    └─────────┬─────────┘
              │
              ▼
        安全回覆 / 拒絕 + 記錄
```

### 6.2 合規要求

| 要求 | 措施 |
|------|------|
| 個人資料私隱 | 不儲存學生語音原檔；只保留文字對話記錄 |
| 家長同意 | 學校收集家長同意書 |
| 數據本地化 | 可選用 Cloudflare 香港節點 |
| 教師監督 | 教師 dashboard 可查看全班對話記錄 |
| 使用時間限制 | 每 session 限時、每日上限 |

---

## 八、教師管理後台（Cloudflare Pages）

### 7.1 功能模組

| 模組 | 功能 |
|------|------|
| **班級管理** | 建立班級、加入學生 device |
| **內容管理** | 上載課本 PDF、編輯 FAQ、管理 RAG 知識庫 |
| **對話監控** | 即時查看學生提問、標記問題對話 |
| **使用分析** | 熱門問題、使用時段、學生參與度 |
| **權限設定** | 設定各級別可使用嘅功能範圍 |
| **系統設定** | API key 管理、MQTT topic 配置 |

### 7.2 技術棧

- **前端**：React + Tailwind CSS
- **部署**：Cloudflare Pages
- **API**：Cloudflare Worker REST endpoints
- **Auth**：Cloudflare Access (SSO) / 學校 Google Workspace 整合

---

## 九、IoT 控制協議（MQTT）

### 8.1 主題 (Topic) 設計

```
funconnect/{school_id}/{device_id}/cmd/light       # 燈光控制指令
funconnect/{school_id}/{device_id}/cmd/motor       # 馬達控制指令
funconnect/{school_id}/{device_id}/cmd/relay       # 繼電器控制指令
funconnect/{school_id}/{device_id}/state/light     # 燈光狀態回報
funconnect/{school_id}/{device_id}/state/temp      # 溫度讀數回報
funconnect/{school_id}/{device_id}/state/humidity  # 濕度讀數回報
funconnect/{school_id}/broadcast                    # 全校廣播
```

### 8.2 MQTT Broker

選用 **EMQX.io**（託管 MQTT broker）：
- 支援 WebSocket MQTT（ESP32 可直接連）
- 自帶 dashboard 監控
- 免費額度足夠學校使用
- Cloudflare Worker 做 bridge（publish IoT 指令、subscribe sensor 數據）

### 8.3 MCP ↔ MQTT 橋接

```
LLM 決定「開燈」
    │
    ▼
Worker send MCP: {"method":"tools/call","name":"light.turn_on"}
    │
    ▼
ESP32 收到 MCP 指令
    │
    ├──▶ mqtt_publish("funconnect/school01/cyberpi01/state/light", "ON")  [狀態回報]
    │
    └──▶ led_set_rgb(0, 255, 255, 255)  [實際控制]
```

---

## 十、多裝置管理（課室場景）

### 9.1 挑戰

- 一班 30-40 部 CyberPi 同時 WiFi 連接
- 同時發聲會互相干擾（mic 收到其他機嘅喇叭聲）
- 頻寬管理

### 9.2 解決方案

| 問題 | 方案 |
|------|------|
| WiFi congestion | 學校級 AP（如 UniFi），2.4GHz 專用 SSID |
| 聲音干擾 | 按鍵觸發（push-to-talk），非 always-on |
| 同時請求 | Cloudflare Durable Object per-device，天然隔離 |
| Device ID 管理 | 教師 dashboard 綁定 MAC address → 學生姓名 |
| 批量更新 | OTA firmware update via Cloudflare R2 |

---

## 十、部署架構

### 10.1 Cloudflare 資源清單

| 服務 | 用途 | 定價 |
|------|------|------|
| **Workers** ($5/mo) | WebSocket 入口 + REST API | 含 10M 請求/mo |
| **Durable Objects** | 每 device 一個有狀態會話 | 含在 Workers paid |
| **Workers AI** | STT + LLM + TTS + Embedding | 按用量計費 |
| **Vectorize** | RAG 向量資料庫 | $0.01/百萬查詢 |
| **D1** | 用戶/內容/記錄數據庫 | $0.75/百萬讀取 |
| **R2** | 課本 PDF、教材存儲 | $0.015/GB/mo |
| **Pages** | 教師管理後台 | 免費額度 |
| **Access** (可選) | SSO 身份驗證 | 免費額度 |

### 10.2 學校端部署

```
課室配置（每間）：
├── Tier 1：10-15 部 CyberPi（高小/初中用）
├── Tier 2：10-15 部 Arduino Uno R4 WiFi（初中/高中用）
├── Tier 3：10-15 部 Micro:bit V2（初小/高小用）
├── 1 部 Raspberry Pi Zero W（Micro:bit BLE → WiFi gateway）
├── 1 個 WiFi AP（2.4GHz）
├── IoT 裝置（燈、馬達、溫濕度 sensor、繼電器）
└── 1 部教師電腦（開 dashboard）

學校伺服器機房：
├── 無需伺服器（全 Cloudflare 雲端）
└── 只需穩定上網連線（100Mbps+）
```

### 10.3 實施路線圖

```
Phase 1（1-2 個月）：核心韌體 + Cloudflare 後端
├── CyberPi firmware：Opus 語音 + xiaozhi WSS 協議 + MQTT
├── Arduino firmware：MQTT + HTTP WAV 上傳
├── Micro:bit firmware：BLE UART + MQTT via Pi Gateway
├── Cloudflare Worker + DO：WebSocket + HTTP + ASR + LLM + TTS
└── 單機測試通過（三種硬件）

Phase 2（1 個月）：IoT 整合 + RAG
├── MQTT 橋接（EMQX.io）
├── IoT 控制（燈/馬達/溫濕度）— 三種硬件通用
├── Vectorize RAG 知識庫
└── 課本內容導入

Phase 3（1 個月）：多裝置 + 教師後台 + 安全
├── 教師 dashboard（Pages）
├── 多硬件裝置管理（Device Registry in D1）
├── BLE Gateway 部署方案
├── 內容安全過濾（4 層）
└── 課室壓力測試（30 部混合硬件同時）

Phase 4（1 個月）：學校試點
├── 1-2 間合作學校試行
├── 收集師生反饋
├── 調整優化
└── 課程內容製作

Phase 5（持續）：全港推廣
├── 教師培訓工作坊
├── 教材套件發佈（分 Micro:bit / CyberPi / Arduino 版本）
├── 教育展參展
└── 持續支援
```

---

## 十一、成本估算

### 每間學校每年

| 項目 | 估算成本 |
|------|---------|
| Cloudflare Workers ($5/mo) | HK$ 470 |
| Workers AI (STT + LLM + TTS, 每日 1000 次) | HK$ 800 |
| Vectorize + D1 + R2 | HK$ 300 |
| EMQX.io (免費額度通常夠用) | HK$ 0 |
| **雲端總計/年** | **~HK$ 1,570** |
| | |
| **硬件組合方案 A（混合硬件班，30 部）** | |
| CyberPi x10 (~$350/部) | HK$ 3,500 |
| Arduino Uno R4 WiFi x10 (~$250/部) | HK$ 2,500 |
| Micro:bit V2 x10 (~$150/部) | HK$ 1,500 |
| Raspberry Pi Zero W x1 (BLE Gateway) | HK$ 100 |
| IoT 配件包 x5（燈/馬達/sensor/繼電器） | HK$ 1,500 |
| **方案 A 硬件總計** | **~HK$ 9,100** |
| | |
| **硬件組合方案 B（純 CyberPi 班，40 部）** | |
| CyberPi x40 (~$350/部) | HK$ 14,000 |
| IoT 配件包 x10 | HK$ 3,000 |
| **方案 B 硬件總計** | **~HK$ 17,000** |

---

## 十二、競爭優勢

| 特點 | 小芳 FunConnect | 其他方案 |
|------|----------------|---------|
| 粵語支援 | 原生支援（ASR + TTS） | 多數只支援普通話/英文 |
| 香港課程對齊 | 按教育局指引設計 | 通用內容 |
| 硬件支援 | CyberPi + Micro:bit + Arduino | 單一硬件 |
| 分級能力 | Tier 1/2/3 按年級選硬件 | 無分級 |
| 硬件成本 | 三種硬件任揀，$150起 | 同類方案 $500-1000+ |
| 雲端成本 | ~$1,570/年全校 | 部份方案 $10,000+/年 |
| 私隱安全 | Cloudflare 邊緣運算，可選香港節點 | 部份方案數據出境 |
| 開放平台 | 開源韌體 + API + MQTT 標準 | 多數封閉系統 |
| 學AI + 用AI | 雙軌並行 | 多數只做其中一個 |
| 跨硬件協作 | MQTT 統一，CyberPi+Micro:bit+Arduino 互通 | 無法混合使用 |

---

## 十三、下一步行動

1. **完成核心韌體開發**（進行中）
   - `opus_codec` ✅
   - `xiaozhi_protocol`（進行中）
   - `audio_pipeline`
   - `main.c` 狀態機重寫

2. **建立 Cloudflare 後端**
   - Worker + Durable Object
   - Workers AI 整合
   - MQTT bridge（EMQX.io）

3. **RAG 知識庫引擎**
   - Vectorize 設定
   - 課本內容處理 pipeline
   - Prompt template 設計

4. **尋找試點學校**
   - 聯絡 IT 科主任
   - 校本課程整合
   - 教師培訓

---

*文件版本：v0.1 | 2026-06-04 | 小芳智能體 FunConnect AIOT 平台*
