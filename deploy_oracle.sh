#!/bin/bash
# ============================================================
# MACD+EMA AI Stocks — 一键部署脚本
# 在 Oracle Cloud Shell 运行: bash deploy_oracle.sh
# ============================================================
set -e

PROJ="$HOME/macd-ema-ai"
mkdir -p "$PROJ/reports" "$PROJ/logs"
cd "$PROJ"

echo "============================================"
echo "  一键部署 MACD+EMA AI Stocks"
echo "============================================"

# === 1. 安装依赖 ===
echo ""
echo "[1/4] 安装 Python 包..."
sudo dnf install -y python3-pip 2>&1 | tail -1
pip3 install pandas pandas-ta numpy alpaca-trade-api requests 2>&1 | tail -1

# === 2. 创建 .env ===
echo "[2/4] 创建配置文件..."
cat > .env << 'ENVEOF'
# 在使用前，请将下方的密钥替换为你自己的 Alpaca API 密钥
# 获取地址: https://app.alpaca.markets/paper/dashboard/overview
ALPACA_API_KEY=YOUR_PAPER_API_KEY_HERE
ALPACA_SECRET_KEY=YOUR_PAPER_SECRET_KEY_HERE
ENVEOF

# === 3. 创建 runner.py ===
echo "[3/4] 创建策略文件..."

cat > runner.py << 'PYEOF'
#!/usr/bin/env python3
"""
MACD+EMA AI Stocks Strategy — Daily Runner
"""
import os, sys, json, io
from datetime import datetime, timedelta
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
import pandas_ta as ta

TICKERS = ['NVDA', 'AMD', 'AVGO', 'TSM', 'MU', 'SMCI']
LOOKBACK_DAYS = 750
REPORT_DIR = "reports"

PARAMS = {
    'fast_len': 3, 'slow_len': 8, 'sig_len': 27,
    'ema_short': 5, 'ema_mid': 8, 'ema_long': 18,
    'use_trend_filter': True, 'use_adx_filter': True,
    'adx_period': 14, 'atr_period': 14,
    'use_stop': True, 'atr_stop_mult': 3.0,
    'use_trail': True, 'trail_activation': 0.015, 'trail_mult': 3.0,
    'pyramiding': 3, 'position_size': 0.33,
}

def load_env():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())

def load_data(symbol, start, end):
    from alpaca_trade_api import REST
    api = REST(os.environ['ALPACA_API_KEY'], os.environ['ALPACA_SECRET_KEY'],
               'https://paper-api.alpaca.markets', api_version='v2')
    bars = api.get_bars(symbol, '1Day', start=start, end=end, adjustment='all', feed='iex').df
    df = bars[['open', 'high', 'low', 'close', 'volume']].copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df.sort_index()

def compute_signals(df, p):
    df['ema_short'] = df['close'].ewm(span=p['ema_short'], adjust=False).mean()
    df['ema_mid'] = df['close'].ewm(span=p['ema_mid'], adjust=False).mean()
    df['ema_long'] = df['close'].ewm(span=p['ema_long'], adjust=False).mean()
    df['macd_line'] = df['close'].ewm(span=p['fast_len'], adjust=False).mean() - df['close'].ewm(span=p['slow_len'], adjust=False).mean()
    df['sig_line'] = df['macd_line'].ewm(span=p['sig_len'], adjust=False).mean()
    df['histogram'] = df['macd_line'] - df['sig_line']
    df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=p['atr_period'])
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=p['adx_period'])
    df['adx'] = adx_df.iloc[:, 0] if adx_df is not None else 0

    df['macd_golong'] = (df['histogram'] > 0) & (df['histogram'].shift(1) <= 0)
    df['macd_goshort'] = (df['histogram'] < 0) & (df['histogram'].shift(1) >= 0)
    df['cross_mid'] = (df['ema_short'] > df['ema_mid']) & (df['ema_short'].shift(1) <= df['ema_mid'].shift(1))
    df['cross_long'] = (df['ema_short'] > df['ema_long']) & (df['ema_short'].shift(1) <= df['ema_long'].shift(1))
    df['death_cross'] = (df['ema_short'] < df['ema_mid']) & (df['ema_short'].shift(1) >= df['ema_mid'].shift(1))

    df['trend_ok'] = ~p['use_trend_filter'] | (df['close'] > df['ema_200'])
    df['adx_ok'] = ~p['use_adx_filter'] | (df['adx'] > 20)
    df['all_ok'] = df['trend_ok'] & df['adx_ok']

    df['enter_l1'] = df['macd_golong'] & df['all_ok']
    df['enter_l2'] = df['cross_mid'] & df['all_ok']
    df['enter_l3'] = df['cross_long'] & df['all_ok']
    df['exit_signal'] = df['macd_goshort'] | df['death_cross']
    return df

