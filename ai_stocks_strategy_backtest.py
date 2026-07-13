#!/usr/bin/env python3.11
import os
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import pandas as pd
import numpy as np
import pandas_ta as ta
import matplotlib.pyplot as plt
from datetime import datetime


def load_env():
    """Load Alpaca credentials from .env file."""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())


def load_data_from_alpaca(symbol, start='2000-01-01', end=None):
    """Download OHLCV data from Alpaca Markets API."""
    try:
        from alpaca_trade_api import REST
    except ImportError:
        raise ImportError("pip install alpaca-trade-api")

    api_key = os.environ.get('ALPACA_API_KEY')
    secret_key = os.environ.get('ALPACA_SECRET_KEY')
    if not api_key or not secret_key:
        raise ValueError("Missing Alpaca API keys. Set ALPACA_API_KEY and ALPACA_SECRET_KEY")

    api = REST(api_key, secret_key, 'https://paper-api.alpaca.markets', api_version='v2')

    if end is None:
        end = datetime.now().strftime('%Y-%m-%d')

    print(f'   Downloading {symbol} from Alpaca ({start} ~ {end})...')
    bars = api.get_bars(symbol, '1Day', start=start, end=end, adjustment='all', feed='iex').df

    if bars.empty:
        raise ValueError(f'No data for {symbol}')

    df = bars[['open', 'high', 'low', 'close', 'volume']].copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = df.sort_index()
    print(f'   ✅ {symbol}: {len(df)} bars ({df.index[0].date()} ~ {df.index[-1].date()})')
    return df


def load_data(file_path, header=None, names=None):
    """
    Load CSV data. Accepts column count from 2 (date,close) to 6 (date,o,h,l,c,vol).
    Auto-detects format. Expects timestamp as first column.
    """
    # Read first row to check structure
    raw = pd.read_csv(file_path, header=header, nrows=1)
    n_cols = raw.shape[1]

    if names is None:
        if n_cols == 2:
            names = ['timestamp', 'close']
        elif n_cols == 5:
            names = ['timestamp', 'open', 'high', 'low', 'close']
        elif n_cols == 6:
            names = ['timestamp', 'open', 'high', 'low', 'close', 'volume']

    df = pd.read_csv(file_path, header=header, names=names)

    # Parse timestamp
    if df['timestamp'].dtype == 'int64' or df['timestamp'].dtype == 'float64':
        df['time'] = pd.to_datetime(df['timestamp'], unit='s')
    else:
        df['time'] = pd.to_datetime(df['timestamp'])

    df = df.set_index('time').drop(columns=['timestamp'])
    return df


