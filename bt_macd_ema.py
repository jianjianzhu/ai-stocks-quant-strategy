"""MACD+EMA full backtest with Sharpe & detailed stats"""
import os, pandas as pd, numpy as np, itertools

for line in open(os.path.join(os.path.dirname(__file__) or '.', '.env'), encoding='utf-8'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ[k.strip()] = v.strip()

import alpaca_trade_api as ata
api = ata.REST(os.environ['ALPACA_API_KEY'], os.environ['ALPACA_SECRET_KEY'],
               'https://paper-api.alpaca.markets', api_version='v2')

data = {}
for sym in ['NVDA', 'AMD', 'AVGO', 'TSM', 'MU']:
    bars = api.get_bars(sym, '1Day', start='2020-01-01', end='2026-06-29', adjustment='all', feed='iex').df
    df = bars[['open', 'high', 'low', 'close', 'volume']].copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    data[sym] = df.sort_index()


def macd_bt(df, fl, sl, sgl, ema_s, ema_m, ema_l, atr_mult, trail_mult, pyra, use_tf):
    close = df['close']
    macd = close.ewm(span=fl).mean() - close.ewm(span=sl).mean()
    sig = macd.ewm(span=sgl).mean()
    hist = macd - sig

    emaS = close.ewm(span=ema_s).mean()
    emaM = close.ewm(span=ema_m).mean()
    emaL = close.ewm(span=ema_l).mean()
    ema200 = close.ewm(span=200).mean()

    tr = pd.concat([df['high']-df['low'], (df['high']-close.shift()).abs(), (df['low']-close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    atr_safe = atr.copy()
    atr_safe[atr_safe < 0.01] = 0.01

    l1 = (hist > 0) & (hist.shift(1) <= 0)
    l2 = (emaS > emaM) & (emaS.shift(1) <= emaM.shift(1))
    l3 = (emaS > emaL) & (emaS.shift(1) <= emaL.shift(1))
    exit_sig = ((hist < 0) & (hist.shift(1) >= 0)) | ((emaS < emaM) & (emaS.shift(1) >= emaM.shift(1)))
    if use_tf:
        l1 = l1 & (close > ema200)
        l2 = l2 & (close > ema200)
        l3 = l3 & (close > ema200)

    equity = 100000.0
    cash = 100000.0
    shares = 0.0
    trades = []
    entry_count = 0
    avg_entry = 0.0
    stop_price = None
    trail_on = False
    trail_high = 0.0

    for i in range(200, len(df)):
        p = float(close.iloc[i])
        lo = float(df['low'].iloc[i])
        atrv = float(atr_safe.iloc[i])

        # -- EXIT --
        if shares > 0:
            trail_high = max(trail_high, p)

            # Update trailing stop
            if trail_mult > 0:
                if not trail_on and p >= avg_entry * 1.02:
                    trail_on = True
                    stop_price = max(stop_price or 0, trail_high - atrv * trail_mult)
                if trail_on:
                    new_stop = trail_high - atrv * trail_mult
                    stop_price = max(stop_price or 0, new_stop)

            stop_hit = stop_price is not None and lo <= stop_price

            if exit_sig.iloc[i] or stop_hit or i == len(df) - 1:
                ret = p / avg_entry - 1
                trades.append(ret)
                cash = cash + shares * p  # ADD back to cash, don't overwrite
                shares = 0.0
                entry_count = 0
                stop_price = None
                trail_on = False
                continue

        # -- ENTRY --
        if entry_count < pyra:
            should_enter = False
            if entry_count == 0 and l1.iloc[i] and not np.isnan(atrv):
                should_enter = True
            elif entry_count == 1 and l2.iloc[i]:
                should_enter = True
            elif entry_count >= 2 and l3.iloc[i]:
                should_enter = True

            if should_enter:
                portion = 0.33  # 33% per entry
                invest = cash * portion
                new_shares = invest / p
                shares += new_shares
                cash -= invest

                if entry_count == 0:
                    avg_entry = p
                else:
                    avg_entry = (avg_entry * (shares - new_shares) / shares) + (p * new_shares / shares)

                entry_count += 1

                # Initial stop
                if entry_count == 1 and not np.isnan(atrv):
                    stop_price = p - atrv * atr_mult
                    trail_on = False
                    trail_high = p
                elif not np.isnan(atrv):
                    ns = p - atrv * atr_mult
                    stop_price = max(stop_price or 0, ns) if stop_price else ns

    # Final value
    total_value = cash + shares * float(close.iloc[-1])
    ret = total_value / 100000 - 1
    n = len(trades)
    wr = sum(1 for t in trades if t > 0) / n if n else 0
    avg_w = np.mean([t for t in trades if t > 0]) * 100 if any(t > 0 for t in trades) else 0
    avg_l = np.mean([t for t in trades if t <= 0]) * 100 if any(t <= 0 for t in trades) else 0
    pf = sum(t for t in trades if t > 0) / abs(sum(t for t in trades if t <= 0)) if any(t <= 0 for t in trades) else float('inf')

    # Max DD
    eq = 100000.0
    peak = 100000.0
    maxdd = 0.0
    for t in trades:
        eq *= (1 + t)
        peak = max(peak, eq)
        maxdd = max(maxdd, (peak - eq) / peak)

    # Sharpe (annualized, ~15 day avg hold)
    if n > 1 and np.std(trades) > 0:
        sharpe = np.mean(trades) / np.std(trades) * np.sqrt(252 / 15)
    else:
        sharpe = 0

    return {
        'ret': ret, 'n': n, 'wr': wr, 'sharpe': sharpe,
        'mdd': maxdd, 'pf': pf, 'avg_w': avg_w, 'avg_l': avg_l
    }


# === CURRENT OPTIMIZED PARAMS ===
print('=== CURRENT PARAMS: MACD(3,8,27) EMA(5,8,18) ATR3 Trail3 Pyr3 TF=true ===')
cp = {'fl': 3, 'sl': 8, 'sgl': 27, 'ema_s': 5, 'ema_m': 8, 'ema_l': 18,
      'atr_mult': 3.0, 'trail_mult': 3.0, 'pyra': 3, 'use_tf': True}
for sym in ['NVDA', 'AMD', 'AVGO', 'TSM', 'MU']:
    r = macd_bt(data[sym], **cp)
    print(f'  {sym}: Ret={r["ret"]*100:.1f}%  Trades={r["n"]}  WR={r["wr"]*100:.0f}%  '
          f'Sharpe={r["sharpe"]:.2f}  PF={r["pf"]:.1f}  MaxDD={r["mdd"]*100:.1f}%')

print()

# === GRID SEARCH ===
print('=== GRID SEARCH ===')
results = []
grid = list(itertools.product(
    [3, 5], [8, 11, 14], [27],
    [3, 5], [8, 11, 14], [18],
    [2.0, 3.0, 4.0], [2.0, 3.0],
    [1, 3], [True],
))

for fl, sl, sgl, es, em, el, atr_m, tr_m, pyr, tf in grid:
    rs = [macd_bt(data[s], fl, sl, sgl, es, em, el, atr_m, tr_m, pyr, tf) for s in ['NVDA', 'AMD', 'AVGO']]
    avg_ret = np.mean([r['ret'] for r in rs])
    avg_sharpe = np.mean([r['sharpe'] for r in rs])
    avg_n = np.mean([r['n'] for r in rs])
    avg_mdd = np.mean([r['mdd'] for r in rs])
    score = avg_sharpe * 0.4 + avg_ret * 0.3 - avg_mdd * 0.3
    results.append({
        'label': f'MACD({fl},{sl},{sgl}) EMA({es},{em},{el}) A{atr_m} T{tr_m} P{pyr}',
        'ret': avg_ret, 'sharpe': avg_sharpe, 'n': avg_n, 'mdd': avg_mdd, 'score': score
    })

results.sort(key=lambda x: x['score'], reverse=True)
print(f'{"Params":<45} {"Return":>8} {"Sharpe":>8} {"Trades":>6} {"MaxDD":>7} {"Score":>7}')
print('-' * 82)
for r in results[:12]:
    print(f'{r["label"]:<45} {r["ret"]*100:>7.1f}% {r["sharpe"]:>7.2f} {r["n"]:>6.0f} {r["mdd"]*100:>6.1f}% {r["score"]*100:>6.1f}%')

b = results[0]
print(f'\nBEST: {b["label"]}')
print(f'  Ret={b["ret"]*100:.1f}%  Sharpe={b["sharpe"]:.2f}  Trades={b["n"]:.0f}  MaxDD={b["mdd"]*100:.1f}%')

print()
print('=== FULL DETAILS FOR BEST PARAMS ON ALL STOCKS ===')
# Parse best
parts = b['label'].replace('MACD(','').replace(') EMA(','|').replace(') ','|')
macd_p, ema_p, rest = parts.split('|')
fl, sl, sgl = [int(x) for x in macd_p.split(',')]
es, em, el = [int(x) for x in ema_p.split(',')]
rest2 = rest.split()
atr_m = float(rest2[0][1:])
tr_m = float(rest2[1][1:])
pyr = int(rest2[2][1:])

for sym in ['NVDA', 'AMD', 'AVGO', 'TSM', 'MU']:
    r = macd_bt(data[sym], fl, sl, sgl, es, em, el, atr_m, tr_m, pyr, True)
    print(f'  {sym}: Ret={r["ret"]*100:.1f}%  n={r["n"]}  WR={r["wr"]*100:.0f}%  Sharpe={r["sharpe"]:.2f}  PF={r["pf"]:.1f}  MaxDD={r["mdd"]*100:.1f}%')

