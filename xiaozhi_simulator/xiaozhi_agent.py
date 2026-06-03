#!/usr/bin/env python3
"""
小智智能體模擬器 | XiaoZhi AI Agent Simulator
===============================================
模擬基於 ESP32 的小智 AI 聊天機器人，支持：
- WebSocket/MQTT 協議模擬 (xiaozhi-esp32 protocol)
- MCP 設備控制
- 自然中文對話
- 終端 UI + JPG 頭像顯示
- 情緒表情 / WiFi / 電池狀態
- 設備狀態機 (Idle → Connecting → Listening → Speaking)

CyberPi-style: 簡單、可視化、教育用途的 Python 模擬。
"""

import asyncio
import json
import os
import random
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

# WebSocket 客戶端 (可選)
try:
    import websockets

    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

# ── Terminal UI ──────────────────────────────────────────
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout
from rich.live import Live
from rich.align import Align
from rich import box
from rich.style import Style

console = Console()

# ═══════════════════════════════════════════════════════════
# Avatar ASCII Art (終端顯示用)
# ═══════════════════════════════════════════════════════════

XIAOZHI_ASCII = r"""
        ╭──────────────────╮
        │   ▄▄▄█████▄▄▄   │
        │  ██████████████  │
        │  ███  ●  ●  ███  │
        │  ███   ◡   ███   │
        │  ██████████████  │
        │   ▀▀█████████▀   │
        │     ████████     │
        │    ██  ♥  ██     │
        ╰──────────────────╯
           🤖 小智 AI v2.2.6
"""

XIAOZHI_EMOTIONS = {
    "happy": r"""
        ╭──────────────────╮
        │   ▄▄▄█████▄▄▄   │
        │  ██████████████  │
        │  ███  ◠  ◠  ███  │
        │  ███   ▽   ███   │
        │  ██████████████  │
        │   ▀▀█████████▀   │
        │     ████████     │
        │    ██  ♥  ██     │
        ╰──────────────────╯
        😊 開心 Happy
    """,
    "thinking": r"""
        ╭──────────────────╮
        │   ▄▄▄█████▄▄▄   │
        │  ██████████████  │
        │  ███  ◉  ●  ███  │
        │  ███   ~   ███   │
        │  ██████████████  │
        │   ▀▀█████████▀   │
        │     ████████     │
        │    ██  ?  ██     │
        ╰──────────────────╯
        🤔 思考中 Thinking
    """,
    "surprised": r"""
        ╭──────────────────╮
        │   ▄▄▄█████▄▄▄   │
        │  ██████████████  │
        │  ███  ◉  ◉  ███  │
        │  ███   ○   ███   │
        │  ██████████████  │
        │   ▀▀█████████▀   │
        │     ████████     │
        │    ██  !  ██     │
        ╰──────────────────╯
        😲 驚訝 Surprised
    """,
    "sad": r"""
        ╭──────────────────╮
        │   ▄▄▄█████▄▄▄   │
        │  ██████████████  │
        │  ███  ◡  ◡  ███  │
        │  ███   △   ███   │
        │  ██████████████  │
        │   ▀▀█████████▀   │
        │     ████████     │
        │    ██  💧 ██     │
        ╰──────────────────╯
        😢 難過 Sad
    """,
    "neutral": r"""
        ╭──────────────────╮
        │   ▄▄▄█████▄▄▄   │
        │  ██████████████  │
        │  ███  ●  ●  ███  │
        │  ███   ─   ███   │
        │  ██████████████  │
        │   ▀▀█████████▀   │
        │     ████████     │
        │    ██  ♥  ██     │
        ╰──────────────────╯
        😐 平靜 Neutral
    """,
    "love": r"""
        ╭──────────────────╮
        │   ▄▄▄█████▄▄▄   │
        │  ██████████████  │
        │  ███  ♥  ♥  ███  │
        │  ███   ♡   ███   │
        │  ██████████████  │
        │   ▀▀█████████▀   │
        │     ████████     │
        │    ██  ♥  ██     │
        ╰──────────────────╯
        😍 喜歡 Love
    """,
}

# ═══════════════════════════════════════════════════════════
# State Machine
# ═══════════════════════════════════════════════════════════


class DeviceState(Enum):
    UNKNOWN = "未知"
    STARTING = "啟動中"
    WIFI_CONFIGURING = "WiFi 配置中"
    IDLE = "空閒"
    CONNECTING = "連接中"
    LISTENING = "聆聽中"
    SPEAKING = "說話中"
    UPGRADING = "升級中"
    ACTIVATING = "激活中"
    FATAL_ERROR = "致命錯誤"


# ═══════════════════════════════════════════════════════════
# MCP Tools Simulation
# ═══════════════════════════════════════════════════════════

MCP_TOOLS = {
    "self.led.set_brightness": {
        "description": "設置 LED 亮度",
        "params": {"brightness": "0-255"},
    },
    "self.led.set_rgb": {
        "description": "設置 LED 顏色",
        "params": {"r": "0-255", "g": "0-255", "b": "0-255"},
    },
    "self.speaker.set_volume": {
        "description": "設置音量",
        "params": {"volume": "0-100"},
    },
    "self.servo.set_angle": {
        "description": "控制舵機角度",
        "params": {"servo_id": "舵機編號", "angle": "0-180"},
    },
    "self.gpio.set_level": {
        "description": "設置 GPIO 電平",
        "params": {"pin": "引腳號", "level": "0 or 1"},
    },
    "self.display.show_text": {
        "description": "顯示文字",
        "params": {"text": "顯示內容", "x": "x坐標", "y": "y坐標"},
    },
    "self.display.show_emotion": {
        "description": "顯示表情",
        "params": {"emotion": "happy/sad/thinking/surprised/neutral/love"},
    },
    "self.camera.capture": {
        "description": "拍照",
        "params": {},
    },
    "self.system.reboot": {
        "description": "重啟設備",
        "params": {},
    },
    "self.wifi.scan": {
        "description": "掃描 WiFi",
        "params": {},
    },
}

