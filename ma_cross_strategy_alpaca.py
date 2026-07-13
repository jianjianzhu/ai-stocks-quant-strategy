import os
import pandas as pd
import numpy as np
import pandas_ta as ta
from datetime import datetime

# ========== 从Alpaca加载数据 ==========
def load_data_from_alpaca(symbol='SPY', timeframe='1D', start='2000-01-01', end='2026-06-19'):
    """通过Alpaca Trade API获取历史K线数据"""
    try:
        import alpaca_trade_api as tradeapi
    except ImportError:
        raise ImportError("请先安装 alpaca-trade-api: pip install alpaca-trade-api")

    # 从环境变量读取API Key，若未设置则提示用户
    api_key = os.environ.get('ALPACA_API_KEY')
    secret_key = os.environ.get('ALPACA_SECRET_KEY')

    if not api_key or not secret_key:
        print("[WARN]  未找到 Alpaca API Key！")
        print("   请设置环境变量：")
        print("     ALPACA_API_KEY=你的API Key")
        print("     ALPACA_SECRET_KEY=你的Secret Key")
        print("   或在代码中直接填入。")
        print("   免费注册: https://alpaca.markets/")
        raise ValueError("缺少Alpaca API凭证")

    # 初始化API (使用免费数据端点)
    base_url = 'https://paper-api.alpaca.markets'
    api = tradeapi.REST(api_key, secret_key, base_url, api_version='v2')

    print(f"[DATA] 正在从Alpaca下载 {symbol} 数据 ({timeframe})...")
    print(f"   时间范围: {start} ~ {end}")

    # 获取历史K线
    barset = api.get_bars(
        symbol,
        timeframe,
        start=start,
        end=end,
        adjustment='all',  # 复权调整
        feed='iex'         # 免费版使用IEX数据源
    ).df

    if barset.empty:
        raise ValueError("未获取到数据，请检查股票代码和时间范围")

    # 转换为标准OHLC格式
    df = barset[['open', 'high', 'low', 'close', 'volume']].copy()
    df.index = pd.to_datetime(df.index)
    # 移除时区信息，避免与tz-naive的datetime比较报错
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = df.sort_index()

    print(f"[OK] 数据下载完成，共 {len(df)} 条记录")
    print(f"   时间范围: {df.index.min()} 到 {df.index.max()}")
    return df

# ========== 从本地CSV加载数据（兼容原逻辑） ==========
def load_data_from_csv(file_path):
    """加载CSV数据，处理Unix时间戳"""
    df = pd.read_csv(file_path, header=None, names=['timestamp', 'open', 'high', 'low', 'close'])

    # 过滤非数值行
    df = df[pd.to_numeric(df['timestamp'], errors='coerce').notna()]
    df['timestamp'] = pd.to_numeric(df['timestamp'])

    # 转换时间戳
    df['time'] = pd.to_datetime(df['timestamp'], unit='s')
    df = df.set_index('time')
    df = df.drop(columns=['timestamp'])

    # 转换价格类型
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['open', 'high', 'low', 'close'])

    return df

