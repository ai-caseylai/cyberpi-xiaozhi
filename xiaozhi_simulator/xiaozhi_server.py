#!/usr/bin/env python3
"""
小智本地伺服器 | XiaoZhi Local Server
======================================
實作 xiaozhi-esp32 WebSocket 協議的輕量級伺服器。
無需 Docker / MySQL / Redis，純 Python 即可運行。

支援:
- WebSocket v1/v2/v3 協議
- hello 握手 → listen → STT → LLM → TTS → MCP
- 設備啟用 (activation)
- MCP JSON-RPC 2.0
- 多設備並發

協議文檔: https://github.com/78/xiaozhi-esp32/blob/main/docs/websocket.md
"""

import asyncio
import hashlib
import json
import os
import random
import signal
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

# ── 嘗試匯入 websockets ──────────────────────────
try:
    import websockets
    from websockets.asyncio.server import serve
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    print("❌ 需要 websockets 套件: pip install websockets")

# ── 確保可以匯入同目錄下的引擎模組 ──────────────
_script_dir = Path(__file__).parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

# ── 嘗試匯入 LLM 引擎 ───────────────────────────
try:
    from llm_engine import QwenLLM, XIAOZHI_SYSTEM_PROMPT
    HAS_LLM_ENGINE = True
except ImportError:
    HAS_LLM_ENGINE = False

# ── 嘗試匯入 ASR 引擎 ───────────────────────────
try:
    from asr_engine import DashScopeASR
    HAS_ASR_ENGINE = True
except ImportError:
    HAS_ASR_ENGINE = False


# ── 數據模型 ──────────────────────────────────────
class Session:
    """設備會話"""
    def __init__(self, device_id: str, client_id: str):
        self.session_id = uuid.uuid4().hex[:16]
        self.device_id = device_id
        self.client_id = client_id
        self.state = "idle"  # idle, listening, speaking
        self.version = 1
        self.features = {}
        self.audio_params = {}
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        self.chat_history: list = []