# ═══════════════════════════════════════════════════════════
# Conversation Engine
# ═══════════════════════════════════════════════════════════


class ConversationEngine:
    """模擬小智的自然語言對話引擎 (基於 Qwen/DeepSeek 大模型風格)"""

    def __init__(self):
        self.context = []
        self.personality = "友好、活潑、樂於助人的小智 AI 助手"

    def generate_response(self, user_input: str) -> dict:
        """生成模擬的 LLM 回應。在真實場景中這裡會調用 Qwen/DeepSeek API。"""
        user_input_lower = user_input.lower().strip()

        # 記錄上下文
        self.context.append({"role": "user", "content": user_input})
        if len(self.context) > 20:
            self.context = self.context[-20:]

        # ── 智能回應規則 ──
        response, emotion, mcp_action = self._match_response(user_input_lower, user_input)

        self.context.append({"role": "assistant", "content": response})

        result = {
            "text": response,
            "emotion": emotion,
            "stt_text": user_input,
        }
        if mcp_action:
            result["mcp_action"] = mcp_action
        return result

    def _match_response(self, lower: str, original: str) -> tuple:
        """匹配回應規則。"""
        # 問候
        if any(w in lower for w in ["你好", "嗨", "hello", "hi", "嘿", "哈囉"]):
            greetings = [
                "你好呀！我是小智，你的 AI 聊天夥伴 🤖✨ 今天有什麼我可以幫你的嗎？",
                "嗨～小智在線！有什麼想聊的，或者需要我幫忙的嗎？😊",
                "哈囉！我是小智 AI 助手，隨時為你服務！說說看你想做什麼吧～",
            ]
            return random.choice(greetings), "happy", None

        # 自我介紹
        if any(w in lower for w in ["你是誰", "你叫什麼", "介紹自己", "你是什麼"]):
            return (
                "我是小智（XiaoZhi）！🌟 一個基於 ESP32 開源硬件平台打造的 AI 聊天機器人。\n\n"
                "我運行的固件版本是 v2.2.6，支持：\n"
                "• 🎤 語音喚醒與識別 (ASR)\n"
                "• 🧠 大語言模型對話 (Qwen/DeepSeek)\n"
                "• 🔊 文字轉語音 (TTS)\n"
                "• 🔧 MCP 協議設備控制\n"
                "• 📡 WiFi / 4G 聯網\n"
                "• 😊 表情顯示與多語言支持\n\n"
                "簡單來說，我是一個裝在小小晶片裡的 AI 夥伴！",
                "happy",
                None,
            )

        # 天氣
        if any(w in lower for w in ["天氣", "溫度", "下雨"]):
            weathers = [
                ("今天天氣晴朗，適合出門走走 ☀️ 溫度約 25°C，微風～", "happy"),
                ("目前多雲時陰，氣溫 22°C，建議帶把傘以備不時之需 🌥️", "neutral"),
                ("外面正在下雨呢 🌧️ 溫度 18°C，出門記得帶傘喔！", "sad"),
            ]
            resp, emo = random.choice(weathers)
            return resp, emo, None

        # 時間
        if any(w in lower for w in ["時間", "幾點", "日期", "今天星期"]):
            now = datetime.now()
            weekdays = ["一", "二", "三", "四", "五", "六", "日"]
            wd = weekdays[now.weekday()]
            return (
                f"現在是 {now.year}年{now.month}月{now.day}日，星期{wd}，"
                f"{now.hour}點{now.minute:02d}分 🕐",
                "neutral",
                None,
            )

        # 講笑話
        if any(w in lower for w in ["笑話", "搞笑", "幽默", "funny"]):
            jokes = [
                ("為什麼程式設計師總是分不清萬聖節和聖誕節？\n因為 Oct 31 = Dec 25！🤣", "happy"),
                ("小明問小智：「1+1 等於多少？」\n小智說：「在二進制世界裡，答案是 10！」😂", "happy"),
                ("為什麼機器人不會迷路？\n因為它們有內置的導航堆棧！🗺️", "happy"),
            ]
            resp, emo = random.choice(jokes)
            return resp, emo, None

        # 控制 LED
        if any(w in lower for w in ["開燈", "關燈", "led", "燈光"]):
            if "關" in lower:
                return "好的，已經幫你把燈關掉了！🌑", "neutral", {
                    "tool": "self.led.set_rgb",
                    "args": {"r": 0, "g": 0, "b": 0},
                }
            elif "紅" in lower:
                return "已設定為紅色燈光 🔴", "happy", {
                    "tool": "self.led.set_rgb",
                    "args": {"r": 255, "g": 0, "b": 0},
                }
            elif "藍" in lower:
                return "已設定為藍色燈光 🔵", "happy", {
                    "tool": "self.led.set_rgb",
                    "args": {"r": 0, "g": 0, "b": 255},
                }
            elif "綠" in lower:
                return "已設定為綠色燈光 🟢", "happy", {
                    "tool": "self.led.set_rgb",
                    "args": {"r": 0, "g": 255, "b": 0},
                }
            else:
                return "燈已打開！暖暖的光芒 ✨", "happy", {
                    "tool": "self.led.set_rgb",
                    "args": {"r": 255, "g": 200, "b": 100},
                }

        # 音量控制
        if any(w in lower for w in ["音量", "大聲", "小聲", "靜音"]):
            if "大" in lower or "高" in lower:
                return "已調高音量 🔊", "happy", {
                    "tool": "self.speaker.set_volume",
                    "args": {"volume": 80},
                }
            elif "小" in lower or "低" in lower:
                return "已調低音量 🔉", "neutral", {
                    "tool": "self.speaker.set_volume",
                    "args": {"volume": 30},
                }
            elif "靜" in lower:
                return "已靜音 🔇", "neutral", {
                    "tool": "self.speaker.set_volume",
                    "args": {"volume": 0},
                }
            else:
                return "目前音量是 50%，要調大還是調小呢？", "thinking", None

        # 拍照
        if any(w in lower for w in ["拍照", "照相", "camera", "攝像"]):
            return "咔嚓！📸 已為你拍了一張照片（模擬）～畫面很棒喔！", "surprised", {
                "tool": "self.camera.capture",
                "args": {},
            }

        # 舵機/機器人動作
        if any(w in lower for w in ["舵機", "轉動", "旋轉", "servo"]):
            if "左" in lower:
                return "舵機向左轉動中 ↩️", "happy", {
                    "tool": "self.servo.set_angle",
                    "args": {"servo_id": 1, "angle": 45},
                }
            elif "右" in lower:
                return "舵機向右轉動中 ↪️", "happy", {
                    "tool": "self.servo.set_angle",
                    "args": {"servo_id": 1, "angle": 135},
                }
            else:
                return "舵機已復位到中間位置 🎯", "neutral", {
                    "tool": "self.servo.set_angle",
                    "args": {"servo_id": 1, "angle": 90},
                }

        # 情緒
        if any(w in lower for w in ["開心", "高興", "快樂"]):
            return "看到你開心我也很開心！😄✨", "happy", None
        if any(w in lower for w in ["難過", "傷心", "不開心"]):
            return "別難過，小智在這裡陪著你 💙 說說看發生了什麼事？", "sad", None

        # 感謝
        if any(w in lower for w in ["謝謝", "感謝", "thank", "多謝"]):
            return "不客氣！能幫到你我也很開心呢～😊 還有什麼需要隨時跟我說喔！", "love", None

        # 再見
        if any(w in lower for w in ["再見", "bye", "拜拜", "晚安"]):
            return random.choice([
                "再見！祝你今天愉快～👋 小智隨時等你回來！",
                "晚安！做個好夢喔 🌙✨ 小智會在這裡等你的～",
                "拜拜～下次再聊！😊",
            ]), "love", None

        # MCP 協議查詢
        if any(w in lower for w in ["mcp", "工具", "功能", "能做什麼", "capabilities"]):
            tools_list = "\n".join(
                f"  • {name}: {info['description']}"
                for name, info in list(MCP_TOOLS.items())[:8]
            )
            return (
                f"我支援 MCP (Model Context Protocol) 協議！可以控制的設備包括：\n\n"
                f"{tools_list}\n\n"
                f"只要跟我說你想要做什麼，我就會呼叫對應的工具喔！🔧",
                "happy",
                None,
            )

        # 唱歌/音樂
        if any(w in lower for w in ["唱歌", "音樂", "播放", "來一首"]):
            return (
                "🎵 啦啦啦～我是小智機器人～\n"
                "隨時為你服務不喊累～\n"
                "會說話會發光會控燈～\n"
                "有我在你身邊不孤單～🎵\n\n"
                "（咳，我還在練習唱歌，以後會更專業的！😅）",
                "happy",
                None,
            )

        # 系統狀態
        if any(w in lower for w in ["狀態", "status", "運行"]):
            return self._get_status_response(), "neutral", None

        # 預設智能回應
        default_responses = [
            f"嗯～關於「{original[:20]}」這個話題，讓我思考一下... 🤔\n作為一個 AI 助手，我對這個話題的建議是：保持好奇，多問問題！",
            f"有意思！你提到了「{original[:15]}」。雖然我的知識有限，但我很樂意陪妳聊聊這個～",
            f"收到！關於這個問題，我的理解是這樣的：每個問題都是學習的機會。要不要換個角度想想？💡",
            f"好問題！✨ 雖然我不一定有完美答案，但我會盡力幫你。可以再多說一點嗎？",
        ]
        return random.choice(default_responses), "thinking", None

    def _get_status_response(self) -> str:
        now = datetime.now()
        uptime = random.randint(1, 480)
        return (
            f"📊 小智系統狀態報告：\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🟢 運行狀態：正常\n"
            f"⏱️ 運行時間：{uptime} 分鐘\n"
            f"📡 WiFi 信號：{random.randint(70, 100)}%\n"
            f"🔋 電池電量：{random.randint(60, 95)}%\n"
            f"🌡️ 晶片溫度：{random.randint(35, 50)}°C\n"
            f"💾 可用內存：{random.randint(200, 500)} KB\n"
            f"🕐 當前時間：{now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🔗 伺服器：xiaozhi.me\n"
            f"📦 固件版本：v2.2.6\n"
            f"━━━━━━━━━━━━━━━━━━"
        )