def macd_ema_strategy(data, params):
    """
    MACD + EMA Crossover Strategy (replica of Pine Script logic)

    Trading Rules:
    - L1 Entry: MACD histogram crosses above 0  (trend start)
    - L2 Entry: Short EMA crosses above Mid EMA (if already long)
    - L3 Entry: Short EMA crosses above Long EMA (if already long)
    - Exit: MACD histogram crosses below 0  OR  Short EMA crosses below Mid EMA
    - Optional: 200 EMA trend filter, ADX > 20 filter
    """
    fast_len = params.get('fast_len', 3)
    slow_len = params.get('slow_len', 11)
    sig_len = params.get('sig_len', 27)
    ema_s = params.get('ema_short', 3)
    ema_m = params.get('ema_mid', 11)
    ema_l = params.get('ema_long', 18)
    use_trend_filter = params.get('use_trend_filter', True)
    use_adx_filter = params.get('use_adx_filter', True)
    adx_period = params.get('adx_period', 14)
    atr_period = params.get('atr_period', 14)
    use_stop = params.get('use_stop', True)
    atr_stop_mult = params.get('atr_stop_mult', 3.0)
    use_trail = params.get('use_trail', True)
    trail_act = params.get('trail_activation', 0.015)
    trail_mult = params.get('trail_mult', 2.0)
    pyramiding = params.get('pyramiding', 3)
    position_size = params.get('position_size', 0.33)

    df = data.copy()

    # === Indicators ===
    df['ema_short'] = df['close'].ewm(span=ema_s, adjust=False).mean()
    df['ema_mid'] = df['close'].ewm(span=ema_m, adjust=False).mean()
    df['ema_long'] = df['close'].ewm(span=ema_l, adjust=False).mean()

    df['macd_line'] = df['close'].ewm(span=fast_len, adjust=False).mean() - df['close'].ewm(span=slow_len, adjust=False).mean()
    df['sig_line'] = df['macd_line'].ewm(span=sig_len, adjust=False).mean()
    df['histogram'] = df['macd_line'] - df['sig_line']

    df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()

    # ATR
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=atr_period)

    # ADX
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=adx_period)
    df['adx'] = adx_df.iloc[:, 0] if adx_df is not None else 0

    # === Signals ===
    df['macd_golong'] = (df['histogram'] > 0) & (df['histogram'].shift(1) <= 0)
    df['macd_goshort'] = (df['histogram'] < 0) & (df['histogram'].shift(1) >= 0)

    df['cross_mid'] = (df['ema_short'] > df['ema_mid']) & (df['ema_short'].shift(1) <= df['ema_mid'].shift(1))
    df['cross_long'] = (df['ema_short'] > df['ema_long']) & (df['ema_short'].shift(1) <= df['ema_long'].shift(1))
    df['death_cross'] = (df['ema_short'] < df['ema_mid']) & (df['ema_short'].shift(1) >= df['ema_mid'].shift(1))

    # Filters
    df['trend_ok'] = ~use_trend_filter | (df['close'] > df['ema_200'])
    df['adx_ok'] = ~use_adx_filter | (df['adx'] > 20)
    df['all_filters_ok'] = df['trend_ok'] & df['adx_ok']

    # Entry conditions
    df['enter_l1'] = df['macd_golong'] & df['all_filters_ok']
    df['enter_l2'] = df['cross_mid'] & df['all_filters_ok']
    df['enter_l3'] = df['cross_long'] & df['all_filters_ok']

    # Exit condition
    df['exit_signal'] = df['macd_goshort'] | df['death_cross']

    return df


