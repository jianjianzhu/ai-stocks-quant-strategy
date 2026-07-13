"""BB+RSI v3 — Buy dips in uptrend, ride the trend"""
import os, pandas as pd, numpy as np, alpaca_trade_api as ata

for line in open(os.path.join(os.path.dirname(__file__) or '.', '.env'), encoding='utf-8'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ[k.strip()] = v.strip()

api = ata.REST(os.environ['ALPACA_API_KEY'], os.environ['ALPACA_SECRET_KEY'],
               'https://paper-api.alpaca.markets', api_version='v2')

for sym in ['NVDA','AMD','AVGO','TSM','MU']:
    bars = api.get_bars(sym, '1Day', start='2020-01-01', end='2026-06-29', adjustment='all', feed='iex').df
    df = bars[['open','high','low','close','volume']].copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None: df.index = df.index.tz_localize(None)
    df = df.sort_index()

    delta = df['close'].diff()
    gain = delta.where(delta>0,0).rolling(14).mean()
    loss = (-delta.where(delta<0,0)).rolling(14).mean()
    rs = gain/loss.replace(0,np.nan)
    df['rsi'] = 100 - (100/(1+rs))

    # BB(20,2)
    df['bb_mid'] = df['close'].rolling(20).mean()
    df['bb_std'] = df['close'].rolling(20).std(ddof=0)
    df['bb_l'] = df['bb_mid'] - 2*df['bb_std']
    df['bb_u'] = df['bb_mid'] + 2*df['bb_std']

    # EMAs for trend
    df['ema20'] = df['close'].ewm(span=20).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['ema200'] = df['close'].ewm(span=200).mean()

    # ATR for trail
    tr = pd.concat([df['high']-df['low'], (df['high']-df['close'].shift()).abs(), (df['low']-df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()

    # === ENTRY: Price near/below lower band IN AN UPTREND ===
    # Only buy when macro trend is up (price > EMA200)
    uptrend = df['close'] > df['ema200']

    # Price near lower band (within 0.5 ATR)
    near_lower = df['close'] <= df['bb_l'] + df['atr'] * 0.3

    # RSI not overbought
    rsi_ok = df['rsi'] < 60

    df['buy'] = uptrend & near_lower & rsi_ok & (df['close'] < df['ema20'])

    # === EXIT: Trail or EMA death ===
    ema_s = df['close'].ewm(span=5).mean()
    ema_m = df['close'].ewm(span=13).mean()
    death_cross = (ema_s < ema_m) & (ema_s.shift(1) >= ema_m.shift(1))

    pos, cap, shares, high_water = 0, 100000, 0, 0
    trades = []
    for i in range(200, len(df)):
        p = float(df['close'].iloc[i])
        if pos == 1:
            high_water = max(high_water, p)
            trail = float(df['atr'].iloc[i]) * 3 if not pd.isna(df['atr'].iloc[i]) else 0
            stop_loss = high_water - trail
            trail_hit = p < stop_loss and trail > 0

            if death_cross.iloc[i] or trail_hit or i == len(df) - 1:
                reason = 'death cross' if death_cross.iloc[i] else ('trail' if trail_hit else 'end')
                cap = shares * p
                trades.append({'entry': e, 'exit': p, 'ret': p/e - 1, 'reason': reason})
                pos = 0
        if pos == 0 and df['buy'].iloc[i]:
            e = p
            shares = cap * 0.95 / p
            cap *= 0.05
            pos = 1
            high_water = p

    final = cap + shares * float(df['close'].iloc[-1]) if pos else cap
    ret = final / 100000 - 1
    n = len(trades)
    wr = sum(1 for t in trades if t['ret'] > 0) / n if n else 0
    pf = sum(t['ret'] for t in trades if t['ret']>0) / abs(sum(t['ret'] for t in trades if t['ret']<=0)) if any(t['ret']<=0 for t in trades) else float('inf')

    eq = 100000
    peak = 100000
    maxdd = 0
    for t in trades:
        eq *= (1 + t['ret'])
        peak = max(peak, eq)
        maxdd = max(maxdd, (peak - eq) / peak)

    total_days = sum((t['ret'] for t in trades))
    cagr = ((1+ret) ** (1/6.5) - 1) * 100 if ret > 0 else 0

    print(f'=== {sym} === Ret: {ret*100:.1f}%  CAGR: {cagr:.1f}%  Trades: {n}  WR: {wr*100:.0f}%  PF: {pf:.1f}  MaxDD: {maxdd*100:.1f}%')
    for t in trades:
        print(f'    {t["reason"]:<15} {t["entry"]:.0f} -> {t["exit"]:.0f} ({t["ret"]*100:+.1f}%)')
    print()
