# cyberpi_xiaozhi.py
# ===================
# 小智 AI 智能體 — CyberPi MicroPython 版
# 使用 HTTP REST API 連接到小智伺服器
#
# 上傳到 CyberPi 後運行：
#   1. 修改 WIFI_SSID / WIFI_PASSWORD / SERVER_IP
#   2. 按 A 鍵發送廣東話問候
#   3. 按 B 鍵循環預設問題
#   4. 用搖桿上下選擇功能
#
# 依賴: urequests (CyberPi 內建)

import time
import json

# CyberPi 模組 (只在實機上可用)
try:
    import cyberpi
    import urequests
    ON_CYBERPI = True
except ImportError:
    ON_CYBERPI = False
    # 桌面模擬用
    import requests as _requests

# ═══════════════════════════════════════════════════
# 設定 — 修改這裡
# ═══════════════════════════════════════════════════
WIFI_SSID = "casey"
WIFI_PASSWORD = "aabbccddee"
SERVER_IP = "192.168.0.194"  # 小智伺服器 IP
SERVER_PORT = 8000
DEVICE_ID = "cyberpi-01"

SERVER_URL = f"http://{SERVER_IP}:{SERVER_PORT}"

# ═══════════════════════════════════════════════════
# 預設問題 (廣東話)
# ═══════════════════════════════════════════════════
QUESTIONS = [
    "你好，用廣東話介紹下自己",
    "今日天氣點樣？",
    "講個笑話聽下",
    "香港有咩好玩嘅地方？",
    "用廣東話教我一句日常用語",
    "你識做啲咩？",
    "開燈",
    "而家幾點？",
]

# ═══════════════════════════════════════════════════
# 表情對照
# ═══════════════════════════════════════════════════
EMOTION_FACES = {
    "happy": "😊",
    "neutral": "😐",
    "thinking": "🤔",
    "love": "🥰",
    "sad": "😢",
    "surprised": "😲",
}


# ═══════════════════════════════════════════════════
# 核心函數
# ═══════════════════════════════════════════════════

def _http_get(url):
    """跨平台 HTTP GET (CyberPi urequests / 桌面 requests)"""
    if ON_CYBERPI:
        r = urequests.get(url)
        data = r.json()
        r.close()
        return data
    else:
        import requests
        r = requests.get(url)
        return r.json()

def connect_wifi():
    """連接 WiFi"""
    cyberpi.display.show_label("🔗 WiFi...", 16, 20, 16)
    cyberpi.display.show_label(WIFI_SSID, 16, 45, 12)

    try:
        cyberpi.wifi.connect(WIFI_SSID, WIFI_PASSWORD)
        time.sleep(2)

        if cyberpi.wifi.is_connected():
            ip = cyberpi.wifi.get_ip()
            cyberpi.display.show_label("✅ WiFi OK!", 16, 20, 16)
            cyberpi.display.show_label(ip, 16, 45, 12)
            cyberpi.led.on(0, 255, 0)  # 綠燈
            time.sleep(1)
            return True
        else:
            raise Exception("WiFi fail")
    except Exception as e:
        cyberpi.display.show_label("❌ WiFi 失敗", 16, 20, 16)
        cyberpi.display.show_label(str(e)[:20], 16, 45, 8)
        cyberpi.led.on(255, 0, 0)  # 紅燈
        time.sleep(3)
        return False


def check_server():
    """檢查伺服器狀態"""
    try:
        return _http_get(f"{SERVER_URL}/api/status")
    except Exception:
        return None


def chat(text):
    """發送文字到小智伺服器，取得回應"""
    try:
        # URL 編碼 (簡化版，處理常見符號)
        encoded = text.replace(" ", "%20").replace("?", "%3F").replace("&", "%26")
        url = f"{SERVER_URL}/api/chat?text={encoded}&device_id={DEVICE_ID}"
        return _http_get(url)
    except Exception as e:
        return {"text": f"錯誤: {e}", "emotion": "sad"}