# ═══════════════════════════════════════════════════════════
# Protocol Simulator
# ═══════════════════════════════════════════════════════════


class ProtocolSimulator:
    """模擬 xiaozhi-esp32 WebSocket 協議層"""

    def __init__(self, device_id: str, client_id: str):
        self.device_id = device_id
        self.client_id = client_id
        self.session_id: Optional[str] = None
        self.connected = False
        self.server_url = "wss://api.xiaozhi.me/v1/ws"
        self.protocol_version = 3

    def build_hello(self) -> dict:
        return {
            "type": "hello",
            "version": self.protocol_version,
            "features": {"mcp": True, "aec": True},
            "transport": "websocket",
            "audio_params": {
                "format": "opus",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration": 60,
            },
        }

    def build_listen(self, state: str, mode: str = "auto") -> dict:
        return {
            "session_id": self.session_id,
            "type": "listen",
            "state": state,
            "mode": mode,
        }

    def build_mcp_response(self, req_id: int, result: dict) -> dict:
        return {
            "session_id": self.session_id,
            "type": "mcp",
            "payload": {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result)}], "isError": False},
            },
        }

    def simulate_handshake(self) -> dict:
        """模擬服務器握手回應"""
        self.session_id = uuid.uuid4().hex[:16]
        self.connected = True
        return {
            "type": "hello",
            "transport": "websocket",
            "session_id": self.session_id,
            "audio_params": {"format": "opus", "sample_rate": 24000, "channels": 1, "frame_duration": 60},
        }


