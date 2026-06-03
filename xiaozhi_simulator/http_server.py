#!/usr/bin/env python3
"""小智 HTTP API 伺服器 — 支援 HTTP/1.0 (CyberPi urequests)"""
import json, os, sys, base64, subprocess, time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(__file__))
from llm_engine import QwenLLM, XIAOZHI_SYSTEM_PROMPT
from asr_engine import DashScopeASR

API_KEY = os.environ.get("QWEN_API_KEY", "")
llm = QwenLLM(api_key=API_KEY, model="qwen-turbo") if API_KEY else None
asr = DashScopeASR(api_key=API_KEY, language="yue") if API_KEY else None
print("🎤 ASR: qwen3-asr-flash (yue/zh)", flush=True) if asr else None

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        ts = datetime.now().strftime("%H:%M:%S")
        path = getattr(self, 'path', '?')
        print("[{}] {} {} from {}".format(ts, self.command, path, self.client_address[0]), flush=True)

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path)
        params = parse_qs(p.query)

        if p.path == "/api/asr" and p.query:
            # GET /api/asr?audio=BASE64&language=yue
            audio_b64 = params.get("audio",[""])[0]
            lang = params.get("language",["yue"])[0]
            if audio_b64 and asr:
                try:
                    audio = base64.b64decode(audio_b64)
                    result = asr.recognize_bytes_sync(audio, "wav", lang)
                    self._json(200, {"text":result.get("text",""),"language":lang})
                except Exception as e:
                    self._json(500, {"error":str(e)})
            else:
                self._json(400, {"error":"no audio"})

        elif p.path == "/api/ping":
            self._json(200, {"pong": True})

        elif p.path == "/api/status":
            self._json(200, {"server":"xiaozhi-http","llm":"千問 qwen-turbo" if llm else "mock","asr":"Paraformer-v2" if asr else "off","ok":True})

        elif p.path == "/api/chat":
            text = params.get("text",[""])[0]
            if not text:
                return self._json(400, {"error":"no text"})
            if llm:
                try:
                    reply = llm.chat_sync([{"role":"user","content":text}], system_prompt=XIAOZHI_SYSTEM_PROMPT)
                except:
                    reply = "伺服器忙碌，請稍後再試。"
            else:
                reply = "(模擬模式) 你好！我係小智。"
            self._json(200, {"text":reply, "emotion":"happy", "stt_text":text})

        elif p.path == "/api/tts":
            text = params.get("text",[""])[0]
            if not text:
                return self._json(400, {"error":"no text"})
            try:
                tmp = "/tmp/tts_{}.mp3".format(os.getpid())
                subprocess.run(["python3","-m","edge_tts","--voice","zh-HK-HiuGaaiNeural","--text",text,"--write-media",tmp],capture_output=True,timeout=15)
                with open(tmp,"rb") as f:
                    data = f.read()
                os.unlink(tmp)
                b64 = base64.b64encode(data).decode()
                self._json(200, {"audio":b64})
            except:
                self._json(500, {"error":"tts failed"})

        else:
            self._json(404, {"error":"not found"})

    def do_POST(self):
        if self.path.startswith("/api/asr"):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                # 試 JSON, base64 text, raw binary
                ct = self.headers.get("Content-Type","")
                if "json" in ct:
                    data = json.loads(body)
                    audio_b64 = data.get("audio","")
                    lang = data.get("language","yue")
                    audio = base64.b64decode(audio_b64)
                elif "octet" in ct:
                    lang = "yue"
                    audio = body
                else:
                    # 純文字 = base64 string
                    try:
                        audio = base64.b64decode(body.decode().strip())
                        lang = "yue"
                    except:
                        lang = "yue"
                        audio = body

                if asr:
                    result = asr.recognize_bytes_sync(audio, "wav", lang)
                    self._json(200, {"text":result.get("text",""),"language":lang})
                else:
                    self._json(200, {"text":"","language":lang})
            except Exception as e:
                self._json(500, {"error":str(e)})
        else:
            self._json(404, {"error":"not found"})

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv)>1 else 8000
    host = "0.0.0.0"
    print("🟢 小智 HTTP API: http://{}:{}".format(host, port), flush=True)
    print("   /api/ping /api/chat /api/status /api/tts", flush=True)
    HTTPServer((host, port), Handler).serve_forever()
