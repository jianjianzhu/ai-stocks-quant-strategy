#!/usr/bin/env python3
"""
Push combined strategy signals to WeChat (Server酱)
"""
import requests, os, json
from datetime import datetime

SENDKEY = os.environ.get("WECHAT_SENDKEY", "")

def push(title, content):
    if not SENDKEY:
        print("❌ WECHAT_SENDKEY not set in environment")
        return
    r = requests.post(f"https://sctapi.ftqq.com/{SENDKEY}.send",
        data={"title": title, "desp": content}, timeout=10)
    return r.json()

if __name__ == "__main__":
    today = datetime.now().strftime("%Y-%m-%d")
    path = f"/root/macd-ema-ai/reports/combined_{today}.txt"
    if os.path.exists(path):
        with open(path) as f:
            content = f.read()
        push(f"BB+RSI & MACD+EMA 策略信号 - {today}", content)
        print(f"Pushed {len(content)} chars")
    else:
        print("No report for", today)
