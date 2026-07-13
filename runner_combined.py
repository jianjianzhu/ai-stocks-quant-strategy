#!/usr/bin/env python3
"""
Bollinger + RSI + MACD+EMA Strategy Runner — Combined signals
"""
import os, sys, io
from datetime import datetime, timedelta
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np

TICKERS = ['NVDA', 'AMD', 'AVGO', 'TSM', 'MU', 'SMCI']
LOOKBACK = 800
REPORT_DIR = "reports"

# === Pure-pandas indicators ===
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

def calc_rsi(close, n=6):
    delta = close.diff()
    gain = delta.where(delta>0,0).rolling(n).mean()
    loss = (-delta.where(delta<0,0)).rolling(n).mean()
    rs = gain / loss.replace(0,np.nan)
    return 100 - (100/(1+rs))

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

def compute_all(df):
    """Compute MACD+EMA + Bollinger+RSI signals"""
    # MACD+EMA
    df['ema_s'] = df['close'].ewm(span=5).mean()
    df['ema_m'] = df['close'].ewm(span=8).mean()
    df['ema_l'] = df['close'].ewm(span=18).mean()
    df['macd'] = df['close'].ewm(span=3).mean() - df['close'].ewm(span=8).mean()
    df['macd_sig'] = df['macd'].ewm(span=27).mean()
    df['macd_hist'] = df['macd'] - df['macd_sig']
    df['ema_200'] = df['close'].ewm(span=200).mean()
    df['atr'] = calc_atr(df['high'], df['low'], df['close'])
    df['adx'] = calc_adx(df['high'], df['low'], df['close'])

    df['macd_buy'] = (df['macd_hist']>0) & (df['macd_hist'].shift(1)<=0)
    df['ema_cross_mid'] = (df['ema_s']>df['ema_m']) & (df['ema_s'].shift(1)<=df['ema_m'].shift(1))
    df['ema_cross_long'] = (df['ema_s']>df['ema_l']) & (df['ema_s'].shift(1)<=df['ema_l'].shift(1))
    df['macd_sell'] = (df['macd_hist']<0) & (df['macd_hist'].shift(1)>=0)
    df['death_cross'] = (df['ema_s']<df['ema_m']) & (df['ema_s'].shift(1)>=df['ema_m'].shift(1))

    # Bollinger + RSI
    df['rsi'] = calc_rsi(df['close'], 6)
    df['bb_mid'] = df['close'].rolling(20).mean()
    df['bb_std'] = df['close'].rolling(20).std()
    df['bb_u'] = df['bb_mid'] + 2.5*df['bb_std']
    df['bb_l'] = df['bb_mid'] - 2.5*df['bb_std']

    df['bb_buy'] = (df['close']>df['bb_l']) & (df['close'].shift(1)<=df['bb_l'].shift(1)) & (df['rsi']<30)
    df['bb_sell'] = (df['close']<df['bb_u']) & (df['close'].shift(1)>=df['bb_u'].shift(1))

    # Trend filter
    trend_ok = df['close'] > df['ema_200']
    adx_ok = df['adx'] > 20
    df['macd_buy_f'] = df['macd_buy'] & trend_ok & adx_ok

    return df

def get_signal(df):
    last = df.iloc[-1]
    signals = []
    # MACD+EMA
    if not pd.isna(last['macd_buy_f']) and last['macd_buy_f']:
        signals.append(('MACD BUY L1', 'MACD>0 + trend'))
    if not pd.isna(last['ema_cross_mid']) and last['ema_cross_mid']:
        signals.append(('MACD BUY L2', 'EMA mid cross'))
    if not pd.isna(last['ema_cross_long']) and last['ema_cross_long']:
        signals.append(('MACD BUY L3', 'EMA long cross'))
    if not pd.isna(last['macd_sell']) and last['macd_sell']:
        signals.append(('MACD SELL', 'MACD<0'))
    if not pd.isna(last['death_cross']) and last['death_cross']:
        signals.append(('MACD SELL', 'death cross'))
    # BB+RSI
    if not pd.isna(last['bb_buy']) and last['bb_buy']:
        signals.append(('BB BUY', 'BB lower+RSI<30'))
    if not pd.isna(last['bb_sell']) and last['bb_sell']:
        signals.append(('BB SELL', 'BB upper hit'))

    return {
        'date': str(df.index[-1].date()),
        'close': float(last['close']),
        'signals': signals,
        'price': float(last['close']),
        'rsi': float(last['rsi']) if not pd.isna(last['rsi']) else 0,
        'bb_l': float(last['bb_l']) if not pd.isna(last['bb_l']) else 0,
        'bb_u': float(last['bb_u']) if not pd.isna(last['bb_u']) else 0,
        'bb_mid': float(last['bb_mid']) if not pd.isna(last['bb_mid']) else 0,
        'atr': float(last['atr']) if not pd.isna(last['atr']) else 0,
        'adx': float(last['adx']) if not pd.isna(last['adx']) else 0,
        'macd_state': 'bullish' if last['macd_hist']>0 else 'bearish',
        'rsi_level': 'oversold' if last['rsi']<30 else 'overbought' if last['rsi']>70 else 'neutral',
    }

def fmt(ticker, s):
    lines = [f"  {ticker}"]
    lines.append(f"    Price: ${s['price']:.2f} | RSI: {s['rsi']:.0f} ({s['rsi_level']})")
    lines.append(f"    BB: lower=${s['bb_l']:.0f} mid=${s['bb_mid']:.0f} upper=${s['bb_u']:.0f}")
    lines.append(f"    MACD: {s['macd_state']} | ATR: {s['atr']:.1f} | ADX: {s['adx']:.1f}")
    if s['signals']:
        for st, sd in s['signals']:
            lines.append(f"    >>> {st}: {sd}")
    else:
        lines.append(f"    No signal")
    return '\n'.join(lines)

def main():
    load_env()
    os.makedirs(REPORT_DIR, exist_ok=True)
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now()-timedelta(days=LOOKBACK)).strftime('%Y-%m-%d')
    print(f"Bollinger+RSI + MACD+EMA Combined — {end}\n")
    reports = []
    for sym in TICKERS:
        try:
            data = load_data(sym, start, end)
            df = compute_all(data)
            s = get_signal(df)
            r = fmt(sym, s)
            reports.append(r); print(r); print()
        except Exception as e:
            reports.append(f"  {sym}: {e}"); print(f"  {sym}: {e}\n")
    rp = os.path.join(REPORT_DIR, f'combined_{end}.txt')
    with open(rp, 'w', encoding='utf-8') as f:
        f.write('\n'.join(reports))
    print(f"Saved: {rp}")

if __name__ == '__main__':
    main()
