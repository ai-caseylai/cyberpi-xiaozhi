micro# cyberpi_xiaozhi78.py
# ====================
# 小智 AI — 錄音本地播 + 文字自動問千問
import event, time, cyberpi, urequests

WIFI_SSID = "SmarTone_HBB_3A74"
WIFI_PASSWORD = "6J25GJ2GB5"
SERVER_IP = "192.168.0.194"
SERVER_PORT = 8000
DEVICE_ID = "cyberpi-78"
SERVER_URL = "http://{}:{}".format(SERVER_IP, SERVER_PORT)

def url_encode(s):
    result = ""
    for ch in s:
        for byte in ch.encode("utf-8"):
            result += "%{:02X}".format(byte)
    return result

def ask_server(text):
    global _last_ask
    _last_ask = time.ticks_ms()
    import ubinascii
    cyberpi.console.println("⏳ 小智...")
    cyberpi.led.on(255, 200, 0, "all")
    try:
        r = urequests.get("{}/api/chat?text={}&device_id={}".format(
            SERVER_URL, url_encode(text), DEVICE_ID))
        data = r.json()
        r.close()
        reply = data.get("text","")
        emotion = data.get("emotion","neutral")
        leds = {"happy":(0,255,0),"neutral":(0,150,255),"thinking":(255,200,0),"love":(255,0,100),"sad":(100,100,255)}
        c = leds.get(emotion,(0,150,255))
        cyberpi.led.on(c[0],c[1],c[2],"all")
        cyberpi.console.clear()
        cyberpi.console.println("🧑: " + text)
        cyberpi.console.println("---")
        cyberpi.console.println("🤖: " + reply)
        try:
            r2 = urequests.get("{}/api/tts?text={}".format(SERVER_URL, url_encode(reply[:100])))
            tts = r2.json().get("audio","")
            r2.close()
            if tts:
                mp3 = ubinascii.a2b_base64(tts)
                with open("t.mp3","wb") as f:
                    f.write(mp3)
                cyberpi.audio.play("t.mp3")
        except:
            pass
        time.sleep(2)
    except:
        cyberpi.console.println("HTTP err")

QUESTIONS = [
    "你好呀，用廣東話介紹下自己",
    "今日天氣點樣",
    "講個笑話",
    "香港有咩好玩",
    "而家幾點",
]
_q_idx = 0
_last_ask = 0
_recording = False

@event.start
def on_start():
    global _last_ask
    import ubinascii

    cyberpi.console.clear()
    cyberpi.console.println("小智 AI")
    cyberpi.wifi.connect(WIFI_SSID, WIFI_PASSWORD)
    time.sleep(8)
    if cyberpi.wifi.is_connect():
        cyberpi.console.println("Wifi OK")
        cyberpi.led.on(0, 255, 0, "all")
    else:
        cyberpi.console.println("Wifi 失效")
        cyberpi.led.on(255, 0, 0, "all")
        return

    time.sleep(1)
    cyberpi.console.clear()
    cyberpi.console.println("A:錄音 B:播")
    cyberpi.console.println("自動問小智...")
    cyberpi.led.on(0, 255, 100, "all")

    global _recording, _last_ask, _q_idx
    _recording = False
    _last_ask = time.ticks_ms()

    for _ in range(99999):
        now = time.ticks_ms()
        a = cyberpi.controller.is_press("a")
        b = cyberpi.controller.is_press("b")

        # A: 按住錄，鬆手停
        if a and not _recording:
            _recording = True
            cyberpi.console.clear()
            cyberpi.console.println("🎤 錄音中...")
            cyberpi.console.println("鬆手停止")
            cyberpi.led.on(255, 0, 255, "all")
            cyberpi.audio.record()

        if not a and _recording:
            _recording = False
            cyberpi.audio.stop_record()
            time.sleep(0.5)
            cyberpi.console.clear()
            cyberpi.console.println("✅ 已儲存")
            cyberpi.console.println("B:播放")
            cyberpi.led.on(0, 255, 100, "all")

        # B: 播放 + 上傳文字base64
        if b and not _recording:
            cyberpi.console.clear()
            cyberpi.console.println("🔊 播放...")
            cyberpi.led.on(255, 255, 0, "all")
            try:
                cyberpi.audio.play_record_until()
            except:
                pass
            time.sleep(1)

            # 文字語音問小智 (B: 先播自己 → 再聽千問)
            cyberpi.console.println("⏳ 問小智...")
            cyberpi.led.on(255, 200, 0, "all")
            q = QUESTIONS[_q_idx]
            _q_idx = (_q_idx + 1) % len(QUESTIONS)
            ask_server(q)

            cyberpi.console.clear()
            cyberpi.console.println("A:錄音 B:播+問")
            cyberpi.led.on(0, 255, 100, "all")

        # 每 15 秒自動文字問千問
        if time.ticks_diff(now, _last_ask) > 15000:
            _last_ask = now
            global _q_idx
            q = QUESTIONS[_q_idx]
            _q_idx = (_q_idx + 1) % len(QUESTIONS)

            cyberpi.console.clear()
            cyberpi.console.println("⏳ 問: " + q[:18])
            cyberpi.led.on(255, 200, 0, "all")

            try:
                r = urequests.get("{}/api/chat?text={}&device_id={}".format(
                    SERVER_URL, url_encode(q), DEVICE_ID))
                data = r.json()
                r.close()
                reply = data.get("text","")
                emotion = data.get("emotion","neutral")

                leds = {"happy":(0,255,0),"neutral":(0,150,255),"thinking":(255,200,0),"love":(255,0,100),"sad":(100,100,255)}
                c = leds.get(emotion,(0,150,255))
                cyberpi.led.on(c[0],c[1],c[2],"all")

                cyberpi.console.clear()
                cyberpi.console.println("Q: " + q[:18])
                cyberpi.console.println("---")
                cyberpi.console.println("🤖 " + reply)

                # TTS
                try:
                    r2 = urequests.get("{}/api/tts?text={}".format(SERVER_URL, url_encode(reply[:100])))
                    tts = r2.json().get("audio","")
                    r2.close()
                    if tts:
                        mp3 = ubinascii.a2b_base64(tts)
                        with open("t.mp3","wb") as f:
                            f.write(mp3)
                        cyberpi.audio.play("t.mp3")
                except:
                    pass
                time.sleep(2)

            except:
                cyberpi.console.println("HTTP err")
                cyberpi.led.on(255, 60, 0, "all")
                time.sleep(2)

            cyberpi.console.clear()
            cyberpi.console.println("A:錄音 B:播放")
            cyberpi.led.on(0, 255, 100, "all")

        time.sleep(0.1)