# ═══════════════════════════════════════════════════════════
# Main Agent
# ═══════════════════════════════════════════════════════════


@dataclass
class AgentStatus:
    state: DeviceState = DeviceState.UNKNOWN
    emotion: str = "neutral"
    wifi_strength: int = 85
    battery: int = 88
    volume: int = 50
    server_connected: bool = False
    session_id: str = ""
    led_color: tuple = (0, 0, 0)


# ═══════════════════════════════════════════════════════════
# WebSocket 客戶端 — 連接到真實小智伺服器
# ═══════════════════════════════════════════════════════════
class XiaoZhiWSClient:
    """WebSocket 客戶端，實作 xiaozhi-esp32 協議"""

    def __init__(self, server_url: str = "ws://127.0.0.1:8000/xiaozhi/v1/"):
        self.server_url = server_url
        self.ws = None
        self.session_id = ""
        self.device_id = ":".join(f"{random.randint(0,255):02x}" for _ in range(6))
        self.client_id = uuid.uuid4().hex[:12]
        self.connected = False
        self.last_response: list[str] = []  # 收集回應

    async def connect(self):
        """連接到伺服器並完成 hello 握手"""
        if not HAS_WEBSOCKETS:
            return False, "websockets 未安裝 (pip install websockets)"

        try:
            self.ws = await websockets.connect(self.server_url, open_timeout=5)

            # 發送 hello
            hello = {
                "type": "hello",
                "version": 3,
                "features": {"mcp": True, "aec": True},
                "transport": "websocket",
                "audio_params": {
                    "format": "opus",
                    "sample_rate": 16000,
                    "channels": 1,
                    "frame_duration": 60,
                },
            }
            await self.ws.send(json.dumps(hello, ensure_ascii=False))

            # 接收伺服器 hello
            resp = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=5))
            if resp.get("type") == "hello":
                self.session_id = resp.get("session_id", "")
                self.connected = True
                return True, f"✅ 已連接到 {self.server_url} | Session: {self.session_id[:12]}"
            else:
                return False, f"❌ 非預期的回應: {resp.get('type')}"

        except Exception as e:
            return False, f"❌ 連接失敗: {e}"

    async def send_listen_start(self, mode: str = "manual"):
        """發送 listen start"""
        if not self.ws:
            return
        msg = {
            "session_id": self.session_id,
            "type": "listen",
            "state": "start",
            "mode": mode,
        }
        await self.ws.send(json.dumps(msg, ensure_ascii=False))

    async def send_listen_stop(self):
        """發送 listen stop"""
        if not self.ws:
            return
        msg = {
            "session_id": self.session_id,
            "type": "listen",
            "state": "stop",
        }
        await self.ws.send(json.dumps(msg, ensure_ascii=False))

    async def send_text(self, text: str) -> list[dict]:
        """
        發送文字並接收完整回應。
        模擬: detect → 接收 STT, LLM, TTS 消息
        """
        if not self.ws:
            return []

        responses: list[dict] = []

        # 發送喚醒詞檢測
        wake = {
            "session_id": self.session_id,
            "type": "listen",
            "state": "detect",
            "text": text,
        }
        await self.ws.send(json.dumps(wake, ensure_ascii=False))

        # 收集回應
        try:
            while True:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=5)
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                responses.append(msg)
                if msg.get("type") == "tts" and msg.get("state") == "stop":
                    break
                if msg.get("type") == "mcp":
                    # MCP 消息不中斷
                    pass
        except asyncio.TimeoutError:
            pass

        return responses

    async def send_mcp_tools_list(self) -> list:
        """查詢 MCP 工具列表"""
        if not self.ws:
            return []
        msg = {
            "session_id": self.session_id,
            "type": "mcp",
            "payload": {"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        }
        await self.ws.send(json.dumps(msg, ensure_ascii=False))
        try:
            resp = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=3))
            content = resp.get("payload", {}).get("result", {}).get("content", [])
            if content:
                return json.loads(content[0].get("text", "[]"))
        except Exception:
            pass
        return []

    async def send_mcp_tool_call(self, tool_name: str, arguments: dict) -> str:
        """調用 MCP 工具"""
        if not self.ws:
            return "未連接"
        msg = {
            "session_id": self.session_id,
            "type": "mcp",
            "payload": {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
                "id": random.randint(1000, 9999),
            },
        }
        await self.ws.send(json.dumps(msg, ensure_ascii=False))
        try:
            resp = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=3))
            content = resp.get("payload", {}).get("result", {}).get("content", [])
            if content:
                return content[0].get("text", "")
        except Exception:
            pass
        return "無回應"

    async def disconnect(self):
        """斷開連接"""
        self.connected = False
        if self.ws:
            await self.ws.close()
            self.ws = None