# ========== 单次回测函数 ==========
def run_backtest(data, ma_type1, ma_type2, ma_length1, ma_length2,
                 start_time, end_time, atr_len=14,
                 commission=0.001, slippage=0.001, use_atr_stop=True):
    """运行单次回测，返回绩效指标

    出场策略：ATR移动止损（价格上涨则自动上调止损位）
    参数:
        commission: 单边手续费率，默认0.001(0.1%)，一开一平总成本0.2%
        slippage: 滑点率，默认0.001(0.1%)，用于模拟订单成交时的价格偏移
        use_atr_stop: 是否使用ATR动态止损，False则使用固定百分比止损
    """
    df = data.loc[start_time:end_time].copy()

    # 计算均线
    if ma_type1 == 'EMA':
        df['ma1'] = ta.ema(df['close'], length=ma_length1)
    else:
        df['ma1'] = ta.sma(df['close'], length=ma_length1)

    if ma_type2 == 'EMA':
        df['ma2'] = ta.ema(df['close'], length=ma_length2)
    else:
        df['ma2'] = ta.sma(df['close'], length=ma_length2)

    # 计算ATR — 用于动态止损
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=atr_len)

    # 计算初始止损价
    if use_atr_stop:
        df['init_long_stop'] = df['close'] - df['atr'] * 2.0
        df['init_short_stop'] = df['close'] + df['atr'] * 2.0
    else:
        df['init_long_stop'] = df['close'] * 0.98
        df['init_short_stop'] = df['close'] * 1.02

    # 交易信号
    df['trend_up'] = df['ma1'] > df['ma2']
    df['trend_dn'] = df['ma1'] < df['ma2']
    # 金叉/死叉当天
    df['golden_cross'] = df['trend_up'] & ~df['trend_up'].shift(1).fillna(False)
    df['death_cross'] = df['trend_dn'] & ~df['trend_dn'].shift(1).fillna(False)

    # 回测循环
    position = 0
    entry_price = 0.0
    stop_price = 0.0
    entry_bar = -999
    equity_curve = [10000]
    trades = 0
    total_commission = 0

    for i in range(1, len(df)):
        # === 出场 ===
        if position == 1:
            # 出场条件1: 趋势反转（死叉）
            if df['death_cross'].iloc[i]:
                exit_price = df['close'].iloc[i] * (1 - slippage)
                pnl = (exit_price - entry_price) / entry_price
                pre_exit_equity = equity_curve[-1]
                new_equity = pre_exit_equity * (1 + pnl) * (1 - commission)
                total_commission += pre_exit_equity * (1 + pnl) * commission
                equity_curve.append(new_equity)
                position = 0
                continue
            # 出场条件2: ATR硬止损
            if df['low'].iloc[i] <= stop_price:
                exit_price = stop_price * (1 - slippage)
                pnl = (exit_price - entry_price) / entry_price
                pre_exit_equity = equity_curve[-1]
                new_equity = pre_exit_equity * (1 + pnl) * (1 - commission)
                total_commission += pre_exit_equity * (1 + pnl) * commission
                equity_curve.append(new_equity)
                position = 0
                continue
            # 出场条件3: 收盘价跌破快线(ma1) → 趋势减弱，主动止盈
            if df['close'].iloc[i] < df['ma1'].iloc[i]:
                exit_price = df['close'].iloc[i] * (1 - slippage)
                pnl = (exit_price - entry_price) / entry_price
                pre_exit_equity = equity_curve[-1]
                new_equity = pre_exit_equity * (1 + pnl) * (1 - commission)
                total_commission += pre_exit_equity * (1 + pnl) * commission
                equity_curve.append(new_equity)
                position = 0
                continue
        elif position == -1:
            if df['golden_cross'].iloc[i]:
                exit_price = df['close'].iloc[i] * (1 + slippage)
                pnl = (entry_price - exit_price) / entry_price
                pre_exit_equity = equity_curve[-1]
                new_equity = pre_exit_equity * (1 + pnl) * (1 - commission)
                total_commission += pre_exit_equity * (1 + pnl) * commission
                equity_curve.append(new_equity)
                position = 0
                continue
            if df['high'].iloc[i] >= stop_price:
                exit_price = stop_price * (1 + slippage)
                pnl = (entry_price - exit_price) / entry_price
                pre_exit_equity = equity_curve[-1]
                new_equity = pre_exit_equity * (1 + pnl) * (1 - commission)
                total_commission += pre_exit_equity * (1 + pnl) * commission
                equity_curve.append(new_equity)
                position = 0
                continue
            if df['close'].iloc[i] > df['ma1'].iloc[i]:
                exit_price = df['close'].iloc[i] * (1 + slippage)
                pnl = (entry_price - exit_price) / entry_price
                pre_exit_equity = equity_curve[-1]
                new_equity = pre_exit_equity * (1 + pnl) * (1 - commission)
                total_commission += pre_exit_equity * (1 + pnl) * commission
                equity_curve.append(new_equity)
                position = 0
                continue

        # === 入场 ===
        if position == 0:
            if (i - entry_bar) > 2:
                if df['golden_cross'].iloc[i] and df['atr'].notna().iloc[i]:
                    position = 1
                    entry_price = df['close'].iloc[i] * (1 + slippage)
                    stop_price = df['init_long_stop'].iloc[i]
                    entry_bar = i
                    trades += 1
                    fee = equity_curve[-1] * commission
                    total_commission += fee
                    equity_curve[-1] -= fee
                elif df['death_cross'].iloc[i] and df['atr'].notna().iloc[i]:
                    position = -1
                    entry_price = df['close'].iloc[i] * (1 - slippage)
                    stop_price = df['init_short_stop'].iloc[i]
                    entry_bar = i
                    trades += 1
                    fee = equity_curve[-1] * commission
                    total_commission += fee
                    equity_curve[-1] -= fee

    # 计算绩效
    if len(equity_curve) > 1:
        total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0]
        days = max((end_time - start_time).days, 1)
        annual_return = (1 + total_return) ** (1 / (days / 365)) - 1
        max_drawdown = (pd.Series(equity_curve).cummax() - pd.Series(equity_curve)).max() / pd.Series(equity_curve).cummax().max()
        returns = pd.Series(equity_curve).pct_change().dropna()
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() != 0 else 0
        win_rate = (returns > 0).sum() / len(returns) if len(returns) > 0 else 0
    else:
        total_return = annual_return = max_drawdown = sharpe = win_rate = 0

    return {
        '组合': f"{ma_type1}({ma_length1})/{ma_type2}({ma_length2})",
        '总收益率': total_return,
        '年化收益率': annual_return,
        '最大回撤': max_drawdown,
        '夏普比率': sharpe,
        '胜率': win_rate,
        '交易次数': trades,
        '手续费成本': total_commission,
        'ATR止损': use_atr_stop,
    }