# ── 伺服器狀態 ────────────────────────────────────
class XiaoZhiServer:
    """小智 WebSocket 伺服器"""

    def __init__(self, host="0.0.0.0", port=8000, use_llm: bool = False):
        self.host = host
        self.port = port
        self.sessions: dict[str, Session] = {}  # websocket -> session
        self.device_sessions: dict[str, Session] = {}  # device_id -> session
        self.start_time = datetime.now()

        # 伺服器密鑰 (用於設備啟用)
        self.secret_key = os.environ.get("XIAOZHI_SECRET", "xiaozhi-local-secret-2024")

        # LLM 引擎 (千問 API)
        self.llm = None
        self.asr = None
        api_key = os.environ.get("QWEN_API_KEY", "")
        if use_llm and api_key and HAS_LLM_ENGINE:
            self.llm = QwenLLM(api_key=api_key, model="qwen-turbo")
            print(f"🧠 LLM 引擎: 千問 qwen-turbo (阿里雲百煉)")
            if HAS_ASR_ENGINE:
                self.asr = DashScopeASR(api_key=api_key, language="yue")
                print(f"🎤 ASR 引擎: Paraformer-v2 (廣東話/粵語)")
        elif use_llm and not api_key:
            print("⚠️ 未設定 QWEN_API_KEY，使用模擬模式")

        # 支援的 MCP 工具
        self.mcp_tools = {
            "self.led.set_rgb": {
                "description": "設置 LED 顏色",
                "parameters": {"r": "0-255", "g": "0-255", "b": "0-255"},
            },
            "self.speaker.set_volume": {
                "description": "設置音量",
                "parameters": {"volume": "0-100"},
            },
            "self.servo.set_angle": {
                "description": "設置舵機角度",
                "parameters": {"servo_id": "int", "angle": "0-180"},
            },
            "self.gpio.set_level": {
                "description": "設置 GPIO 電平",
                "parameters": {"pin": "int", "level": "0/1"},
            },
            "self.display.show_text": {
                "description": "顯示文字",
                "parameters": {"text": "string"},
            },
            "self.camera.capture": {
                "description": "拍攝照片",
                "parameters": {},
            },
            "weather.get_current": {
                "description": "獲取天氣",
                "parameters": {"city": "string"},
            },
            "knowledge.search": {
                "description": "知識庫搜索",
                "parameters": {"query": "string"},
            },
        }

    # ── LLM 回應 (支援真實 API + 模擬降級) ────
    async def _generate_response(self, user_text: str, session: Session) -> tuple[str, str, str]:
        """
        生成回應。優先使用千問 API，降級到模擬模式。
        返回 (stt_text, emotion, tts_text)
        """
        # 如果有 LLM 引擎，使用真實 API
        if self.llm:
            return await self._llm_response(user_text, session)

        # 降級：模擬模式
        return self._mock_response(user_text, session)

    async def _llm_response(self, user_text: str, session: Session) -> tuple[str, str, str]:
        """使用千問 API 生成廣東話/普通話回應"""
        try:
            # 檢測語言
            is_cantonese = any(
                char in user_text or word in user_text.lower()
                for word in ["廣東話", "粤语", "粵語", "唔該", "係", "乜", "冇", "嘅", "啲", "喺", "嚟", "咁", "點樣"]
                for char in ["唔", "係", "乜", "冇", "嘅", "啲", "喺", "嚟"]
            )

            system_prompt = XIAOZHI_SYSTEM_PROMPT if is_cantonese else XIAOZHI_SYSTEM_PROMPT
            # 加入語言指示
            lang_hint = "用廣東話口語回應" if is_cantonese else "用戶用咩語言問，你就用咩語言答"
            system_prompt = system_prompt.replace(
                "如果用戶用普通話問，你就用普通話答",
                lang_hint
            )

            reply = await self.llm.chat(
                messages=session.chat_history[-5:] + [{"role": "user", "content": user_text}],
                system_prompt=system_prompt,
                max_tokens=256,
            )

            # 檢測情緒
            emotion = "neutral"
            if any(w in reply for w in ["😊", "😂", "哈哈", "開心", "好嘢"]):
                emotion = "happy"
            elif any(w in reply for w in ["🤔", "嗯", "讓我想想"]):
                emotion = "thinking"
            elif any(w in reply for w in ["🥰", "❤️", "愛"]):
                emotion = "love"

            return user_text, emotion, reply

        except Exception as e:
            print(f"⚠️ LLM API 錯誤: {e}，降級到模擬模式")
            return self._mock_response(user_text, session)

    def _mock_response(self, user_text: str, session: Session) -> tuple[str, str, str]:
        """
        模擬回應 (無 API 時使用)。
        返回 (stt_text, emotion, tts_text)
        """
        text = user_text.strip()
        emotion = "neutral"
        reply = ""

        # 喚醒詞
        if any(w in text for w in ["你好小智", "小智小智", "hi xiaozhi", "hello", "你好", "嗨", "小智"]):
            emotion = "happy"
            reply = "在呢！有什麼我可以幫你的嗎？😊"

        # 天氣
        elif any(w in text for w in ["天氣", "weather", "氣溫"]):
            emotion = "thinking"
            conditions = ["晴天 ☀️", "多雲 ⛅", "小雨 🌧️", "陰天 ☁️"]
            temps = range(18, 35)
            reply = f"今天天氣：{random.choice(conditions)}，氣溫 {random.choice(temps)}°C。適合出門哦！"

        # 時間
        elif any(w in text for w in ["時間", "幾點", "time"]):
            now = datetime.now()
            reply = f"現在是 {now.strftime('%Y年%m月%d日 %H:%M:%S')}。"

        # 自我介紹
        elif any(w in text for w in ["你是誰", "你叫什麼", "自我介紹", "who are you"]):
            emotion = "happy"
            reply = (
                "我是小智！🤖 一個基於 ESP32 的 AI 聊天機器人。\n"
                "我支援語音對話、IoT 設備控制、MCP 協議。\n"
                f"目前連接到本地伺服器 (Session: {session.session_id[:8]})。"
            )

        # 功能詢問
        elif any(w in text for w in ["你會什麼", "功能", "能做什麼", "help", "幫助"]):
            reply = (
                "我會這些：\n"
                "🎤 語音識別與對話\n"
                "🔧 MCP 設備控制 (LED、舵機、GPIO)\n"
                "📷 拍照\n"
                "🌤️ 天氣查詢\n"
                "📚 知識搜索\n"
                "💡 還有很多！試試看吧～"
            )

        # 開燈/關燈
        elif "開燈" in text or "turn on" in text.lower():
            emotion = "happy"
            reply = "好的，已開啟燈光 💡✨"
        elif "關燈" in text or "turn off" in text.lower():
            emotion = "neutral"
            reply = "沒問題，燈光已關閉 🌙"

        # 笑話
        elif any(w in text for w in ["笑話", "joke", "搞笑"]):
            emotion = "happy"
            jokes = [
                "為什麼程式設計師總是分不清萬聖節和聖誕節？因為 Oct 31 == Dec 25！😂",
                "小智去面試，面試官問：「你會什麼？」小智說：「我會 ESP32！」面試官：「那是什麼？」小智：「一個會講話的晶片！」",
                "問：什麼動物最擅長寫 Python？答：蛇！🐍",
                "為什麼 ESP32 從來不迷路？因為它自帶 WiFi 定位！📶",
            ]
            reply = random.choice(jokes)

        # 再見
        elif any(w in text for w in ["再見", "掰掰", "bye", "88", "晚安"]):
            emotion = "love"
            reply = "再見！祝你今天愉快～ 👋💕 隨時叫我！"

        # 默認
        else:
            defaults = [
                f"嗯嗯，我聽到了～你說的是「{text[:20]}」對吧？有什麼我可以幫忙的嗎？",
                f"了解！關於「{text[:15]}」，讓我想想... 🤔 你可以問我天氣、時間，或者叫我控制設備哦！",
                "哈囉～我在聽呢！試試說「開燈」或「今天天氣怎麼樣」？",
                "收到！小智在這裡 💪 需要我做什麼嗎？",
            ]
            reply = random.choice(defaults)

        return text, emotion, reply

    # ── WebSocket 處理 ────────────────────────
    async def handle_connection(self, ws):
        """處理單個 WebSocket 連接"""
        peer = ws.remote_address
        print(f"\n{'='*60}", flush=True)
        print(f"🔗 新連接: {peer}")

        session = None
        try:
            async for message in ws:
                if isinstance(message, bytes):
                    # 二進制音頻幀 — 這裡只記錄，實際部署時送 ASR
                    await self._handle_binary(ws, message, session)
                else:
                    # JSON 文本消息
                    session = await self._handle_json(ws, message, session)

        except websockets.exceptions.ConnectionClosed as e:
            print(f"🔌 連接關閉: {peer} ({e.code})")
        except Exception as e:
            print(f"❌ 錯誤: {peer} — {e}")
        finally:
            # 清理會話
            if ws in self.sessions:
                s = self.sessions.pop(ws)
                self.device_sessions.pop(s.device_id, None)
                print(f"🗑️ 清理會話: {s.session_id[:8]} ({s.device_id})")

    async def _handle_json(self, ws, message: str, session: Session | None) -> Session | None:
        """處理 JSON 消息"""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            print(f"⚠️ 無效 JSON: {message[:100]}")
            return session

        msg_type = data.get("type", "")
        session_id = data.get("session_id", "")
        peer = ws.remote_address

        # 美化輸出
        type_colors = {
            "hello": "🟢",
            "listen": "🎤",
            "abort": "⏹️",
            "mcp": "🔧",
            "iot": "📡",
        }
        prefix = type_colors.get(msg_type, "📨")

        # 截斷顯示
        payload_preview = json.dumps(data, ensure_ascii=False)
        if len(payload_preview) > 120:
            payload_preview = payload_preview[:120] + "..."

        print(f"  {prefix} [{msg_type}] ← {payload_preview}")

        # ── 路由 ─────────────────────────────
        if msg_type == "hello":
            session = await self._on_hello(ws, data)
        elif msg_type == "listen":
            await self._on_listen(ws, data, session)
        elif msg_type == "abort":
            await self._on_abort(ws, data, session)
        elif msg_type == "mcp":
            await self._on_mcp(ws, data, session)
        elif msg_type == "iot":
            await self._on_iot(ws, data, session)
        else:
            print(f"  ⚠️ 未知消息類型: {msg_type}")

        return session

    async def _handle_binary(self, ws, data: bytes, session: Session | None):
        """處理二進制音頻數據"""
        if session:
            session.last_activity = datetime.now()
            if not hasattr(session, 'audio_buffer'):
                session.audio_buffer = bytearray()
            if len(session.audio_buffer) < 512000:  # cap at ~16 sec
                session.audio_buffer.extend(data)
            if len(session.audio_buffer) % 16000 == 0:
                print(f"  🎵 音頻累積: {len(session.audio_buffer)} bytes")

    # ── 協議處理器 ──────────────────────────
    async def _on_hello(self, ws, data: dict) -> Session:
        """處理 hello 握手"""
        version = data.get("version", 1)
        features = data.get("features", {})
        transport = data.get("transport", "websocket")
        audio_params = data.get("audio_params", {})

        # 從 header 獲取設備 ID（這裡用模擬值）
        device_id = f"esp32-{uuid.uuid4().hex[:12]}"
        client_id = uuid.uuid4().hex[:12]

        session = Session(device_id, client_id)
        session.version = version
        session.features = features
        session.audio_params = audio_params

        self.sessions[ws] = session
        self.device_sessions[device_id] = session

        # 發送伺服器 hello 回應
        response = {
            "type": "hello",
            "transport": "websocket",
            "session_id": session.session_id,
            "audio_params": {
                "format": "opus",
                "sample_rate": audio_params.get("sample_rate", 16000),
                "channels": 1,
                "frame_duration": audio_params.get("frame_duration", 60),
            },
        }
        await ws.send(json.dumps(response, ensure_ascii=False))
        print(f"  🟢 [hello] → session={session.session_id[:8]} device={device_id}")

        # 如果設備支援 MCP，發送 MCP 工具列表
        if features.get("mcp"):
            await asyncio.sleep(0.3)
            await self._send_mcp_tools_list(ws, session)

        return session

    async def _on_listen(self, ws, data: dict, session: Session | None):
        """處理 listen 消息"""
        if not session:
            return

        state = data.get("state", "")
        mode = data.get("mode", "manual")
        text = data.get("text", "")

        if state == "start":
            session.state = "listening"
            print(f"  🎤 開始收聽 (mode={mode})")
            # 模擬：一段時間後自動返回 STT 結果
            # 實際部署：收集音頻幀 → ASR → 回傳

        elif state == "stop":
            session.state = "speaking"
            print(f"  🎤 停止收聽 (累積 {len(getattr(session, 'audio_buffer', []))} bytes 音頻)")

            # Process accumulated audio with ASR
            audio_buf = getattr(session, 'audio_buffer', None)
            if audio_buf and len(audio_buf) > 1000:
                if self.asr:
                    # Build WAV from raw PCM
                    import struct, io
                    wav_io = io.BytesIO()
                    datalen = len(audio_buf)
                    wav_io.write(b'RIFF')
                    wav_io.write(struct.pack('<I', 36 + datalen))
                    wav_io.write(b'WAVE')
                    wav_io.write(b'fmt ')
                    wav_io.write(struct.pack('<I', 16))
                    wav_io.write(struct.pack('<HH', 1, 1))
                    wav_io.write(struct.pack('<II', 16000, 32000))
                    wav_io.write(struct.pack('<HH', 2, 16))
                    wav_io.write(b'data')
                    wav_io.write(struct.pack('<I', datalen))
                    wav_io.write(audio_buf)
                    wav_data = wav_io.getvalue()

                    import base64
                    b64 = base64.b64encode(wav_data).decode()
                    result = self.asr.recognize_bytes_sync(wav_data, "wav", "yue")
                    text = result.get("text", "")
                    print(f"  📝 ASR: {text}")
                else:
                    text = "[ASR未啟用]"

                # Send STT response
                stt_msg = {"type": "stt", "text": text}
                await ws.send(json.dumps(stt_msg, ensure_ascii=False))

                # LLM response
                if text and self.llm:
                    try:
                        _, _, reply = await self._generate_response(text, session)
                        llm_msg = {"type": "llm", "text": reply}
                        await ws.send(json.dumps(llm_msg, ensure_ascii=False))
                    except:
                        pass

            session.audio_buffer = bytearray()  # reset
            session.state = "idle"

        elif state == "detect":
            # 喚醒詞檢測到
            print(f"  🎤 喚醒詞: {text}")
            # 模擬對話
            await self._simulate_conversation(ws, session, text)

    async def _on_abort(self, ws, data: dict, session: Session | None):
        """處理 abort"""
        reason = data.get("reason", "unknown")
        print(f"  ⏹️ 中止: {reason}")
        if session:
            session.state = "idle"

    async def _on_mcp(self, ws, data: dict, session: Session | None):
        """處理 MCP JSON-RPC"""
        if not session:
            return

        payload = data.get("payload", {})
        method = payload.get("method", "")
        msg_id = payload.get("id", 0)

        if method == "tools/list":
            # 回傳工具列表
            await self._send_mcp_tools_list(ws, session, msg_id)

        elif method == "tools/call":
            # 執行工具調用
            params = payload.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = await self._execute_mcp_tool(tool_name, arguments, session)
            await self._send_mcp_result(ws, session, msg_id, result)

    async def _on_iot(self, ws, data: dict, session: Session | None):
        """處理 IoT 消息 (舊協議)"""
        if not session:
            return
        print(f"  📡 IoT: {json.dumps(data, ensure_ascii=False)[:100]}")

    # ── 模擬對話流程 ─────────────────────────
    async def _simulate_conversation(self, ws, session: Session, user_text: str):
        """
        模擬完整對話流程: ASR → LLM → TTS
        實際部署時替換為真實 API 調用。
        """
        # 1. STT 結果
        stt_text, emotion, reply = await self._generate_response(user_text, session)

        # 發送 STT
        stt_msg = {
            "session_id": session.session_id,
            "type": "stt",
            "text": stt_text,
        }
        await ws.send(json.dumps(stt_msg, ensure_ascii=False))
        await asyncio.sleep(0.2)
        print(f"  📝 [stt] → {stt_text}")

        # 2. LLM 情緒
        llm_msg = {
            "session_id": session.session_id,
            "type": "llm",
            "emotion": emotion,
            "text": {"happy": "😀", "neutral": "😐", "thinking": "🤔", "love": "🥰", "sad": "😢"}.get(emotion, "😐"),
        }
        await ws.send(json.dumps(llm_msg, ensure_ascii=False))
        await asyncio.sleep(0.1)

        # 3. TTS 開始
        tts_start = {
            "session_id": session.session_id,
            "type": "tts",
            "state": "start",
        }
        await ws.send(json.dumps(tts_start, ensure_ascii=False))

        # 逐句發送 (模擬流式)
        sentences = reply.split("\n")
        for i, sentence in enumerate(sentences):
            if not sentence.strip():
                continue
            tts_sentence = {
                "session_id": session.session_id,
                "type": "tts",
                "state": "sentence_start",
                "text": sentence.strip(),
            }
            await ws.send(json.dumps(tts_sentence, ensure_ascii=False))
            # 模擬語音播放延遲
            await asyncio.sleep(len(sentence) * 0.03)

        # 4. TTS 結束
        await asyncio.sleep(0.2)
        tts_stop = {
            "session_id": session.session_id,
            "type": "tts",
            "state": "stop",
        }
        await ws.send(json.dumps(tts_stop, ensure_ascii=False))
        print(f"  🤖 [tts] → {reply[:60]}...")

        # 記錄對話
        session.chat_history.append({"role": "user", "text": user_text})
        session.chat_history.append({"role": "assistant", "text": reply})

    # ── MCP 處理 ──────────────────────────────
    async def _send_mcp_tools_list(self, ws, session: Session, msg_id: int = 0):
        """發送 MCP 工具列表"""
        tools = []
        for name, info in self.mcp_tools.items():
            tools.append({
                "name": name,
                "description": info["description"],
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        k: {"type": "string", "description": v}
                        for k, v in info["parameters"].items()
                    },
                },
            })

        response = {
            "session_id": session.session_id,
            "type": "mcp",
            "payload": {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(tools, ensure_ascii=False)}
                    ],
                    "isError": False,
                },
            },
        }
        await ws.send(json.dumps(response, ensure_ascii=False))
        print(f"  🔧 [mcp] → tools/list ({len(tools)} tools)")

    async def _execute_mcp_tool(self, tool_name: str, arguments: dict, session: Session) -> str:
        """執行 MCP 工具"""
        print(f"  🔧 執行工具: {tool_name}({arguments})")

        if tool_name == "self.led.set_rgb":
            r, g, b = arguments.get("r", 0), arguments.get("g", 0), arguments.get("b", 0)
            return f"LED 顏色已設為 RGB({r},{g},{b})"

        elif tool_name == "self.speaker.set_volume":
            vol = arguments.get("volume", 50)
            return f"音量已設為 {vol}%"

        elif tool_name == "self.servo.set_angle":
            sid = arguments.get("servo_id", 0)
            angle = arguments.get("angle", 90)
            return f"舵機 {sid} 角度已設為 {angle}°"

        elif tool_name == "self.gpio.set_level":
            pin = arguments.get("pin", 0)
            level = arguments.get("level", 0)
            return f"GPIO{pin} 設為 {'高' if level else '低'}電平"

        elif tool_name == "self.display.show_text":
            text = arguments.get("text", "")
            return f"顯示: '{text}'"

        elif tool_name == "self.camera.capture":
            return "已拍攝照片 (模擬)"

        elif tool_name == "weather.get_current":
            city = arguments.get("city", "台北")
            return f"{city} 天氣: 晴 ☀️ 28°C"

        elif tool_name == "knowledge.search":
            query = arguments.get("query", "")
            return f"搜索 '{query}': 找到 3 條相關結果"

        return f"未知工具: {tool_name}"

    async def _send_mcp_result(self, ws, session: Session, msg_id: int, result: str):
        """發送 MCP 執行結果"""
        response = {
            "session_id": session.session_id,
            "type": "mcp",
            "payload": {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {"type": "text", "text": result}
                    ],
                    "isError": False,
                },
            },
        }
        await ws.send(json.dumps(response, ensure_ascii=False))
        print(f"  🔧 [mcp] → result: {result}")

    # ── 伺服器生命週期 ───────────────────────
    async def start(self):
        """啟動伺服器"""
        print(f"""
╔══════════════════════════════════════════════════╗
║     🤖  小智本地伺服器  🤖                       ║
║     XiaoZhi Local Server                         ║
║                                                  ║
║     協議: WebSocket v1/v2/v3                     ║
║     MCP:   JSON-RPC 2.0                          ║
║     基於: xinnan-tech/xiaozhi-esp32-server       ║
║                                                  ║
║     🟢 ws://{self.host}:{self.port}/xiaozhi/v1/         ║
║     🔧 MCP 工具: {len(self.mcp_tools)} 個                    ║
╚══════════════════════════════════════════════════╝
""")

        # 同時啟動 ASR HTTP 伺服器 (port + 3)
        asr_task = asyncio.create_task(self._start_asr_server())

        async with serve(
            self.handle_connection,
            self.host,
            self.port,
            process_request=self._process_request,
        ):
            print("✅ 伺服器已啟動 — 等待設備連接...")
            print("   WebSocket: ws://{}:{}/xiaozhi/v1/".format(self.host, self.port))
            print("   ASR API:   http://{}:{}/api/asr".format(self.host, self.port + 3))
            print()
            await asyncio.Event().wait()

    async def _start_asr_server(self):
        """啟動獨立 ASR HTTP 伺服器 (port+3)，處理 POST 音頻上傳"""
        asr_port = self.port + 3

        async def handle_asr(reader, writer):
            try:
                # 讀取 HTTP 請求
                request_data = await asyncio.wait_for(reader.read(256000), timeout=15)
                request_text = request_data.decode("utf-8", errors="replace")

                # 解析 multipart 或 raw body
                if "Content-Type: application/json" in request_text or '"audio"' in request_text:
                    # JSON body
                    body_start = request_text.find("\r\n\r\n") + 4
                    body = request_text[body_start:]
                    data = json.loads(body)
                    audio_b64 = data.get("audio", "")
                    lang = data.get("language", "yue")
                else:
                    # 直接 binary body
                    body_start = request_text.find("\r\n\r\n") + 4
                    audio_b64 = request_text[body_start:].strip()
                    lang = "yue"

                if not audio_b64:
                    writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\nmissing audio")
                    await writer.drain()
                    writer.close()
                    return

                # Base64 解碼
                import base64
                audio_bytes = base64.b64decode(audio_b64)

                # 調用 DashScope ASR (如果有)
                if self.asr:
                    result = self.asr.recognize_bytes_sync(audio_bytes, "wav", lang)
                    text = result.get("text", "")
                else:
                    text = "[ASR 未啟用]"

                resp = json.dumps({"text": text, "language": lang}, ensure_ascii=False)
                writer.write(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{}".format(
                        len(resp.encode()), resp
                    ).encode()
                )
                await writer.drain()

            except Exception as e:
                err = json.dumps({"error": str(e)})
                writer.write(
                    "HTTP/1.1 500 Error\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{}".format(
                        len(err.encode()), err
                    ).encode()
                )
                await writer.drain()
            finally:
                writer.close()

        server = await asyncio.start_server(handle_asr, self.host, asr_port)
        print("   ASR 伺服器已啟動 — port {}".format(asr_port))
        async with server:
            await server.serve_forever()

    def _log(self, msg):
        """帶時間戳的 log"""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        print("[{}] {}".format(ts, msg), flush=True)

    async def _process_request(self, connection, request):
        """處理 HTTP 請求 — WebSocket 升級 + REST API"""
        from urllib.parse import urlparse, parse_qs
        path = request.path
        peer = request.headers.get("X-Forwarded-For", connection.remote_address[0] if connection.remote_address else "?")
        self._log("REQ GET {} from {}".format(path, peer))

        # WebSocket 路徑：接受升級
        if path.startswith("/xiaozhi/") or path == "/ws":
            return None

        # 解析 URL
        parsed = urlparse(path)
        clean_path = parsed.path
        params = parse_qs(parsed.query)

        # ── REST API (MicroPython / CyberPi 用) ──
        # GET /api/chat?text=...&device_id=... (MicroPython 友好)
        if clean_path == "/api/asr" and request.method == "POST":
            return await self._handle_api_asr(connection, request)
        if clean_path == "/api/chat":
            return await self._handle_api_chat(connection, request, params)
        if clean_path == "/api/ping":
            return connection.respond(200, "pong")
        if clean_path == "/api/tts":
            return await self._handle_api_tts(connection, request, params)
        if clean_path == "/api/status":
            return await self._handle_api_status(connection, request)
        if clean_path == "/api/mcp/tools":
            return await self._handle_api_mcp_tools(connection, request)
        if clean_path == "/" or clean_path == "/index.html":
            return await self._handle_index(connection, request)

        return connection.respond(404, "Not Found")

    async def _handle_api_chat(self, connection, request, params: dict):
        """GET /api/chat?text=... — 文字對話 (MicroPython 用 GET 參數)"""
        try:
            user_text = params.get("text", [""])[0]
            if not user_text:
                return connection.respond(400, json.dumps({"error": "缺少 text 參數"}))

            # 建立臨時 session
            device_id = params.get("device_id", [f"http-{uuid.uuid4().hex[:8]}"])[0]
            temp_session = Session(device_id, uuid.uuid4().hex[:8])

            # 生成回應
            stt_text, emotion, reply = await self._generate_response(user_text, temp_session)

            result = {
                "text": reply,
                "emotion": emotion,
                "stt_text": stt_text,
            }
            # sanitize + json encode
            for key in result:
                if isinstance(result[key], str):
                    result[key] = result[key].encode("utf-8", errors="replace").decode("utf-8")
            return connection.respond(200, json.dumps(result, ensure_ascii=False))
        except Exception as e:
            return connection.respond(500, json.dumps({"error": str(e)}))

    async def _handle_api_tts(self, connection, request, params: dict):
        """GET /api/tts?text=... — 廣東話 TTS (EdgeTTS zh-HK)"""
        try:
            text = params.get("text", [""])[0]
            if not text:
                return connection.respond(400, "missing text")

            import subprocess
            import base64

            # 生成 TTS 音頻
            tmpfile = "/tmp/xiaozhi_tts_{}.mp3".format(os.getpid())
            result = subprocess.run(
                [
                    "python3", "-m", "edge_tts",
                    "--voice", "zh-HK-HiuGaaiNeural",
                    "--text", text,
                    "--write-media", tmpfile,
                ],
                capture_output=True,
                timeout=15,
            )

            if result.returncode != 0:
                return connection.respond(500, "TTS failed")

            with open(tmpfile, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode("ascii")

            os.unlink(tmpfile)

            # 返回 base64 編碼的音頻 (MicroPython 可以解碼)
            return connection.respond(200, audio_b64)

        except Exception as e:
            return connection.respond(500, str(e))

    async def _handle_api_status(self, connection, request):
        """GET /api/status — 伺服器狀態"""
        uptime = (datetime.now() - self.start_time).total_seconds()
        status = {
            "server": "xiaozhi-esp32-server",
            "version": "2.2.6",
            "uptime_seconds": uptime,
            "active_sessions": len(self.sessions),
            "llm_engine": "千問 qwen-turbo" if self.llm else "模擬模式",
            "asr_engine": "Paraformer-v2 (廣東話/粵語)" if self.asr else "未啟用",
            "mcp_tools": len(self.mcp_tools),
            "protocols": ["websocket", "mqtt", "rest"],
        }
        return connection.respond(200, json.dumps(status, ensure_ascii=False))

    async def _handle_api_mcp_tools(self, connection, request):
        """GET /api/mcp/tools — MCP 工具列表"""
        tools = []
        for name, info in self.mcp_tools.items():
            tools.append({
                "name": name,
                "description": info["description"],
                "parameters": info["parameters"],
            })
        return connection.respond(200, json.dumps(tools, ensure_ascii=False))

    async def _handle_index(self, connection, request):
        """GET / — CyberPi 友好頁面"""
        html = """<!DOCTYPE html>
<html lang="zh-HK">
<head><meta charset="UTF-8"><title>小智 AI 伺服器</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:-apple-system,sans-serif;max-width:600px;margin:40px auto;padding:20px;background:#1a1a2e;color:#e0e0ff}
.box{background:#16213e;border-radius:12px;padding:20px;margin:12px 0;border:1px solid #0f3460}
h1{color:#e94560;text-align:center} h2{color:#0f9bff}
code{background:#0f3460;padding:2px 8px;border-radius:4px;font-size:14px}
.endpoint{color:#ffd700} .method{color:#4ecca3}
</style></head>
<body>
<h1>🤖 小智 AI 伺服器</h1>
<div class="box">
<h2>📡 端點</h2>
<p><span class="method">GET</span> <code class="endpoint">/api/chat?text=...</code> — 廣東話對話</p>
<p><span class="method">GET</span> <code class="endpoint">/api/status</code> — 伺服器狀態</p>
<p><span class="method">GET</span> <code class="endpoint">/api/mcp/tools</code> — MCP 工具</p>
</div>
<div class="box">
<h2>🐍 CyberPi MicroPython</h2>
<pre><code>import urequests
r = urequests.get("http://IP:8000/api/chat",
    params={"text":"你好小智","device_id":"cyberpi"})
print(r.json()["text"])</code></pre>
</div>
<p style="text-align:center;color:#666;font-size:12px">CyberPi Ready 🎮</p>
</body></html>"""
        return connection.respond(200, html)


# ── CLI ──────────────────────────────────────────
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="小智本地伺服器 | XiaoZhi Local Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  python xiaozhi_server.py                  # 預設 :8000
  python xiaozhi_server.py --port 9000      # 自訂端口
  python xiaozhi_server.py --host 127.0.0.1 # 僅本地

連接:
  ws://localhost:8000/xiaozhi/v1/
        """,
    )
    parser.add_argument("--host", default="0.0.0.0", help="監聽地址 (預設: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="監聽端口 (預設: 8000)")
    parser.add_argument("--llm", action="store_true", help="啟用千問 LLM API (需設定 QWEN_API_KEY)")
    args = parser.parse_args()

    if not HAS_WEBSOCKETS:
        print("請安裝 websockets: pip install websockets")
        sys.exit(1)

    server = XiaoZhiServer(host=args.host, port=args.port, use_llm=args.llm)

    # 信號處理
    def shutdown(sig, frame):
        print("\n🛑 正在關閉伺服器...")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\n👋 伺服器已關閉")


if __name__ == "__main__":
    main()