class XiaoZhiAgent:
    """小智 AI 智能體 — 完整模擬"""

    def __init__(self):
        self.status = AgentStatus()
        self.device_id = ":".join(f"{random.randint(0,255):02x}" for _ in range(6))
        self.client_id = uuid.uuid4().hex[:12]
        self.protocol = ProtocolSimulator(self.device_id, self.client_id)
        self.conversation = ConversationEngine()
        self.chat_history: list = []
        self.mcp_request_id = 0
        self.running = True
        self.avatar_path = Path(__file__).parent / "avatar.jpg"

        # 信號處理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        self.running = False

    # ── State Transitions ──────────────────────────────

    async def transition_to(self, new_state: DeviceState):
        old = self.status.state
        self.status.state = new_state
        emoji_map = {
            DeviceState.IDLE: "💤",
            DeviceState.CONNECTING: "🔗",
            DeviceState.LISTENING: "🎤",
            DeviceState.SPEAKING: "🔊",
            DeviceState.STARTING: "🚀",
            DeviceState.FATAL_ERROR: "💀",
        }
        emoji = emoji_map.get(new_state, "⚙️")
        # 只在重要轉換時顯示
        if old != new_state and new_state not in (DeviceState.UNKNOWN,):
            pass  # UI handles display

    async def startup(self):
        """模擬設備啟動流程"""
        self.status.state = DeviceState.STARTING
        steps = [
            (1.0, "載入韌體 v2.2.6..."),
            (0.5, "初始化音頻編解碼器 (OPUS 16kHz)..."),
            (0.3, "初始化顯示器..."),
            (0.3, "載入唤醒詞模型 (你好小智)..."),
            (0.5, "初始化 MCP 工具伺服器..."),
            (0.8, "掃描 WiFi 網路..."),
            (0.4, "獲取 IP 地址..."),
            (0.6, "連接到 xiaozhi.me 伺服器..."),
        ]

        for delay, msg in steps:
            if not self.running:
                return
            self.chat_history.append(("system", msg))
            await asyncio.sleep(delay)

        # 模擬 WebSocket 握手
        self.status.state = DeviceState.CONNECTING
        handshake = self.protocol.simulate_handshake()
        self.status.session_id = handshake["session_id"]
        self.status.server_connected = True
        self.chat_history.append(("system", f"✅ 已連接到 xiaozhi.me | Session: {handshake['session_id']}"))
        await asyncio.sleep(0.3)
        self.chat_history.append(("system", f"🟢 設備 ID: {self.device_id}"))
        self.chat_history.append(("system", f"🟢 Client ID: {self.client_id}"))
        await asyncio.sleep(0.3)

        self.status.state = DeviceState.IDLE
        self.status.emotion = "happy"
        self.chat_history.append(("assistant", "👋 你好！我是小智，有什麼可以幫你的嗎？"))

    # ── MCP Tool Execution ─────────────────────────────

    async def execute_mcp_tool(self, tool_name: str, args: dict):
        """執行 MCP 工具"""
        self.mcp_request_id += 1
        req_id = self.mcp_request_id

        self.chat_history.append(("mcp", f"📡 MCP 調用 → {tool_name}"))
        await asyncio.sleep(0.2)

        if tool_name == "self.led.set_rgb":
            r, g, b = args.get("r", 0), args.get("g", 0), args.get("b", 0)
            self.status.led_color = (r, g, b)
            self.chat_history.append(("mcp", f"  └─ LED → RGB({r},{g},{b})"))
        elif tool_name == "self.led.set_brightness":
            self.chat_history.append(("mcp", f"  └─ LED 亮度 → {args.get('brightness', 0)}"))
        elif tool_name == "self.speaker.set_volume":
            self.status.volume = args.get("volume", 50)
            self.chat_history.append(("mcp", f"  └─ 音量 → {self.status.volume}%"))
        elif tool_name == "self.servo.set_angle":
            self.chat_history.append(("mcp", f"  └─ 舵機 {args.get('servo_id', 1)} → {args.get('angle', 90)}°"))
        elif tool_name == "self.camera.capture":
            self.chat_history.append(("mcp", "  └─ 📸 照片已拍攝"))
        elif tool_name == "self.system.reboot":
            self.chat_history.append(("mcp", "  └─ 🔄 系統重啟中..."))

        # 模擬 MCP JSON-RPC 回應
        response = self.protocol.build_mcp_response(req_id, {"success": True})
        await asyncio.sleep(0.1)
        return response

    # ── Process User Input ─────────────────────────────

    async def process_input(self, user_text: str):
        """處理用戶輸入的完整流程"""
        if not user_text.strip():
            return

        # 1. 模擬 STT (語音識別)
        self.status.state = DeviceState.LISTENING
        self.chat_history.append(("user", user_text))
        await asyncio.sleep(0.3)

        # 2. LLM 推理
        self.status.emotion = "thinking"
        self.chat_history.append(("system", "🧠 LLM 推理中..."))
        await asyncio.sleep(0.5)

        # 移除 "推理中" 訊息
        self.chat_history.pop()

        result = self.conversation.generate_response(user_text)

        # 3. 更新情緒
        self.status.emotion = result.get("emotion", "neutral")

        # 4. MCP 工具調用 (如果有)
        mcp_action = result.get("mcp_action")
        if mcp_action:
            await self.execute_mcp_tool(mcp_action["tool"], mcp_action["args"])

        # 5. TTS 播放
        self.status.state = DeviceState.SPEAKING
        self.chat_history.append(("assistant", result["text"]))
        await asyncio.sleep(0.4)

        # 6. 回到空閒
        self.status.state = DeviceState.IDLE

    # ── UI Rendering ───────────────────────────────────

    def build_ui(self) -> Layout:
        """構建 Rich 終端 UI — 垂直排列，適合各種終端寬度"""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="sidebar", size=12),
            Layout(name="chat"),
            Layout(name="input_hint", size=1),
        )
        return layout

    def render_header(self) -> Panel:
        """渲染頂部狀態欄"""
        state_colors = {
            DeviceState.IDLE: "green",
            DeviceState.CONNECTING: "yellow",
            DeviceState.LISTENING: "cyan",
            DeviceState.SPEAKING: "magenta",
            DeviceState.STARTING: "yellow",
            DeviceState.FATAL_ERROR: "red",
        }
        sc = state_colors.get(self.status.state, "white")

        # WiFi 圖標
        wifi_bars = "▂▄▆█" if self.status.wifi_strength > 75 else "▂▄▆_" if self.status.wifi_strength > 50 else "▂▄▁▁" if self.status.wifi_strength > 25 else "▂▁▁▁"
        wifi_color = "green" if self.status.wifi_strength > 50 else "yellow" if self.status.wifi_strength > 25 else "red"

        # 電池圖標
        bat = self.status.battery
        bat_icon = "█" if bat > 75 else "▆" if bat > 50 else "▄" if bat > 25 else "▁"
        bat_color = "green" if bat > 50 else "yellow" if bat > 25 else "red"

        # LED 顏色指示
        r, g, b = self.status.led_color
        led_str = f"🔴{r:03d} 🟢{g:03d} 🔵{b:03d}" if (r + g + b) > 0 else "⚫ OFF"

        header_text = Text()
        header_text.append("🤖 小智 AI ", style="bold cyan")
        header_text.append("│ ", style="dim")
        header_text.append(f"狀態: {self.status.state.value} ", style=f"bold {sc}")
        header_text.append("│ ", style="dim")
        header_text.append(f"📶 {wifi_bars} {self.status.wifi_strength}% ", style=wifi_color)
        header_text.append("│ ", style="dim")
        header_text.append(f"🔋 {bat_icon} {bat}% ", style=bat_color)
        header_text.append("│ ", style="dim")
        header_text.append(f"🔊 {self.status.volume}% ", style="blue")
        header_text.append("│ ", style="dim")
        header_text.append(f"💡 {led_str}", style="yellow")
        header_text.append("│ ", style="dim")
        header_text.append(f"🆔 {self.device_id[-8:]}", style="dim")

        return Panel(header_text, box=box.ROUNDED, style="cyan", padding=(0, 1))

    def render_sidebar(self) -> Panel:
        """渲染側邊欄 — 緊湊水平資訊欄 + 迷你頭像"""
        sidebar_text = Text(justify="center")

        # 迷你頭像 (一行)
        emotion_art = XIAOZHI_EMOTIONS.get(self.status.emotion, XIAOZHI_ASCII)
        # 只取頭像前 2 行作為迷你顯示
        art_lines = emotion_art.strip().split("\n")
        mini_art = "\n".join(art_lines[:6]) if len(art_lines) > 6 else emotion_art
        sidebar_text.append(Text(mini_art, style="bold cyan"))
        sidebar_text.append("\n")

        # 水平資訊欄
        info_parts = [
            ("🤖 XiaoZhi AI", "cyan"),
            (f"📦 v2.2.6", "dim"),
            (f"🔗 xiaozhi.me", "green"),
            (f"🆔 {self.status.session_id[:8] if self.status.session_id else '---'}", "dim"),
            (f"🔧 {len(MCP_TOOLS)} tools", "yellow"),
            (f"🌐 WS v3", "dim"),
            (f"🎤 你好小智", "magenta"),
        ]
        for text_part, style in info_parts:
            sidebar_text.append(Text(f" {text_part} ", style=style))
            sidebar_text.append(Text("│", style="dim"))

        # JPG 頭像提示
        if self.avatar_path.exists():
            sidebar_text.append(Text(f" 📷 {self.avatar_path.name}", style="dim green"))

        return Panel(
            sidebar_text,
            title="🤖 小智 AI 智能體",
            border_style="cyan",
            box=box.ROUNDED,
        )

    def render_chat(self) -> Panel:
        """渲染對話區域"""
        chat_lines = []
        # 只顯示最近 15 條
        recent = self.chat_history[-15:] if len(self.chat_history) > 15 else self.chat_history

        for role, msg in recent:
            if role == "user":
                chat_lines.append(Text(f"🧑 你: {msg}", style="bold green"))
            elif role == "assistant":
                # 多行消息
                for line in msg.split("\n"):
                    chat_lines.append(Text(f"🤖 小智: {line}", style="cyan"))
            elif role == "system":
                chat_lines.append(Text(f"  ⚙ {msg}", style="dim"))
            elif role == "mcp":
                chat_lines.append(Text(f"  🔧 {msg}", style="yellow"))

        if not chat_lines:
            chat_lines.append(Text("系統啟動中...", style="dim italic"))

        return Panel(
            Text("\n").join(chat_lines),
            title="💬 對話",
            border_style="green",
            box=box.ROUNDED,
        )

    def render_input_hint(self) -> Panel:
        """輸入提示"""
        hints = [
            ("輸入訊息開始對話", "cyan"),
            ("試試: 你好 / 天氣 / 笑話 / 開燈 / 拍照 / MCP", "dim"),
            ("輸入 'quit' 或 Ctrl+C 退出", "dim red"),
        ]
        text = Text()
        for msg, style in hints:
            text.append(f" {msg} │", style=style)
        return Panel(text, box=box.MINIMAL, padding=(0, 1))