def show_response(question, response):
    """在 CyberPi 螢幕上顯示回應"""
    cyberpi.display.clear()

    reply_text = response.get("text", "無回應")
    emotion = response.get("emotion", "neutral")
    face = EMOTION_FACES.get(emotion, "🤖")

    # 第一行：表情 + 問題摘要
    q_short = question[:18] + ".." if len(question) > 18 else question
    cyberpi.display.show_label(f"{face} {q_short}", 2, 2, 10)

    # 分隔線
    cyberpi.display.show_label("-" * 24, 2, 16, 8)

    # 回應文字 (自動換行)
    lines = wrap_text(reply_text, 22)
    y = 28
    for line in lines[:6]:  # 最多 6 行
        cyberpi.display.show_label(line, 2, y, 10)
        y += 16

    # 底部提示
    cyberpi.display.show_label("A:再問 B:下一題", 2, 110, 8)

    # LED 表情
    if emotion == "happy":
        cyberpi.led.on(0, 255, 0)
    elif emotion == "thinking":
        cyberpi.led.on(255, 255, 0)
    elif emotion == "sad":
        cyberpi.led.on(255, 0, 0)
    else:
        cyberpi.led.on(0, 100, 255)


def wrap_text(text, max_chars):
    """簡單文字換行"""
    lines = []
    current = ""
    for char in text:
        current += char
        if len(current) >= max_chars:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)
    return lines if lines else [text]


def show_welcome():
    """顯示歡迎畫面"""
    cyberpi.display.clear()
    cyberpi.display.show_label("🤖 小智 AI", 24, 10, 20)
    cyberpi.display.show_label("CyberPi Edition", 16, 35, 12)
    cyberpi.display.show_label("廣東話智能體", 16, 52, 14)
    cyberpi.display.show_label("A:開始 B:狀態", 16, 80, 10)
    cyberpi.led.on(0, 150, 255)


def show_status(status):
    """顯示伺服器狀態"""
    cyberpi.display.clear()
    if status:
        cyberpi.display.show_label("🟢 伺服器在線", 16, 5, 16)
        cyberpi.display.show_label(f"LLM: {status.get('llm_engine','?')[:18]}", 2, 28, 10)
        cyberpi.display.show_label(f"ASR: {status.get('asr_engine','?')[:18]}", 2, 42, 10)
        cyberpi.display.show_label(f"Session: {status.get('active_sessions',0)}", 2, 56, 10)
        cyberpi.display.show_label(f"工具: {status.get('mcp_tools',0)} 個", 2, 70, 10)
    else:
        cyberpi.display.show_label("🔴 伺服器離線", 16, 30, 18)
        cyberpi.display.show_label("請檢查網絡", 20, 55, 12)
    cyberpi.display.show_label("A:返回", 16, 100, 10)
    cyberpi.led.on(100, 100, 255)


def show_loading(msg="載入中..."):
    """顯示載入畫面"""
    cyberpi.display.clear()
    cyberpi.display.show_label("⏳", 48, 25, 30)
    cyberpi.display.show_label(msg, 20, 60, 14)
    cyberpi.led.on(255, 200, 0)


# ═══════════════════════════════════════════════════
# 主程式
# ═══════════════════════════════════════════════════

