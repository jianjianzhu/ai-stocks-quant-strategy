#!/usr/bin/env python3
"""
MACD+EMA AI Stocks Strategy — Daily Runner
BB(20,2.5)+RSI(6) + MACD(3,14,27)+EMA(5,11,18) combined
"""
import os, sys, io
from datetime import datetime, timedelta
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np

TICKERS = ['NVDA', 'AMD', 'MU', 'ASML', 'INTC', 'WOLF', 'AMAT', 'STM']
LOOKBACK = 800
REPORT_DIR = "reports"

# --- Indicators (pure pandas) ---
def calc_rsi(close, n=14):
    delta = close.diff()
    gain = delta.where(delta>0,0).rolling(n).mean()
    loss = (-delta.where(delta<0,0)).rolling(n).mean()
    rs = gain / loss.replace(0,np.nan)
    return 100 - (100/(1+rs))

def calc_atr(high, low, close, n=14):
    tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def calc_adx(high, low, close, n=14):
    tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(n).mean()
    up, dn = high.diff(), low.diff()
    pdm = up.where((up>dn)&(up>0),0)
    mdm = dn.where((dn>up)&(dn>0),0).abs()
    pdi = 100*(pdm.ewm(alpha=1/n).mean()/atr)
    mdi = 100*(mdm.ewm(alpha=1/n).mean()/atr)
    dx = 100*((pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan))
    return dx.rolling(n).mean()

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
    df = bars[['open','high','low','close','volume']].copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None: df.index = df.index.tz_localize(None)
    return df.sort_index()

def compute(df):
    """Compute all signals: MACD+EMA + BB+RSI"""
    close = df['close']
    # MACD(3,14,27)
    df['macd'] = close.ewm(span=3).mean() - close.ewm(span=14).mean()
    df['macd_sig'] = df['macd'].ewm(span=27).mean()
    df['macd_hist'] = df['macd'] - df['macd_sig']
    # EMA(5,11,18)
    df['ema_s'] = close.ewm(span=5).mean()
    df['ema_m'] = close.ewm(span=11).mean()
    df['ema_l'] = close.ewm(span=18).mean()
    # Trend
    df['ema200'] = close.ewm(span=200).mean()
    df['atr'] = calc_atr(df['high'], df['low'], close)
    df['adx'] = calc_adx(df['high'], df['low'], close)
    # BB(20,2.5)+RSI(6)
    df['rsi6'] = calc_rsi(close, 6)
    df['bb_mid'] = close.rolling(20).mean()
    df['bb_std'] = close.rolling(20).std(ddof=0)
    df['bb_l'] = df['bb_mid'] - 2.5*df['bb_std']
    df['bb_u'] = df['bb_mid'] + 2.5*df['bb_std']

    # Signals
    df['macd_buy'] = (df['macd_hist']>0) & (df['macd_hist'].shift(1)<=0)
    df['ema_mid_x'] = (df['ema_s']>df['ema_m']) & (df['ema_s'].shift(1)<=df['ema_m'].shift(1))
    df['ema_long_x'] = (df['ema_s']>df['ema_l']) & (df['ema_s'].shift(1)<=df['ema_l'].shift(1))
    df['macd_sell'] = (df['macd_hist']<0) & (df['macd_hist'].shift(1)>=0)
    df['death_x'] = (df['ema_s']<df['ema_m']) & (df['ema_s'].shift(1)>=df['ema_m'].shift(1))
    df['exit'] = df['macd_sell'] | df['death_x']
    # BB buy
    df['bb_buy'] = (close>df['bb_l']) & (close.shift(1)<=df['bb_l'].shift(1)) & (df['rsi6']<35) & (close<df['bb_mid'])
    df['bb_sell'] = (close<df['bb_u']) & (close.shift(1)>=df['bb_u'].shift(1))

    return df

def get_signal(df):
    last = df.iloc[-1]
    signals = []
    if not pd.isna(last['macd_buy']) and last['macd_buy']:
        signals.append(('🟢 MACD BUY L1', 'hist > 0'))
    if not pd.isna(last['ema_mid_x']) and last['ema_mid_x']:
        signals.append(('🟢 MACD BUY L2', 'EMA mid cross'))
    if not pd.isna(last['ema_long_x']) and last['ema_long_x']:
        signals.append(('🟢 MACD BUY L3', 'EMA long cross'))
    if not pd.isna(last['bb_buy']) and last['bb_buy']:
        signals.append(('🟢 BB BUY', f'BB lower + RSI {last["rsi6"]:.0f}'))
    if not pd.isna(last['exit']) and last['exit']:
        signals.append(('🔴 SELL', 'MACD or death cross'))
    if not pd.isna(last['bb_sell']) and last['bb_sell']:
        signals.append(('🔴 BB SELL', 'upper band'))

    return {
        'date': str(df.index[-1].date()),
        'price': float(last['close']),
        'signals': signals,
        'rsi': float(last['rsi6']) if not pd.isna(last['rsi6']) else 0,
        'atr': float(last['atr']) if not pd.isna(last['atr']) else 0,
        'adx': float(last['adx']) if not pd.isna(last['adx']) else 0,
        'macd_state': 'bullish' if last['macd_hist']>0 else 'bearish',
        'bb_pct': float((last['close']-last['bb_l'])/(last['bb_u']-last['bb_l']))*100 if not pd.isna(last['bb_l']) else 0,
    }

def fmt(ticker, s):
    lines = [f"  {ticker} — ${s['price']:.2f}"]
    lines.append(f"    MACD: {s['macd_state']} | RSI: {s['rsi']:.0f} | BB%: {s['bb_pct']:.0f}%")
    lines.append(f"    ATR: ${s['atr']:.2f} | ADX: {s['adx']:.1f}")
    if s['signals']:
        for st, sd in s['signals']:
            lines.append(f"    >>> {st}: {sd}")
    else:
        lines.append(f"    No signal — {s['macd_state']}")
    return '\n'.join(lines)

def main():
    load_env()
    os.makedirs(REPORT_DIR, exist_ok=True)
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now()-timedelta(days=LOOKBACK)).strftime('%Y-%m-%d')
    print(f"Strategy Signal — {end}\n")
    reports = []
    for sym in TICKERS:
        try:
            data = load_data(sym, start, end)
            df = compute(data)
            s = get_signal(df)
            r = fmt(sym, s)
            reports.append(r); print(r); print()
        except Exception as e:
            reports.append(f"  {sym}: {e}"); print(f"  {sym}: {e}\n")
    rp = os.path.join(REPORT_DIR, f'signal_{end}.txt')
    with open(rp, 'w', encoding='utf-8') as f:
        f.write('\n'.join(reports))
    print(f"Saved: {rp}")

if __name__ == '__main__':
    main()
