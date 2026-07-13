#!/usr/bin/env python3.11
"""
Telegram notifier — sends strategy signals to Telegram chat.
Usage:
    python3.11 notifier.py                    # Send last saved report
    python3.11 notifier.py --message "hello"  # Send custom message
"""
import os
import sys
import json
import io
import argparse
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests

# === CONFIG ===
# Create your bot via @BotFather on Telegram, then set these:
TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"
REPORT_DIR = "reports"
SIGNAL_FILE_TEMPLATE = os.path.join(REPORT_DIR, "signals_{date}.json")
REPORT_FILE_TEMPLATE = os.path.join(REPORT_DIR, "report_{date}.txt")


def send_telegram(message, token, chat_id):
    """Send text message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ Telegram send failed: {e}")
        return False


def format_signals_for_telegram(signal_data):
    """Format signal data as a concise Telegram message."""
    date = signal_data['date']
    lines = [f"📊 *MACD+EMA AI Stocks — {date}*", ""]

    any_signals = False
    for sym, data in signal_data['tickers'].items():
        if 'error' in data:
            lines.append(f"⚠️ {sym}: {data['error']}")
            continue

        signals = data['signals']
        has_signal = len(signals) > 0
        if has_signal:
            any_signals = True
            for s in signals:
                emoji = "🟢" if "BUY" in s['type'] else "🔴"
                lines.append(f"{emoji} *{sym}*: {s['type']} @ ${data['close']:.2f}")

    if not any_signals:
        lines.append("⏸ No new signals today")
        for sym, data in signal_data['tickers'].items():
            if 'error' not in data:
                emoji = "🟢" if "✅" in data.get('trend_filter', '') else "🔴"
                lines.append(f"   {emoji} {sym}: ${data['close']:.2f} | MACD {data['macd_state']} ({data['histogram_trend']})")

    lines.append("")
    lines.append("```")
    # Compact ticker table
    header = f"{'Ticker':<6} {'Price':>8} {'MACD':<8} {'Sig':<6}"
    lines.append(header)
    lines.append("-" * len(header))
    for sym, data in signal_data['tickers'].items():
        if 'error' not in data:
            sig = "BUY" if any("BUY" in s['type'] for s in data['signals']) else ("SELL" if any("SELL" in s['type'] for s in data['signals']) else "-")
            lines.append(f"{sym:<6} ${data['close']:>6.2f} {data['macd_state']:<8} {sig:<6}")
    lines.append("```")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--message', help='Send custom message instead of report')
    parser.add_argument('--date', help='Report date (YYYY-MM-DD), default today')
    parser.add_argument('--check', action='store_true', help='Check env config and exit')
    args = parser.parse_args()

    token = os.environ.get(TELEGRAM_TOKEN_ENV)
    chat_id = os.environ.get(TELEGRAM_CHAT_ID_ENV)

    if args.check:
        print(f"🔍 Telegram Config Check:")
        print(f"   Token: {'✅ set' if token else '❌ missing'} ({TELEGRAM_TOKEN_ENV})")
        print(f"   Chat ID: {'✅ set' if chat_id else '❌ missing'} ({TELEGRAM_CHAT_ID_ENV})")
        if token and chat_id:
            print("   Sending test message...")
            ok = send_telegram("✅ *MACD+EMA AI Bot* — Test message from Oracle Cloud", token, chat_id)
            print(f"   Result: {'✅ sent' if ok else '❌ failed'}")
        return

    if not token or not chat_id:
        print(f"❌ Missing Telegram config. Set {TELEGRAM_TOKEN_ENV} and {TELEGRAM_CHAT_ID_ENV}")
        sys.exit(1)

    if args.message:
        ok = send_telegram(args.message, token, chat_id)
        print(f"{'✅ Sent' if ok else '❌ Failed'}")
        return

    # Load today's signal data
    date = args.date or datetime.now().strftime('%Y-%m-%d')
    signal_path = SIGNAL_FILE_TEMPLATE.format(date=date)

    if not os.path.exists(signal_path):
        print(f"❌ No signal file for {date}: {signal_path}")
        print(f"   Run runner.py first to generate signals")
        sys.exit(1)

    with open(signal_path) as f:
        signal_data = json.load(f)

    message = format_signals_for_telegram(signal_data)
    print(f"📤 Sending Telegram message...")
    print(message)
    ok = send_telegram(message, token, chat_id)
    print(f"{'✅ Sent' if ok else '❌ Failed'}")


if __name__ == '__main__':
    main()
