# cyberpi_xiaozhi03_debug.py
# ===========================
# 小智 AI CyberPi 精簡版 — 逐步測試
# 先確認每個 API 都能正常呼叫

import time

# ── 設定 ──
WIFI_SSID = "casey"
WIFI_PASSWORD = "aabbccddee"
SERVER_IP = "192.168.0.194"
SERVER_PORT = 8000
DEVICE_ID = "cyberpi-03"
SERVER_URL = "http://{}:{}".format(SERVER_IP, SERVER_PORT)

# ── 載入 CyberPi ──
try:
    import cyberpi
    import urequests
except ImportError:
    print("不是 CyberPi 環境")
    raise SystemExit

# ── 步驟 1: 清屏 + 顯示第一行 ──
def step1():
    cyberpi.display.clear()
    cyberpi.led.on(0, 0, 255)  # 藍燈
    cyberpi.display.show_label("小智 AI 啟動", 8, 40, 14)
    time.sleep(1.5)

# ── 步驟 2: 連接 WiFi ──
def step2():
    cyberpi.display.clear()
    cyberpi.display.show_label("WiFi 連接中...", 8, 30, 14)
    cyberpi.display.show_label(WIFI_SSID, 8, 50, 12)
    cyberpi.led.on(255, 255, 0)  # 黃燈

    try:
        cyberpi.wifi.connect(WIFI_SSID, WIFI_PASSWORD)
        for _ in range(10):  # 等最多 10 秒
            time.sleep(1)
            if cyberpi.wifi.is_connected():
                cyberpi.led.on(0, 255, 0)  # 綠燈
                ip = cyberpi.wifi.get_ip()
                cyberpi.display.clear()
                cyberpi.display.show_label("WiFi OK", 20, 20, 18)
                cyberpi.display.show_label(ip, 8, 45, 14)
                time.sleep(2)
                return True
        return False
    except Exception as e:
        cyberpi.display.clear()
        cyberpi.display.show_label("WiFi 失敗", 16, 40, 14)
        cyberpi.display.show_label(str(e)[:20], 4, 60, 10)
        cyberpi.led.on(255, 0, 0)  # 紅燈
        time.sleep(3)
        return False

# ── 步驟 3: 測試伺服器 ──
def step3():
    cyberpi.display.clear()
    cyberpi.display.show_label("連線伺服器...", 8, 40, 14)
    cyberpi.led.on(0, 200, 255)

    try:
        url = "{}/api/status".format(SERVER_URL)
        r = urequests.get(url)
        data = r.json()
        r.close()
        cyberpi.display.clear()
        cyberpi.display.show_label("伺服器 OK!", 16, 20, 18)
        cyberpi.display.show_label(data.get("llm_engine", "")[:18], 4, 45, 12)
        cyberpi.display.show_label(data.get("asr_engine", "")[:18], 4, 62, 12)
        cyberpi.led.on(0, 255, 100)
        time.sleep(2)
        return True
    except Exception as e:
        cyberpi.display.clear()
        cyberpi.display.show_label("伺服器 失敗", 12, 40, 14)
        cyberpi.display.show_label(str(e)[:20], 4, 60, 10)
        cyberpi.led.on(255, 100, 0)
        time.sleep(3)
        return False

# ── 步驟 4: 發送對話 ──
def step4():
    cyberpi.display.clear()
    cyberpi.display.show_label("問小智...", 16, 40, 16)
    cyberpi.led.on(200, 200, 0)

    try:
        url = "{}/api/chat?text={}&device_id={}".format(
            SERVER_URL,
            "你好呀".replace(" ", "%20"),
            DEVICE_ID
        )
        r = urequests.get(url)
        data = r.json()
        r.close()

        reply = data.get("text", "無回應")
        cyberpi.display.clear()

        # 顯示回應 (最多 5 行)
        lines = []
        line = ""
        for ch in reply:
            line += ch
            if len(line) >= 18:
                lines.append(line)
                line = ""
        if line:
            lines.append(line)

        y = 5
        for ln in lines[:6]:
            cyberpi.display.show_label(ln, 4, y, 12)
            y += 18

        cyberpi.led.on(0, 255, 0)
        time.sleep(5)
        return True
    except Exception as e:
        cyberpi.display.clear()
        cyberpi.display.show_label("對話 失敗", 16, 40, 14)
        cyberpi.display.show_label(str(e)[:20], 4, 60, 10)
        cyberpi.led.on(255, 0, 0)
        time.sleep(3)
        return False

# ── 主程式 ──
print("小智 AI CyberPi Debug")
step1()
step2()
step3()
step4()

cyberpi.display.clear()
cyberpi.display.show_label("完成!", 30, 40, 20)
cyberpi.display.show_label("A=重試 B=退出", 8, 65, 12)
cyberpi.led.on(0, 255, 200)

# ── 按鍵 + 定時循環 ──
_last_chat = time.time()
while True:
    now = time.time()

    # 每 30 秒自動重試一次
    if now - _last_chat > 30:
        _last_chat = now
        cyberpi.display.clear()
        cyberpi.display.show_label("自動重試...", 16, 40, 16)
        cyberpi.led.on(255, 200, 0)
        step4()
        cyberpi.display.clear()
        cyberpi.display.show_label("完成!", 30, 40, 20)
        cyberpi.display.show_label("A=重試 B=退出", 8, 65, 12)
        cyberpi.led.on(0, 255, 200)

    # 按鍵
    try:
        if cyberpi.is_press("a"):
            _last_chat = now
            # 等放開
            while cyberpi.is_press("a"):
                time.sleep(0.05)

            cyberpi.display.clear()
            cyberpi.display.show_label("重試中...", 20, 40, 16)
            cyberpi.led.on(255, 200, 0)
            step4()
            cyberpi.display.clear()
            cyberpi.display.show_label("完成!", 30, 40, 20)
            cyberpi.display.show_label("A=重試 B=退出", 8, 65, 12)
            cyberpi.led.on(0, 255, 200)

        if cyberpi.is_press("b"):
            while cyberpi.is_press("b"):
                time.sleep(0.05)
            break
    except:
        pass
    time.sleep(0.1)

cyberpi.display.clear()
cyberpi.display.show_label("再見!", 30, 40, 20)
cyberpi.led.off()
time.sleep(1)
cyberpi.display.clear()