def backtest_signals(data, params):
    """
    Run backtest. Supports pyramiding (up to 3 entries).
    Uses closing price for entries/exits by default.
    """
    df = macd_ema_strategy(data, params)

    initial_capital = params.get('initial_capital', 100000)
    pyramiding = params.get('pyramiding', 3)
    pos_size = params.get('position_size', 0.33)
    use_stop = params.get('use_stop', True)
    atr_stop_mult = params.get('atr_stop_mult', 3.0)
    use_trail = params.get('use_trail', True)
    trail_act = params.get('trail_activation', 0.015)
    trail_mult = params.get('trail_mult', 2.0)

    capital = initial_capital
    equity = initial_capital
    position = 0  # number of active entries (0 to pyramiding)
    entry_prices = []
    shares_per_entry = 0
    stop_price = None
    trail_on = False

    equity_curve = np.full(len(df), np.nan)
    trades = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        price = row['close']
        high = row['high']
        low = row['low']
        atr_val = row['atr'] if not pd.isna(row['atr']) else 0

        # Cash on the current bar (how much one entry buys)
        if position < pyramiding:
            shares_per_entry = (equity * pos_size) / price

        # === Exits ===
        # 1. Signal-based exit
        if position > 0 and row['exit_signal']:
            exit_val = shares_per_entry * price * position
            capital += exit_val
            equity = capital
            # Record trade
            avg_entry = np.mean(entry_prices) if entry_prices else 0
            pnl_pct = (price / avg_entry - 1) if avg_entry > 0 else 0
            trades.append({
                'exit_time': df.index[i],
                'type': 'signal',
                'pnl_pct': pnl_pct,
                'num_entries': position,
                'exit_price': price
            })
            position = 0
            entry_prices = []
            stop_price = None
            trail_on = False

        # 2. Stop loss hit
        elif position > 0 and use_stop and stop_price is not None and low <= stop_price:
            exit_price = min(price, stop_price)  # assume filled at or near stop
            exit_val = shares_per_entry * exit_price * position
            capital += exit_val
            equity = capital
            avg_entry = np.mean(entry_prices) if entry_prices else 0
            trades.append({
                'exit_time': df.index[i],
                'type': 'stop_loss',
                'pnl_pct': (exit_price / avg_entry - 1),
                'num_entries': position,
                'exit_price': exit_price
            })
            position = 0
            entry_prices = []
            stop_price = None
            trail_on = False

        # === Entries (only if no position or pyramiding available) ===
        can_enter = position < pyramiding
        if can_enter and row['enter_l1'] and position == 0:
            # First entry
            entry_prices = [price]
            position = 1
            capital -= shares_per_entry * price
            equity = capital + shares_per_entry * price * position
            # Set initial stop
            if use_stop and atr_val > 0:
                stop_price = price - atr_stop_mult * atr_val
            trail_on = False

        elif can_enter and row['enter_l2'] and position >= 1:
            entry_prices.append(price)
            position += 1
            capital -= shares_per_entry * price
            equity = capital + shares_per_entry * price * position
            # Ratchet stop
            if use_stop and atr_val > 0:
                new_stop = price - atr_stop_mult * atr_val
                if stop_price is None or new_stop > stop_price:
                    stop_price = new_stop

        elif can_enter and row['enter_l3'] and position >= 1:
            entry_prices.append(price)
            position += 1
            capital -= shares_per_entry * price
            equity = capital + shares_per_entry * price * position
            if use_stop and atr_val > 0:
                new_stop = price - atr_stop_mult * atr_val
                if stop_price is None or new_stop > stop_price:
                    stop_price = new_stop

        # === Trailing Stop ===
        if position > 0 and use_trail and atr_val > 0:
            avg_entry = np.mean(entry_prices) if entry_prices else price
            if not trail_on:
                if price >= avg_entry * (1 + trail_act):
                    trail_on = True
                    trail_stop = price - trail_mult * atr_val
                    stop_price = max(stop_price if stop_price is not None else 0, trail_stop)
            else:
                trail_stop = price - trail_mult * atr_val
                stop_price = max(stop_price if stop_price is not None else 0, trail_stop)

        # Reset stop when flat
        if position == 0:
            stop_price = None
            trail_on = False

        # Current equity
        equity_curve[i] = capital + (shares_per_entry * price * position) if position > 0 else capital

    # Final close
    if position > 0:
        final_price = df['close'].iloc[-1]
        exit_val = shares_per_entry * final_price * position
        capital += exit_val
        equity = capital
        avg_entry = np.mean(entry_prices) if entry_prices else 0
        trades.append({
            'exit_time': df.index[-1],
            'type': 'final_close',
            'pnl_pct': (final_price / avg_entry - 1),
            'num_entries': position,
            'exit_price': final_price
        })
        equity_curve[-1] = capital

    # Clean NaN at start
    valid_idx = np.where(~np.isnan(equity_curve))[0]
    if len(valid_idx) > 0:
        equity_curve[:valid_idx[0]] = equity_curve[valid_idx[0]] if valid_idx[0] > 0 else initial_capital

    df['equity'] = equity_curve

    return df, trades


