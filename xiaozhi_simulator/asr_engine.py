#!/usr/bin/env python3
"""
小智語音識別引擎 | XiaoZhi ASR Engine
======================================
基於阿里雲百煉 DashScope Paraformer API，支援廣東話 (粵語)。

模型: paraformer-v2
語言: zh (普通話), yue (廣東話/粵語), en (英文), ja (日文), ko (韓文)
"""

import os
import json
import base64
import asyncio
from pathlib import Path
from typing import Optional

# ── 嘗試匯入 HTTP 客戶端 ──────────────────────────
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class DashScopeASR:
    """阿里雲百煉 Qwen3-ASR-Flash 語音識別 (支援廣東話)"""

    # 國際版 endpoint (新加坡) — OpenAI 兼容
    BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"

    # 支援的語言
    LANGUAGES = {
        "zh": "普通話 (Chinese Mandarin)",
        "yue": "廣東話 (Cantonese)",
        "en": "英文 (English)",
        "ja": "日文 (Japanese)",
        "ko": "韓文 (Korean)",
        "auto": "自動檢測",
    }

    def __init__(self, api_key: str = None, language: str = "yue"):
        self.api_key = api_key or os.environ.get("QWEN_API_KEY", "")
        self.language = language  # 預設廣東話
        self._session = None

    async def _get_session(self):
        """獲取或建立 HTTP session"""
        if self._session is None:
            if HAS_AIOHTTP:
                import aiohttp
                self._session = aiohttp.ClientSession()
            elif HAS_HTTPX:
                import httpx
                self._session = httpx.AsyncClient()
        return self._session

    async def recognize_file(self, audio_path: str, language: str = None) -> dict:
        """
        識別音頻文件。

        Args:
            audio_path: 音頻文件路徑 (支援 wav, mp3, opus, pcm 等)
            language: 語言代碼 (zh/yue/en/ja/ko/auto)，預設使用實例語言

        Returns:
            {"text": "識別文字", "language": "yue", "confidence": 0.95}
        """
        lang = language or self.language

        # 讀取音頻並轉 base64
        with open(audio_path, "rb") as f:
            audio_data = base64.b64encode(f.read()).decode("utf-8")

        # 獲取文件擴展名以判斷格式
        ext = Path(audio_path).suffix.lower().lstrip(".")
        format_map = {
            "wav": "wav",
            "mp3": "mp3",
            "opus": "opus",
            "ogg": "ogg",
            "pcm": "pcm",
            "m4a": "m4a",
            "flac": "flac",
        }
        audio_format = format_map.get(ext, "wav")

        return await self._call_api(audio_data, audio_format, lang)

    async def recognize_bytes(self, audio_bytes: bytes, audio_format: str = "wav",
                              language: str = None) -> dict:
        """識別音頻位元組數據"""
        lang = language or self.language
        audio_data = base64.b64encode(audio_bytes).decode("utf-8")
        return await self._call_api(audio_data, audio_format, lang)

    async def _call_api(self, audio_base64: str, audio_format: str, language: str) -> dict:
        """調用 DashScope Qwen3-ASR-Flash API"""
        headers = {
            "Authorization": "Bearer {}".format(self.api_key),
            "Content-Type": "application/json",
        }

        payload = {
            "model": "qwen3-asr-flash",
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "input_audio",
                    "input_audio": {
                        "data": "data:audio/{};base64,{}".format(audio_format, audio_base64)
                    }
                }]
            }],
            "asr_options": {
                "language": language,
                "enable_itn": True,
            }
        }

        session = await self._get_session()

        if HAS_AIOHTTP:
            import aiohttp
            async with session.post(self.BASE_URL, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                result = await resp.json()
        elif HAS_HTTPX:
            import httpx
            resp = await session.post(self.BASE_URL, headers=headers, json=payload, timeout=30.0)
            result = resp.json()
        else:
            # 降級到同步 requests
            import requests
            resp = requests.post(self.BASE_URL, headers=headers, json=payload, timeout=30)
            result = resp.json()

        return self._parse_response(result, language)

    def recognize_bytes_sync(self, audio_bytes: bytes, audio_format: str = "wav",
                              language: str = None) -> dict:
        """同步識別音頻位元組"""
        import requests
        import base64 as b64

        lang = language or self.language
        audio_data = b64.b64encode(audio_bytes).decode("utf-8")

        headers = {
            "Authorization": "Bearer {}".format(self.api_key),
            "Content-Type": "application/json",
        }
        payload = {
            "model": "qwen3-asr-flash",
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "input_audio",
                    "input_audio": {
                        "data": "data:audio/{};base64,{}".format(audio_format, audio_data)
                    }
                }]
            }],
            "asr_options": {"language": lang, "enable_itn": True}
        }
        resp = requests.post(self.BASE_URL, headers=headers, json=payload, timeout=30)
        return self._parse_response(resp.json(), lang)

    def recognize_file_sync(self, audio_path: str, language: str = None) -> dict:
        """同步版本 (降級用)"""
        lang = language or self.language

        with open(audio_path, "rb") as f:
            audio_data = base64.b64encode(f.read()).decode("utf-8")

        ext = Path(audio_path).suffix.lower().lstrip(".")
        format_map = {"wav": "wav", "mp3": "mp3", "opus": "opus", "ogg": "ogg", "pcm": "pcm", "m4a": "m4a", "flac": "flac"}
        audio_format = format_map.get(ext, "wav")

        import requests
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "paraformer-v2",
            "input": {"audio": f"data:audio/{audio_format};base64,{audio_data}"},
            "parameters": {"language_hints": [lang], "enable_itn": True},
        }
        resp = requests.post(self.BASE_URL, headers=headers, json=payload, timeout=30)
        return self._parse_response(resp.json(), lang)

    def _parse_response(self, response: dict, language: str) -> dict:
        """解析 Qwen3-ASR-Flash API 回應"""
        # 檢查錯誤
        if "error" in response:
            error_msg = response.get("error", {}).get("message", "Unknown error")
            print("⚠️ ASR API 錯誤: {}".format(error_msg))
            return {"text": "", "language": language, "confidence": 0, "error": error_msg}

        # OpenAI 兼容格式
        choices = response.get("choices", [])
        if not choices:
            return {"text": "", "language": language, "confidence": 0}

        msg = choices[0].get("message", {})
        text = msg.get("content", "")

        # 從 annotations 取語言
        annotations = msg.get("annotations", [])
        detected_lang = language
        for a in annotations:
            if a.get("type") == "audio_info":
                detected_lang = a.get("language", language)
                break

        return {
            "text": text.strip(),
            "language": detected_lang,
            "confidence": 0.95,
        }

    async def close(self):
        """關閉 HTTP session"""
        if self._session:
            await self._session.close()
            self._session = None