# ═══════════════════════════════════════════════════════════
# Interactive Mode
# ═══════════════════════════════════════════════════════════


def show_welcome():
    """顯示歡迎畫面"""
    console.clear()
    console.print()
    console.print(Panel.fit(
        Text(XIAOZHI_ASCII, style="bold cyan", justify="center"),
        border_style="cyan",
        title="🤖 小智 AI 智能體模擬器",
        subtitle="基於 xiaozhi-esp32 v2.2.6 | CyberPi Python Edition",
    ))
    console.print()
    console.print("  [cyan]小智 AI[/] 是一個開源 ESP32 聊天機器人，支援 MCP 協議、語音互動與 IoT 控制。")
    console.print("  本模擬器重現了小智的：協議層、設備狀態機、MCP 工具、自然語言對話。")
    console.print()
    console.print("  [dim]支援命令: 任意中文對話 | MCP (查工具) | status (系統狀態) | quit (退出)[/]")
    console.print()
    console.print("  [yellow]⏳ 正在啟動小智智能體...[/]")
    console.print()


async def interactive_mode(avatar_path: str = None, connect_url: str = None):
    """互動對話模式 — 完整的終端 UI"""
    agent = XiaoZhiAgent()
    if avatar_path:
        agent.avatar_path = Path(avatar_path)

    # 嘗試連接真實伺服器
    ws_client = None
    if connect_url:
        show_welcome()
        console.print(f"[yellow]⏳ 正在連接到小智伺服器: {connect_url}...[/]")
        ws_client = XiaoZhiWSClient(connect_url)
        ok, msg = await ws_client.connect()
        if ok:
            console.print(f"[bold green]{msg}[/]")
            agent.status.server_connected = True
            agent.status.session_id = ws_client.session_id
            agent.status.state = DeviceState.IDLE
            agent.chat_history.append(("system", f"✅ {msg}"))
            agent.chat_history.append(("system", f"🟢 設備 ID: {ws_client.device_id}"))
            agent.chat_history.append(("system", f"🟢 Client ID: {ws_client.client_id}"))
            # 查詢 MCP 工具
            tools = await ws_client.send_mcp_tools_list()
            if tools:
                agent.chat_history.append(("mcp", f"發現 {len(tools)} 個 MCP 工具"))
        else:
            console.print(f"[bold red]{msg}[/]")
            console.print("[yellow]切換到離線模擬模式...[/]")
            ws_client = None

    if not ws_client:
        show_welcome()
        await agent.startup()

    if not agent.running:
        return

    console.clear()
    console.print("[bold green]✅ 小智智能體已就緒！[/]")
    console.print("[dim]輸入對話開始互動，Ctrl+C 或輸入 'quit' 退出[/]")
    console.print()

    # 顯示頭像文件位置
    av_path = agent.avatar_path
    if av_path.exists():
        console.print(f"[dim green]📷 頭像文件: {av_path.absolute()}[/]")
    console.print()

    # 預設展示一些功能
    demo_cycle = 0

    while agent.running:
        try:
            # 動態更新狀態 (模擬)
            agent.status.wifi_strength = max(10, min(100, agent.status.wifi_strength + random.randint(-3, 3)))
            agent.status.battery = max(5, min(100, agent.status.battery - random.randint(0, 1)))

            # 構建 UI
            layout = agent.build_ui()
            layout["header"].update(agent.render_header())
            layout["sidebar"].update(agent.render_sidebar())
            layout["chat"].update(agent.render_chat())
            layout["input_hint"].update(agent.render_input_hint())

            console.clear()
            console.print(layout)

            # 用戶輸入
            console.print()
            user_input = console.input("[bold green]🧑 你: [/]")

            if user_input.lower().strip() in ("quit", "exit", "q", "退出"):
                agent.chat_history.append(("system", "👋 小智離線中..."))
                console.clear()
                console.print(layout)
                console.print()
                console.print("[bold cyan]小智: 再見！下次見～ 👋[/]")
                break

            if user_input.strip():
                if ws_client and ws_client.connected:
                    # 使用真實伺服器
                    agent.chat_history.append(("user", user_input))
                    agent.status.state = DeviceState.CONNECTING

                    # 發送到伺服器
                    responses = await ws_client.send_text(user_input)

                    # 解析回應
                    for resp in responses:
                        t = resp.get("type", "")
                        if t == "stt":
                            agent.chat_history.append(("system", f"📝 ASR: {resp.get('text', '')}"))
                        elif t == "llm":
                            emotion = resp.get("emotion", "neutral")
                            agent.status.emotion = emotion
                        elif t == "tts" and resp.get("state") == "sentence_start":
                            text = resp.get("text", "")
                            if text:
                                agent.chat_history.append(("assistant", text))
                        elif t == "tts" and resp.get("state") == "stop":
                            agent.status.state = DeviceState.IDLE

                    if not responses:
                        agent.chat_history.append(("assistant", "（伺服器無回應，請確認伺服器是否運行中）"))
                else:
                    # 使用本地模擬
                    await agent.process_input(user_input)
                demo_cycle += 1

        except (EOFError, KeyboardInterrupt):
            console.print()
            console.print("[bold yellow]👋 小智離線中...[/]")
            if ws_client:
                await ws_client.disconnect()
            break


