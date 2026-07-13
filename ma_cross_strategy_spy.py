import pandas as pd
import numpy as np
import pandas_ta as ta
import matplotlib.pyplot as plt
from datetime import datetime

# ========== 加载数据 ==========
def load_data(file_path):
    """加载CSV数据，自动识别格式（yfinance标准格式或旧版Unix时间戳格式）"""

    # 先读取前几行判断格式
    with open(file_path, 'r', encoding='utf-8') as f:
        first_lines = [f.readline().strip() for _ in range(5)]

    # 判断是否为yfinance格式（第一行是表头，包含Date/Open/High/Low/Close/Volume）
    if 'Date' in first_lines[0] or 'Price' in first_lines[0]:
        # yfinance格式: 需要跳过前两行（Ticker行），从第3行开始是数据
        df = pd.read_csv(file_path, skiprows=[1, 2])

        # 处理多级表头（yfinance默认输出）
        if 'Price' in df.columns:
            df = df.rename(columns={'Price': 'Date'})

        # 设置日期索引
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date')
        df.index.name = 'time'

        # 标准化列名（小写）
        df = df.rename(columns={
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume'
        })

        print(f"   检测到yfinance格式数据")

    else:
        # 旧版Unix时间戳格式（无表头）
        df = pd.read_csv(file_path, header=None, names=['timestamp', 'open', 'high', 'low', 'close'])

        # 过滤非数值行
        df = df[pd.to_numeric(df['timestamp'], errors='coerce').notna()]
        df['timestamp'] = pd.to_numeric(df['timestamp'])

        # 转换时间戳
        df['time'] = pd.to_datetime(df['timestamp'], unit='s')
        df = df.set_index('time')
        df = df.drop(columns=['timestamp'])

        print(f"   检测到旧版Unix时间戳格式数据")

    # 转换价格类型
    for col in ['open', 'high', 'low', 'close']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df = df.dropna(subset=['open', 'high', 'low', 'close'])

    return df

# ========== 单次回测函数 ==========
def run_backtest(data, ma_type1, ma_type2, ma_length1, ma_length2, 
                 start_time, end_time, atr_len=14, swing_lookback=5):
    """运行单次回测，返回绩效指标"""
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
    
    # 计算ATR
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=atr_len)
    
    # 计算止损止盈
    df['lowest_low'] = df['low'].rolling(window=swing_lookback).min()
    df['highest_high'] = df['high'].rolling(window=swing_lookback).max()
    df['long_stop'] = df['lowest_low'] - df['atr']
    df['short_stop'] = df['highest_high'] + df['atr']
    df['long_limit'] = df['close'] + (df['close'] - df['long_stop'])
    df['short_limit'] = df['close'] - (df['short_stop'] - df['close'])
    
    # 交易信号
    df['ma1_cross_up'] = df['ma1'] > df['ma2']
    df['ma1_cross_dn'] = df['ma1'] < df['ma2']
    df['valid_long'] = df['ma1_cross_up'] & df['atr'].notna()
    df['valid_short'] = df['ma1_cross_dn'] & df['atr'].notna()
    
    # 回测循环
    position = 0
    entry_price = 0.0
    stop_price = 0.0
    target_price = 0.0
    equity_curve = [10000]
    trades = 0
    
    for i in range(1, len(df)):
        # 开仓
        if df['valid_long'].iloc[i] and position == 0:
            position = 1
            entry_price = df['close'].iloc[i]
            stop_price = df['long_stop'].iloc[i]
            target_price = df['long_limit'].iloc[i]
            trades += 1
        elif df['valid_short'].iloc[i] and position == 0:
            position = -1
            entry_price = df['close'].iloc[i]
            stop_price = df['short_stop'].iloc[i]
            target_price = df['short_limit'].iloc[i]
            trades += 1
        
        # 平仓
        if position == 1:
            if df['low'].iloc[i] <= stop_price or df['high'].iloc[i] >= target_price:
                exit_price = df['close'].iloc[i]
                equity_curve.append(equity_curve[-1] * (1 + (exit_price - entry_price) / entry_price))
                position = 0
        elif position == -1:
            if df['high'].iloc[i] >= stop_price or df['low'].iloc[i] <= target_price:
                exit_price = df['close'].iloc[i]
                equity_curve.append(equity_curve[-1] * (1 + (entry_price - exit_price) / entry_price))
                position = 0
    
    # 计算绩效
    if len(equity_curve) > 1:
        total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0]
        annual_return = (1 + total_return) ** (1 / ((end_time - start_time).days / 365)) - 1
        max_drawdown = (pd.Series(equity_curve).cummax() - pd.Series(equity_curve)).max() / pd.Series(equity_curve).cummax().max()
        returns = pd.Series(equity_curve).pct_change().dropna()
        sharpe = (returns.mean() / returns.std()) * np.sqrt(12) if returns.std() != 0 else 0
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
        '交易次数': trades
    }

# ========== 主程序 ==========
if __name__ == "__main__":
    print("="*70)
    print("[STRATEGY] 均线交叉策略 - 参数优化")
    print("="*70)
    
    # 加载数据
    print("\n[FILE] 加载数据...")
    # 使用 Quant_Data 文件夹中的 AAPL_daily.csv
    data_file = r'D:\Quant_Data\AAPL_daily.csv'
    data = load_data(data_file)
    start_time = datetime(2020, 1, 1)
    end_time = datetime(2026, 6, 19)
    data = data.loc[start_time:end_time]
    print(f"[OK] 数据加载完成，共 {len(data)} 条记录")
    print(f"   时间范围: {data.index.min()} 到 {data.index.max()}")
    
    # 定义要测试的组合
    combinations = [
        ('SMA', 'SMA', 50, 200),
        ('EMA', 'EMA', 10, 30),
        ('EMA', 'EMA', 20, 100),
        ('SMA', 'SMA', 20, 120),
    ]
    
    # 运行回测
    print("\n[TEST] 运行参数优化回测...\n")
    results = []
    for ma1, ma2, l1, l2 in combinations:
        print(f"  测试: {ma1}({l1}) / {ma2}({l2}) ...")
        result = run_backtest(data, ma1, ma2, l1, l2, start_time, end_time)
        results.append(result)
        print(f"    总收益率: {result['总收益率']:.2%}")
    
    # 输出对比结果
    print("\n" + "="*70)
    print("[STRATEGY] 参数优化结果对比")
    print("="*70)
    print(f"{'组合':<20} {'总收益率':>12} {'年化收益率':>12} {'最大回撤':>12} {'夏普比率':>10} {'交易次数':>10}")
    print("-"*70)
    
    best = max(results, key=lambda x: x['总收益率'])
    for r in results:
        print(f"{r['组合']:<20} {r['总收益率']:>11.2%} {r['年化收益率']:>11.2%} {r['最大回撤']:>11.2%} {r['夏普比率']:>9.2f} {r['交易次数']:>10}")
    
    print("-"*70)
    print(f"\n[BEST] 最优组合: {best['组合']}")
    print(f"   总收益率: {best['总收益率']:.2%}")
    print(f"   年化收益率: {best['年化收益率']:.2%}")
    print(f"   最大回撤: {best['最大回撤']:.2%}")
    print(f"   夏普比率: {best['夏普比率']:.2f}")
    print(f"   胜率: {best['胜率']:.2%}")
    print(f"   交易次数: {best['交易次数']}")
    
    print("\n" + "="*70)
    print("[OK] 参数优化完成！")
    print("="*70)