# ── 快速測試 ──────────────────────────────────────────
def generate_test_audio(output_path: str = "test_cantonese.wav", text: str = "你好，請問今日天氣點樣"):
    """生成測試用的 WAV 音頻文件 (用於測試 ASR)"""
    import wave
    import struct
    import math

    sample_rate = 16000
    duration = 2.0  # 2 秒
    frequency = 440  # A4 音 (替代真實語音)

    with wave.open(output_path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        for i in range(int(sample_rate * duration)):
            value = int(32767 * 0.3 * math.sin(2 * math.pi * frequency * i / sample_rate))
            wf.writeframes(struct.pack("<h", value))

    print(f"測試音頻已生成: {output_path}")
    return output_path


if __name__ == "__main__":
    import sys

    api_key = os.environ.get("QWEN_API_KEY", "")
    if not api_key:
        print("❌ 請設定 QWEN_API_KEY 環境變數")
        sys.exit(1)

    asr = DashScopeASR(api_key=api_key, language="yue")

    # 使用命令行參數指定的音頻文件
    if len(sys.argv) > 1:
        audio_file = sys.argv[1]
    else:
        audio_file = generate_test_audio()

    result = asr.recognize_file_sync(audio_file)
    print(json.dumps(result, ensure_ascii=False, indent=2))