def main():
    """CyberPi 小智 AI 主程式"""
    cyberpi.display.clear()
    cyberpi.display.show_label("小智 AI", 30, 30, 20)
    cyberpi.display.show_label("啟動中...", 24, 55, 14)
    time.sleep(0.5)

    # 連接 WiFi
    if not connect_wifi():
        cyberpi.display.show_label("重啟 CyberPi", 16, 55, 14)
        return

    show_welcome()

    # 狀態變數
    question_index = 0
    screen = "welcome"  # welcome, chat, status
    last_response = None
    last_question = ""

    # 主循環
    while True:
        # ── 按鍵處理 ──
        # A 鍵：執行主要動作
        if cyberpi.is_press("a"):
            cyberpi.audio.play_music("button")
            time.sleep(0.2)

            if screen == "welcome":
                # 開始對話
                screen = "chat"
                question_index = 0
                show_loading("問緊小智...")

                q = QUESTIONS[question_index]
                result = chat(q)
                last_response = result
                last_question = q
                show_response(q, result)
                time.sleep(0.5)

            elif screen == "status":
                screen = "welcome"
                show_welcome()
                time.sleep(0.3)

            elif screen == "chat":
                # 再問同一個問題
                show_loading("再問一次...")
                q = last_question or QUESTIONS[question_index]
                result = chat(q)
                last_response = result
                show_response(q, result)
                time.sleep(0.3)

        # B 鍵：次要動作
        if cyberpi.is_press("b"):
            cyberpi.audio.play_music("button")
            time.sleep(0.2)

            if screen == "welcome":
                # 顯示狀態
                screen = "status"
                show_loading("檢查伺服器...")
                status = check_server()
                show_status(status)
                time.sleep(0.3)

            elif screen == "chat":
                # 下一題
                question_index = (question_index + 1) % len(QUESTIONS)
                show_loading("問緊小智...")

                q = QUESTIONS[question_index]
                result = chat(q)
                last_response = result
                last_question = q
                show_response(q, result)
                time.sleep(0.3)

            elif screen == "status":
                screen = "welcome"
                show_welcome()
                time.sleep(0.3)

        # ── 搖桿上下：選擇問題 ──
        joy_y = cyberpi.get_joystick("y")
        if abs(joy_y) > 50 and screen == "chat":
            time.sleep(0.2)
            if joy_y > 50:
                question_index = (question_index - 1) % len(QUESTIONS)
            else:
                question_index = (question_index + 1) % len(QUESTIONS)

            show_loading("問緊小智...")
            q = QUESTIONS[question_index]
            result = chat(q)
            last_response = result
            last_question = q
            show_response(q, result)

        # ── 搖桿按下：返回主頁 ──
        if cyberpi.is_press("middle"):
            cyberpi.audio.play_music("button")
            screen = "welcome"
            show_welcome()
            time.sleep(0.3)

        time.sleep(0.1)


# ═══════════════════════════════════════════════════
# 桌面模擬模式 (開發測試用，在電腦上跑)
# ═══════════════════════════════════════════════════

def desktop_sim():
    """
    桌面模擬模式 — 在電腦上測試 CyberPi 邏輯。
    """
    print(f"伺服器: {SERVER_URL}")

    # 測試 API
    try:
        status = _http_get(f"{SERVER_URL}/api/status")
        print(f"伺服器狀態: {json.dumps(status, ensure_ascii=False)}")
    except Exception as e:
        print(f"無法連接伺服器: {e}")
        return

    print("\n── 預設問題測試 (廣東話) ──")
    for i, q in enumerate(QUESTIONS[:5]):
        print(f"\n🧑 Q{i+1}: {q}")
        try:
            resp = chat(q)
            emotion = resp.get("emotion", "neutral")
            face = EMOTION_FACES.get(emotion, "🤖")
            print(f"🤖 {face}: {resp['text'][:150]}")
        except Exception as e:
            print(f"❌ 錯誤: {e}")

    print("\n✅ 桌面模擬完成！")


# ═══════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    # 自動檢測運行環境
    try:
        import cyberpi
        # CyberPi 實機模式
        main()
    except ImportError:
        # 桌面模擬模式
        print("=" * 50)
        print("  小智 AI — CyberPi 桌面模擬器")
        print("=" * 50)
        print()
        print("在 CyberPi 上運行時:")
        print("  1. 修改 WIFI_SSID / WIFI_PASSWORD / SERVER_IP")
        print("  2. 上傳此檔案到 CyberPi")
        print("  3. 重啟 CyberPi")
        print()
        desktop_sim()