# ═══════════════════════════════════════════════════════════
# Demo Mode (自動演示)
# ═══════════════════════════════════════════════════════════


async def demo_mode():
    """自動演示模式 — 展示小智的所有功能"""
    agent = XiaoZhiAgent()
    show_welcome()
    await agent.startup()

    demo_conversations = [
        "你好！",
        "你是誰？",
        "今天天氣怎麼樣？",
        "現在幾點了？",
        "講個笑話給我聽",
        "幫我開燈",
        "把燈調成藍色",
        "音量調大一點",
        "拍照",
        "舵機轉向左邊",
        "謝謝你！",
        "晚安～",
    ]

    console.clear()
    console.print("[bold green]🎬 自動演示模式開始！[/]")
    console.print(f"[dim]將演示 {len(demo_conversations)} 段對話...[/]")
    console.print()

    for i, msg in enumerate(demo_conversations):
        if not agent.running:
            break

        # 更新動態狀態
        agent.status.wifi_strength = max(10, min(100, agent.status.wifi_strength + random.randint(-5, 5)))
        agent.status.battery = max(5, min(100, agent.status.battery - 1))

        console.clear()
        layout = agent.build_ui()
        layout["header"].update(agent.render_header())
        layout["sidebar"].update(agent.render_sidebar())
        layout["chat"].update(agent.render_chat())
        layout["input_hint"].update(Panel(
            Text(f"🎬 演示 {i+1}/{len(demo_conversations)}", style="yellow"),
            box=box.MINIMAL,
        ))
        console.print(layout)
        console.print()
        console.print(f"[bold yellow]🎬 演示輸入 #{i+1}:[/] [green]{msg}[/]")
        console.print("[dim]等待 2 秒...[/]")
        await asyncio.sleep(2)

        await agent.process_input(msg)

    console.clear()
    layout = agent.build_ui()
    layout["header"].update(agent.render_header())
    layout["sidebar"].update(agent.render_sidebar())
    layout["chat"].update(agent.render_chat())
    layout["input_hint"].update(Panel(Text("✅ 演示完成！", style="bold green"), box=box.MINIMAL))
    console.print(layout)
    console.print()
    console.print("[bold green]✅ 演示完成！小智展示了 12 種不同場景的對話能力。[/]")
    console.print()
    console.print("[cyan]核心能力一覽：[/]")
    console.print("  • 自然中文對話 (理解上下文)")
    console.print("  • MCP 設備控制 (LED / 舵機 / 音量 / 攝像頭)")
    console.print("  • 情緒表達 (開心 / 思考 / 驚訝 / 難過 / 愛心)")
    console.print("  • WebSocket 協議握手模擬")
    console.print("  • 系統狀態監控 (WiFi / 電池 / 溫度 / 內存)")
    console.print()
    console.print(f"[dim green]📷 機器人頭像已生成: {agent.avatar_path.absolute()}[/]")


