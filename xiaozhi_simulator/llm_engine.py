#!/usr/bin/env python3
"""
小智 LLM 引擎 | XiaoZhi LLM Engine
===================================
基於阿里雲百煉 DashScope 千問 (Qwen) API。

模型: qwen-turbo / qwen-plus / qwen-max
支援: 廣東話、普通話、英文等多語言對話
"""

import os
import json
import asyncio
from typing import Optional, AsyncGenerator


class QwenLLM:
    """阿里雲百煉 千問 LLM (支援廣東話)"""

    # 國際版 endpoint (新加坡, OpenAI 兼容)
    BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"

    # 可用模型
    MODELS = {
        "qwen-turbo": "快速便宜，適合簡單對話",
        "qwen-plus": "平衡性能與成本",
        "qwen-max": "最強能力，適合複雜任務",
        "qwen3-235b-a22b": "Qwen3 最新",
    }

    def __init__(self, api_key: str = None, model: str = "qwen-turbo"):
        self.api_key = api_key or os.environ.get("QWEN_API_KEY", "")
        self.model = model
        self._session = None

    async def _get_session(self):
        """獲取 HTTP session"""
        if self._session is None:
            try:
                import aiohttp
                self._session = aiohttp.ClientSession()
            except ImportError:
                import httpx
                self._session = httpx.AsyncClient()
        return self._session

    async def chat(self, messages: list, system_prompt: str = None,
                   temperature: float = 0.7, max_tokens: int = 512) -> str:
        """
        發送對話請求。

        Args:
            messages: [{"role": "user", "content": "..."}]
            system_prompt: 系統提示詞
            temperature: 溫度 (0-2)
            max_tokens: 最大輸出 token

        Returns:
            模型回應文字
        """
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": full_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        session = await self._get_session()

        try:
            import aiohttp
            async with session.post(self.BASE_URL, headers=headers, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=30)) as resp:
                result = await resp.json()
        except ImportError:
            import httpx
            resp = await session.post(self.BASE_URL, headers=headers, json=payload, timeout=30.0)
            result = resp.json()

        # 解析回應
        if "choices" in result:
            return result["choices"][0]["message"]["content"]
        elif "error" in result:
            error_msg = result.get("error", {}).get("message", "Unknown error")
            print(f"⚠️ LLM API 錯誤: {error_msg}")
            return f"[錯誤] {error_msg}"
        else:
            return "[錯誤] 無法解析 API 回應"

    async def chat_stream(self, messages: list, system_prompt: str = None) -> AsyncGenerator[str, None]:
        """流式對話"""
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": full_messages,
            "temperature": 0.7,
            "max_tokens": 512,
            "stream": True,
        }

        session = await self._get_session()

        if "aiohttp" in str(type(session)).lower():
            import aiohttp
            async with session.post(self.BASE_URL, headers=headers, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=30)) as resp:
                async for line in resp.content:
                    line = line.decode("utf-8").strip()
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            chunk = json.loads(line[6:])
                            delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if delta:
                                yield delta
                        except json.JSONDecodeError:
                            continue
        else:
            # httpx 降級到非流式
            result = await self.chat(messages, system_prompt)
            yield result

    def chat_sync(self, messages: list, system_prompt: str = None,
                  temperature: float = 0.7, max_tokens: int = 512) -> str:
        """同步版本 (降級用)"""
        import requests

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": full_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = requests.post(self.BASE_URL, headers=headers, json=payload, timeout=30)
        result = resp.json()

        if "choices" in result:
            return result["choices"][0]["message"]["content"]
        else:
            error_msg = result.get("error", {}).get("message", "Unknown error")
            return f"[錯誤] {error_msg}"

    async def close(self):
        """關閉 session"""
        if self._session:
            await self._session.close()
            self._session = None


# ── 小智專用系統提示詞 (廣東話) ──────────────────────
XIAOZHI_SYSTEM_PROMPT = """你係「小智」，一個基於 ESP32 嘅 AI 聊天機械人。
你嘅性格友善、活潑、好樂意幫手。

重要規則：
- 用廣東話口語回應（唔好用書面語）
- 回答簡潔，盡量喺 2-3 句之內
- 可以加表情符號 😊🤖✨
- 如果用戶用普通話問，你就用普通話答
- 你嘅能力包括：
  • 語音對話
  • IoT 設備控制（LED、舵機、GPIO）
  • 天氣查詢
  • 講笑話
  • 一般知識問答
- 你可以用 MCP 協議控制硬件設備
- 回應要自然、流暢，似朋友傾偈咁
"""

XIAOZHI_SYSTEM_PROMPT_ZH = """你是「小智」，一个基于 ESP32 的 AI 聊天机器人。
你的性格友善、活泼、乐于助人。

重要规则：
- 用口语化中文回应
- 回答简洁，尽量在 2-3 句之内
- 可以加表情符号 😊🤖✨
- 如果用户用广东话问，你就用广东话答
- 你的能力包括：
  • 语音对话
  • IoT 设备控制（LED、舵机、GPIO）
  • 天气查询
  • 讲笑话
  • 一般知识问答
- 你可以用 MCP 协议控制硬件设备
- 回应要自然、流畅，像朋友聊天一样
"""


if __name__ == "__main__":
    import sys

    api_key = os.environ.get("QWEN_API_KEY", "")
    if not api_key:
        print("❌ 請設定 QWEN_API_KEY 環境變數")
        sys.exit(1)

    llm = QwenLLM(api_key=api_key, model="qwen-turbo")

    # 測試廣東話
    result = llm.chat_sync(
        messages=[{"role": "user", "content": "你好，用廣東話介紹下你自己"}],
        system_prompt=XIAOZHI_SYSTEM_PROMPT,
    )
    print("廣東話回應:")
    print(result)
    print()

    # 測試普通話
    result2 = llm.chat_sync(
        messages=[{"role": "user", "content": "你好，用普通话介绍一下你自己"}],
        system_prompt=XIAOZHI_SYSTEM_PROMPT_ZH,
    )
    print("普通話回應:")
    print(result2)