# ========== 主程序 ==========
if __name__ == "__main__":
    print("="*70)
    print("[STRATEGY] 均线交叉策略 - Alpaca数据源回测")
    print("="*70)

    # 加载数据（优先Alpaca，失败则回退本地CSV）
    print("\n[FILE] 加载数据...")
    use_alpaca = True
    try:
        data = load_data_from_alpaca(
            symbol='SPY',
            timeframe='1Day',
            start='2000-01-01',
            end='2026-06-19'
        )
    except Exception as e:
        print(f"\n[FAIL] Alpaca数据获取失败: {e}")
        print("   尝试回退到本地CSV文件...")
        try:
            data = load_data_from_csv('SPCFD_SPX, 1M.csv')
            use_alpaca = False
            print(f"[OK] 本地数据加载完成，共 {len(data)} 条记录")
        except Exception as e2:
            print(f"[FAIL] 本地数据也加载失败: {e2}")
            print("\n[TIP] 提示：")
            print("   1. 设置Alpaca环境变量后重试:")
            print("      export ALPACA_API_KEY=你的Key")
            print("      export ALPACA_SECRET_KEY=你的Secret")
            print("   2. 或将本地CSV文件放置于同目录下")
            exit(1)

    # 数据切片
    start_time = datetime(2000, 1, 1)
    end_time = datetime(2026, 6, 19)
    data = data.loc[start_time:end_time]
    print(f"\n[DATE] 回测时间范围: {data.index.min()} 到 {data.index.max()}")

    # 定义要测试的组合
    # 用更短的均线周期，增加交叉频率
    ma_types = ['SMA', 'EMA']
    short_lengths = [5, 10, 15, 20]
    long_lengths = [20, 30, 40, 50, 60]
    stop_modes = [True, False]  # True=ATR止损, False=固定百分比止损

    # 生成所有组合
    combinations = []
    for ma1 in ma_types:
        for ma2 in ma_types:
            for l1 in short_lengths:
                for l2 in long_lengths:
                    if l1 < l2:  # 短期均线必须小于长期均线
                        for use_atr in stop_modes:
                            combinations.append((ma1, ma2, l1, l2, use_atr))

    print(f"\n[INFO] 共 {len(combinations)} 组参数待测试")
    print("[TEST] 运行参数优化回测 (含0.1%手续费)...\n")
    results = []
    for idx, (ma1, ma2, l1, l2, use_atr) in enumerate(combinations):
        print(f"  [{idx+1}/{len(combinations)}] 测试: {ma1}({l1})/{ma2}({l2}) ATR={use_atr} ...")
        result = run_backtest(data, ma1, ma2, l1, l2, start_time, end_time,
                              commission=0.001, slippage=0.001, use_atr_stop=use_atr)
        results.append(result)
        print(f"    总收益率: {result['总收益率']:.2%} | 夏普: {result['夏普比率']:.2f} | 交易: {result['交易次数']}")

    # 输出对比结果
    print("\n" + "="*70)
    print("[STRATEGY] 参数优化结果对比")
    print("="*70)
    print(f"{'组合':<20} {'总收益率':>12} {'年化收益率':>12} {'最大回撤':>12} {'夏普比率':>10} {'交易次数':>10}")
    print("-"*70)

    # 多维度筛选最优
    best_return = max(results, key=lambda x: x['总收益率'])
    best_sharpe = max(results, key=lambda x: x['夏普比率'])
    best_calmar = max(results, key=lambda x: x['年化收益率'] / max(x['最大回撤'], 0.001))

    # 只展示夏普>0且交易次数>=3的有效策略
    valid_results = [r for r in results if r['夏普比率'] > 0 and r['交易次数'] >= 3]
    valid_results.sort(key=lambda x: x['夏普比率'], reverse=True)

    print("-"*70)
    print(f"{'组合':<20} {'总收益率':>10} {'年化':>8} {'回撤':>8} {'夏普':>8} {'交易':>6} {'止损':>6}")
    print("-"*70)
    for r in valid_results[:15]:  # 展示前15名
        stop_type = 'ATR' if r['ATR止损'] else '固定'
        print(f"{r['组合']:<20} {r['总收益率']:>9.2%} {r['年化收益率']:>7.2%} {r['最大回撤']:>7.2%} {r['夏普比率']:>7.2f} {r['交易次数']:>6} {stop_type:>6}")

    print("-"*70)
    print(f"\n[BEST] 最高收益组合: {best_return['组合']} (ATR={best_return['ATR止损']})")
    print(f"   总收益率: {best_return['总收益率']:.2%}")
    print(f"   年化收益率: {best_return['年化收益率']:.2%}")
    print(f"   最大回撤: {best_return['最大回撤']:.2%}")
    print(f"   夏普比率: {best_return['夏普比率']:.2f}")
    print(f"   胜率: {best_return['胜率']:.2%}")
    print(f"   交易次数: {best_return['交易次数']}")
    print(f"   手续费成本: ${best_return['手续费成本']:.2f}")

    print(f"\n[INFO] 最高夏普组合: {best_sharpe['组合']} (ATR={best_sharpe['ATR止损']})")
    print(f"   夏普比率: {best_sharpe['夏普比率']:.2f}")
    print(f"   总收益率: {best_sharpe['总收益率']:.2%}")
    print(f"   最大回撤: {best_sharpe['最大回撤']:.2%}")

    print("\n" + "="*70)
    print("[OK] 参数优化完成！")
    if use_alpaca:
        print("[DATA] 数据来源: Alpaca Markets")
    else:
        print("[FILE] 数据来源: 本地CSV")
    print("="*70)