def calc_metrics(equity_series, trades_df, initial_capital, annual_factor=252):
    """Calculate performance metrics."""
    final_equity = equity_series.iloc[-1]
    total_return = (final_equity / initial_capital) - 1

    # CAGR
    days = (equity_series.index[-1] - equity_series.index[0]).days
    if days > 0:
        cagr = (final_equity / initial_capital) ** (365 / days) - 1
    else:
        cagr = 0

    # Max drawdown
    peak = equity_series.expanding().max()
    dd = (peak - equity_series) / peak
    max_dd = dd.max()

    # Sharpe (uses daily returns from equity curve)
    daily_returns = equity_series.pct_change().dropna()
    if daily_returns.std() > 0:
        sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(annual_factor)
    else:
        sharpe = 0

    # Win rate (trade-level)
    if len(trades_df) > 0:
        win_rate = (trades_df['pnl_pct'] > 0).mean()
        avg_win = trades_df.loc[trades_df['pnl_pct'] > 0, 'pnl_pct'].mean() if (trades_df['pnl_pct'] > 0).any() else 0
        avg_loss = trades_df.loc[trades_df['pnl_pct'] <= 0, 'pnl_pct'].mean() if (trades_df['pnl_pct'] <= 0).any() else 0
        # Profit factor
        gross_profit = trades_df.loc[trades_df['pnl_pct'] > 0, 'pnl_pct'].sum()
        gross_loss = abs(trades_df.loc[trades_df['pnl_pct'] <= 0, 'pnl_pct'].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    else:
        win_rate = avg_win = avg_loss = profit_factor = 0

    return {
        'Total Return': f'{total_return:.2%}',
        'CAGR': f'{cagr:.2%}',
        'Max Drawdown': f'{max_dd:.2%}',
        'Sharpe Ratio': f'{sharpe:.2f}',
        'Win Rate': f'{win_rate:.2%}',
        'Avg Win': f'{avg_win:.2%}',
        'Avg Loss': f'{avg_loss:.2%}',
        'Profit Factor': f'{profit_factor:.2f}',
        'Total Trades': len(trades_df),
        'Final Equity': f'${final_equity:,.0f}'
    }


def plot_results(df, trades_df, title='MACD+EMA AI Strategy'):
    """Plot equity curve, drawdown, and trade markers."""
    fig, axes = plt.subplots(3, 1, figsize=(14, 9), gridspec_kw={'height_ratios': [3, 1, 1.5]})

    # --- Equity curve ---
    ax1 = axes[0]
    ax1.plot(df.index, df['equity'], label='Equity', color='navy', linewidth=1.5)
    peak = df['equity'].expanding().max()
    ax1.fill_between(df.index, df['equity'], peak, alpha=0.15, color='red', label='Drawdown')
    # Entry markers
    for _, t in trades_df.iterrows():
        if t['pnl_pct'] > 0:
            ax1.scatter(t['exit_time'], df.loc[df.index <= t['exit_time'], 'equity'].iloc[-1] if t['exit_time'] in df.index else 0,
                       color='green', s=20, zorder=5)
        else:
            ax1.scatter(t['exit_time'], df.loc[df.index <= t['exit_time'], 'equity'].iloc[-1] if t['exit_time'] in df.index else 0,
                       color='red', s=20, zorder=5)
    ax1.set_title(f'{title} — Equity Curve', fontsize=13)
    ax1.set_ylabel('Equity ($)')
    ax1.legend(loc='upper left')
    ax1.grid(alpha=0.3)

    # --- Drawdown ---
    ax2 = axes[1]
    dd_pct = (peak - df['equity']) / peak * 100
    ax2.fill_between(df.index, dd_pct, 0, color='red', alpha=0.4)
    ax2.set_ylabel('Drawdown %')
    ax2.set_ylim(bottom=max(dd_pct.max() * 1.2, 5))
    ax2.invert_yaxis()
    ax2.grid(alpha=0.3)

    # --- Price with signals ---
    ax3 = axes[2]
    ax3.plot(df.index, df['close'], label='Close', color='gray', alpha=0.6, linewidth=1)
    signal_buy = df['enter_l1'] | df['enter_l2'] | df['enter_l3']
    signal_sell = df['exit_signal']
    ax3.scatter(df.index[signal_buy], df['close'][signal_buy] * 0.98, marker='^', color='lime', s=40, label='Buy', zorder=5)
    ax3.scatter(df.index[signal_sell], df['close'][signal_sell] * 1.02, marker='v', color='red', s=40, label='Sell', zorder=5)
    ax3.set_ylabel('Price')
    ax3.legend(loc='upper left')
    ax3.grid(alpha=0.3)

    plt.tight_layout()
    return fig


def opt_backtest(data, params):
    """Run backtest for a single param set and return metrics dict."""
    df_result, trades = backtest_signals(data, params)
    trades_df = pd.DataFrame(trades)
    metrics = calc_metrics(df_result['equity'], trades_df, params['initial_capital'])
    return metrics, trades_df, df_result


def param_sweep(data, param_grid, ticker, use_cagr=False):
    """Grid search over parameter grid. Returns results sorted by return."""
    results = []
    total = 1
    for v in param_grid.values():
        total *= len(v)
    idx = 0
    # Pre-compute base params
    base = {
        'initial_capital': 100000,
        'atr_period': 14,
        'adx_period': 14,
        'use_stop': True,
        'use_trail': True,
        'trail_activation': 0.015,
        'trail_mult': 2.0,
        'use_trend_filter': True,
        'use_adx_filter': True,
        'pyramiding': 3,
        'position_size': 0.33,
    }
    for fl in param_grid.get('fast_len', [3]):
        for sl in param_grid.get('slow_len', [11]):
            for sgl in param_grid.get('sig_len', [27]):
                for es in param_grid.get('ema_short', [3]):
                    for em in param_grid.get('ema_mid', [11]):
                        for el in param_grid.get('ema_long', [18]):
                            for atr in param_grid.get('atr_stop_mult', [3.0]):
                                for tr in param_grid.get('trail_mult', [2.0]):
                                    for trail_act_pct in param_grid.get('trail_activation', [0.015]):
                                        for pyra in param_grid.get('pyramiding', [3]):
                                            idx += 1
                                            p = dict(base)
                                            p.update({
                                                'fast_len': fl, 'slow_len': sl, 'sig_len': sgl,
                                                'ema_short': es, 'ema_mid': em, 'ema_long': el,
                                                'atr_stop_mult': atr,
                                                'trail_mult': tr,
                                                'trail_activation': trail_act_pct,
                                                'pyramiding': pyra,
                                            })
                                            try:
                                                m, _, _ = opt_backtest(data, p)
                                                total_ret = float(m['Total Return'].rstrip('%'))
                                                cagr = float(m['CAGR'].rstrip('%'))
                                                dd = float(m['Max Drawdown'].rstrip('%'))
                                                sharpe = float(m['Sharpe Ratio'])
                                                results.append({
                                                    **p,
                                                    'return': total_ret,
                                                    'cagr': cagr,
                                                    'max_dd': dd,
                                                    'sharpe': sharpe,
                                                    'trades': m['Total Trades'],
                                                })
                                            except Exception as e:
                                                pass
    # Score: combine return with penalties
    for r in results:
        score_key = 'cagr' if use_cagr else 'return'
        dd_penalty = max(0, r['max_dd'] - 30) * 0.5
        r['score'] = r[score_key] - dd_penalty
    results.sort(key=lambda x: x['score'], reverse=True)
    return results


if __name__ == '__main__':
    load_env()

    TICKERS = ['NVDA', 'AMD', 'AVGO', 'TSM', 'MU']
    START = '2018-01-01'
    END = '2026-06-26'
    FOCUS = 'NVDA'  # Optimize on NVDA, then test on the rest

    # ---------- Choose mode ----------
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--optimize', action='store_true', help='Run parameter optimization sweep')
    parser.add_argument('--single', action='store_true', help='Run single-param backtest on all tickers (default)')
    args = parser.parse_args()

    if args.optimize:
        # ===== PARAM SWEEP MODE =====
        param_grid = {
            'fast_len':    [3, 5],
            'slow_len':    [8, 11, 14],
            'sig_len':     [27],
            'ema_short':   [3, 5],
            'ema_mid':     [8, 11, 14],
            'ema_long':    [18],
            'atr_stop_mult': [2.0, 3.0, 4.0],
            'trail_mult':    [2.0, 3.0],
            'trail_activation': [0.015],
            'pyramiding':     [1, 3],
        }
        total_combo = 1
        for v in param_grid.values():
            total_combo *= len(v)
        print(f'Running param sweep: {total_combo} combos on {FOCUS}...\n')

        data = load_data_from_alpaca(FOCUS, START, END)
        results = param_sweep(data, param_grid, FOCUS)

        print(f'\n🏆 Top 15 Parameter Sets (sorted by score = return - dd_penalty)')
        print(f'{"Rank":<5} {"MACD":<14} {"EMA":<14} {"ATRstop":<8} {"Trail":<10} {"Pyra":<5} {"Return":>8} {"CAGR":>8} {"MaxDD":>7} {"Sharpe":>7} {"Trades":>7}')
        print('-' * 95)
        for rank, r in enumerate(results[:15], 1):
            macd = f"{r['fast_len']},{r['slow_len']},{r['sig_len']}"
            ema = f"{r['ema_short']},{r['ema_mid']},{r['ema_long']}"
            trl = f"{r['trail_activation']*100:.1f}%/{r['trail_mult']}×"
            print(f"{rank:<5} {macd:<14} {ema:<14} {r['atr_stop_mult']:<8.1f} {trl:<10} {r['pyramiding']:<5} {r['return']:>7.2f}% {r['cagr']:>7.2f}% {r['max_dd']:>6.2f}% {r['sharpe']:>6.2f} {r['trades']:>6}")

        # Best params
        best = results[0]
        print(f'\n✅ Best Params for {FOCUS}:')
        print(f'   MACD({best["fast_len"]},{best["slow_len"]},{best["sig_len"]})')
        print(f'   EMA({best["ema_short"]}/{best["ema_mid"]}/{best["ema_long"]})')
        print(f'   ATR Stop: {best["atr_stop_mult"]}×')
        print(f'   Trail: {best["trail_activation"]*100}% / {best["trail_mult"]}×')
        print(f'   Pyramiding: {best["pyramiding"]}')
        print(f'   Return: {best["return"]:.2f}% | CAGR: {best["cagr"]:.2f}% | DD: {best["max_dd"]:.2f}% | Sharpe: {best["sharpe"]:.2f}')

    else:
        # ===== SINGLE BACKTEST (default) =====
        # Best params from optimization on NVDA:
        params = {
            'initial_capital': 100000,
            'fast_len': 3,
            'slow_len': 8,
            'sig_len': 27,
            'ema_short': 5,
            'ema_mid': 8,
            'ema_long': 18,
            'use_trend_filter': True,
            'use_adx_filter': True,
            'adx_period': 14,
            'atr_period': 14,
            'use_stop': True,
            'atr_stop_mult': 3.0,
            'use_trail': True,
            'trail_activation': 0.015,
            'trail_mult': 3.0,
            'pyramiding': 3,
            'position_size': 0.33,
        }

        print('=' * 65)
        print('   MACD+EMA AI Stocks Strategy — Alpaca Backtest')
        print('=' * 65)
        print(f'\n📊 Tickers: {", ".join(TICKERS)}')
        print(f'📅 Period:  {START} ~ {END}')
        print(f'📐 Params:  MACD({params["fast_len"]},{params["slow_len"]},{params["sig_len"]})')
        print(f'            EMA({params["ema_short"]}/{params["ema_mid"]}/{params["ema_long"]})')
        print(f'            ATR Stop: {params["atr_stop_mult"]}× | Trail: {params["trail_activation"]*100}%/{params["trail_mult"]}×')

        all_metrics = {}

        for sym in TICKERS:
            print(f'\n─── {sym} ────────────────────────────────────────')
            try:
                data = load_data_from_alpaca(sym, START, END)
            except Exception as e:
                print(f'   ❌ {e}')
                continue

            m, trades_df, df_result = opt_backtest(data, params)
            all_metrics[sym] = m

            print(f'\n   📈 {sym} Results:')
            for k, v in m.items():
                print(f'      {k:20s}: {v}')

            fig = plot_results(df_result, trades_df, f'{sym} — MACD+EMA AI Strategy')
            fig.savefig(f'ai_stocks_{sym}.png', dpi=150, bbox_inches='tight')
            plt.close(fig)

        print('\n' + '=' * 65)
        print('   📊 SUMMARY — All Stocks')
        print('=' * 65)
        header = f"{'Ticker':<8} {'Return':>10} {'CAGR':>10} {'MaxDD':>10} {'Sharpe':>8} {'WinRate':>8} {'Trades':>7}"
        print(f'\n{header}')
        print('-' * 65)
        for sym, m in all_metrics.items():
            print(f"{sym:<8} {m['Total Return']:>10} {m['CAGR']:>10} {m['Max Drawdown']:>10} {m['Sharpe Ratio']:>8} {m['Win Rate']:>8} {m['Total Trades']:>7}")
        print('-' * 65)
        print('\n✅ All backtests complete!')