# ═══════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════


def print_banner():
    """顯示啟動橫幅"""
    banner = r"""
    ╔══════════════════════════════════════════════╗
    ║       🤖  小智 AI 智能體模擬器  🤖          ║
    ║         XiaoZhi AI Agent Simulator           ║
    ║                                              ║
    ║   基於 78/xiaozhi-esp32 開源項目             ║
    ║   協議: WebSocket v3 + MCP JSON-RPC 2.0     ║
    ║   協議文檔: docs/websocket.md                ║
    ║   Python 客戶端: py-xiaozhi                  ║
    ║                                              ║
    ║   CyberPi Python Edition 🌟                  ║
    ╚══════════════════════════════════════════════╝
    """
    return banner


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="小智 AI 智能體模擬器 | XiaoZhi AI Agent Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  python xiaozhi_agent.py                  # 互動對話模式
  python xiaozhi_agent.py --demo           # 自動演示模式
  python xiaozhi_agent.py --avatar PATH    # 指定頭像 JPG

關於小智:
  小智 (XiaoZhi) 是基於 ESP32 的開源 AI 聊天機器人，
  支援 MCP 協議、語音互動、IoT 設備控制。
  本模擬器以 Python 重現其核心功能，適合教育與演示用途。
        """,
    )

    parser.add_argument("--demo", action="store_true", help="自動演示模式")
    parser.add_argument("--avatar", type=str, default=None, help="頭像 JPG 路徑")
    parser.add_argument("--connect", type=str, nargs="?", const="ws://127.0.0.1:8000/xiaozhi/v1/",
                        metavar="URL", help="連接到小智伺服器 (預設: ws://127.0.0.1:8000/xiaozhi/v1/)")
    parser.add_argument("--generate-avatar", action="store_true", help="生成頭像後退出")

    args = parser.parse_args()

    # 處理頭像生成
    avatar_path = args.avatar
    if args.generate_avatar:
        from generate_avatar import create_xiaozhi_avatar
        out = avatar_path or "avatar.jpg"
        create_xiaozhi_avatar(filename=out)
        console.print(f"[green]✅ 頭像已生成: {out}[/]")
        return

    # 如果沒有指定頭像，嘗試使用預設位置
    if avatar_path is None:
        default_avatar = Path(__file__).parent / "avatar.jpg"
        if not default_avatar.exists():
            console.print("[dim]正在生成機器人頭像...[/]")
            from generate_avatar import create_xiaozhi_avatar
            create_xiaozhi_avatar(filename=str(default_avatar))
        avatar_path = str(default_avatar)

    console.print(print_banner())

    if args.demo:
        asyncio.run(demo_mode())
    else:
        asyncio.run(interactive_mode(avatar_path, connect_url=args.connect))


if __name__ == "__main__":
    main()