def get_latest_signal(df):
    last = df.iloc[-1]; prev = df.iloc[-2] if len(df) > 1 else last
    signals = []
    if last['enter_l1']: signals.append(('BUY L1', 'MACD histogram crossed above 0'))
    if last['enter_l2']: signals.append(('BUY L2', 'EMA short crossed above EMA mid'))
    if last['enter_l3']: signals.append(('BUY L3', 'EMA short crossed above EMA long'))
    if last['exit_signal']: signals.append(('SELL', 'MACD crossed below 0 or EMA death cross'))

    above_short = last['close'] > last['ema_short']
    above_mid = last['close'] > last['ema_mid']
    above_long = last['close'] > last['ema_long']
    macd_state = "bullish" if last['histogram'] > 0 else "bearish" if last['histogram'] < 0 else "neutral"
    return {
        'date': str(df.index[-1].date()), 'close': last['close'], 'signals': signals,
        'macd': {'line': last['macd_line'], 'signal': last['sig_line'], 'histogram': last['histogram'], 'state': macd_state},
        'ema': {'short': last['ema_short'], 'mid': last['ema_mid'], 'long': last['ema_long']},
        'atr': last['atr'], 'adx': last['adx'],
        'trend_filter': "above 200EMA" if last['close'] > last['ema_200'] else "below 200EMA",
        'adx_ok': bool(last['adx_ok']),
        'price_above_emas': bool(above_short and above_mid and above_long),
        'histogram_trend': 'rising' if last['histogram'] > prev['histogram'] else 'falling',
    }

def format_report(ticker, s):
    lines = [f"  {ticker} - {s['date']}"]
    lines.append(f"    Price: ${s['close']:.2f}")
    lines.append(f"    MACD: {s['macd']['state']} (hist {s['macd']['histogram']:.2f}, {s['histogram_trend']})")
    lines.append(f"    EMAs: S={s['ema']['short']:.2f} M={s['ema']['mid']:.2f} L={s['ema']['long']:.2f}")
    lines.append(f"    ATR: {s['atr']:.2f} | ADX: {s['adx']:.1f}")
    if s['signals']:
        for st, sd in s['signals']:
            lines.append(f"    >>> {st}: {sd}")
    else:
        lines.append(f"    No new signal")
    return '\n'.join(lines)

def main():
    load_env(); os.makedirs(REPORT_DIR, exist_ok=True)
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime('%Y-%m-%d')
    print(f"Running: {end_date} ({start_date} ~ {end_date})")
    all_reports = []
    for sym in TICKERS:
        try:
            data = load_data(sym, start_date, end_date)
            df = compute_signals(data, PARAMS)
            s = get_latest_signal(df)
            r = format_report(sym, s)
            all_reports.append(r); print(r); print()
        except Exception as e:
            all_reports.append(f"  {sym}: ERROR - {e}")
            print(f"  {sym}: ERROR - {e}\n")
    report_path = os.path.join(REPORT_DIR, f'report_{end_date}.txt')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(all_reports))
    print(f"Report saved: {report_path}")

if __name__ == '__main__':
    main()
PYEOF

# === 4. 创建 run_strategy.sh ===
cat > run_strategy.sh << 'SHEOF'
#!/bin/bash
cd "$(dirname "$0")"
if [ -f .env ]; then set -a; source .env; set +a; fi
LOG_DIR="logs"; mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run_$(date '+%Y%m%d_%H%M%S').log"
echo "=== MACD+EMA AI Runner ===" | tee -a "$LOG_FILE"
echo "[1/2] Running strategy..." | tee -a "$LOG_FILE"
python3 runner.py 2>&1 | tee -a "$LOG_FILE"
echo "[2/2] Done" | tee -a "$LOG_FILE"
SHEOF
chmod +x run_strategy.sh

# === 5. 验证 ===
echo "[4/4] 验证..."
python3 -c "import pandas_ta, alpaca_trade_api; print('OK: pandas_ta', pandas_ta.__version__)"
python3 runner.py 2>&1 | head -10

echo ""
echo "============================================"
echo "  部署完成！"
echo "  项目路径: $PROJ"
echo "============================================"
echo ""
echo "手动运行: cd $PROJ && python3 runner.py"
echo "设置定时任务: crontab -e"
echo "  美东 9:25 AM: 25 13 * * 1-5 cd $PROJ && python3 runner.py"
echo "  美东 4:30 PM: 30 20 * * 1-5 cd $PROJ && python3 runner.py"
