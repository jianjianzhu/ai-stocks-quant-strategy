import pandas as pd
import numpy as np
import pandas_ta as ta
import matplotlib.pyplot as plt
from datetime import datetime

# ========== 加载数据（修正时间戳解析） ==========
def load_data(file_path):
    # 读取CSV，没有表头，列名是：timestamp, open, high, low, close
    df = pd.read_csv(file_path, header=None, names=['timestamp', 'open', 'high', 'low', 'close'])
    
    # 将Unix时间戳转换为日期时间
    df['time'] = pd.to_datetime(df['timestamp'], unit='s')
    
    # 设置为索引
    df = df.set_index('time')
    
    # 删除原始时间戳列
    df = df.drop(columns=['timestamp'])
    
    return df

# ========== 加载数据 ==========
data = load_data('SPCFD_SPX, 1M.csv')

# 筛选时间范围: 2000-01-01 到 2026-06-19
start_time = datetime(2000, 1, 1)
end_time = datetime(2026, 6, 19)
data = data.loc[start_time:end_time]

print(f"✅ 数据加载完成，共 {len(data)} 条记录")
print(f"   时间范围: {data.index.min()} 到 {data.index.max()}")
print(data.head())

# ========== 策略参数 ==========
ma_type1 = 'EMA'
ma_type2 = 'EMA'
ma_length1 = 21
ma_length2 = 50
atr_len = 14
swing_lookback = 5
risk_m = 1
rnr = 1
trail_stop_size = 1.0
trail_source = 'High/Low'
max_perc_dd = 20
FLIP = False
longTrades = True
shortTrades = True
confirmed = True

# ========== 计算指标 ==========
# 计算移动平均线
data['ma1'] = data['close'].ta.ma(ma_type1, length=ma_length1)
data['ma2'] = data['close'].ta.ma(ma_type2, length=ma_length2)

# 计算 ATR
data['atr'] = data['close'].ta.atr(length=atr_len)

# 计算摆动高低点
data['lowest_low'] = data['low'].rolling(window=swing_lookback).min()
data['highest_high'] = data['high'].rolling(window=swing_lookback).max()

# 定义止损和目标价格
data['long_stop'] = data['lowest_low'] - (data['atr'] * risk_m)
data['short_stop'] = data['highest_high'] + (data['atr'] * risk_m)
data['long_limit'] = data['close'] + (rnr * (data['close'] - data['long_stop']))
data['short_limit'] = data['close'] - (rnr * (data['short_stop'] - data['close']))

# 定义交易条件
data['ma1_cross_up_2'] = data['ma1'] > data['ma2']
data['ma1_cross_dn_2'] = data['ma1'] < data['ma2']
data['valid_long_entry'] = (data['ma1_cross_up_2']) & (data['atr'].notna())
data['valid_short_entry'] = (data['ma1_cross_dn_2']) & (data['atr'].notna())

# ========== 简化的回测逻辑 ==========
def backtest(data):
    position = 0  # 0: FLAT, 1: LONG, -1: SHORT
    entry_price = 0.0
    trade_stop_price = 0.0
    trade_target_price = 0.0
    equity_curve = [10000]  # 初始资本
    
    for i in range(1, len(data)):
        # 开仓条件
        if data['valid_long_entry'].iloc[i] and position == 0 and longTrades:
            position = 1
            entry_price = data['close'].iloc[i]
            trade_stop_price = data['long_stop'].iloc[i]
            trade_target_price = data['long_limit'].iloc[i]
            
        elif data['valid_short_entry'].iloc[i] and position == 0 and shortTrades:
            position = -1
            entry_price = data['close'].iloc[i]
            trade_stop_price = data['short_stop'].iloc[i]
            trade_target_price = data['short_limit'].iloc[i]
            
        # 平仓条件
        if position == 1:
            if data['low'].iloc[i] <= trade_stop_price or data['high'].iloc[i] >= trade_target_price:
                exit_price = data['close'].iloc[i]
                equity_curve.append(equity_curve[-1] * (1 + (exit_price - entry_price) / entry_price))
                position = 0
                
        elif position == -1:
            if data['high'].iloc[i] >= trade_stop_price or data['low'].iloc[i] <= trade_target_price:
                exit_price = data['close'].iloc[i]
                equity_curve.append(equity_curve[-1] * (1 + (entry_price - exit_price) / entry_price))
                position = 0
                
    return equity_curve

# ========== 运行回测 ==========
print("📈 运行均线交叉策略回测...")
equity_curve = backtest(data)

# ========== 计算绩效指标 ==========
if len(equity_curve) > 1:
    total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0]
    annualized_return = (1 + total_return) ** (1 / ((end_time - start_time).days / 365)) - 1
    max_drawdown = (pd.Series(equity_curve).cummax() - pd.Series(equity_curve)).max() / pd.Series(equity_curve).cummax().max()
    returns = pd.Series(equity_curve).pct_change().dropna()
    sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() != 0 else 0
    win_rate = (returns > 0).sum() / len(returns) if len(returns) > 0 else 0
    
    print("\n📊 回测结果:")
    print(f"   总收益率: {total_return:.2%}")
    print(f"   年化收益率: {annualized_return:.2%}")
    print(f"   最大回撤: {max_drawdown:.2%}")
    print(f"   夏普比率: {sharpe_ratio:.2f}")
    print(f"   胜率: {win_rate:.2%}")
else:
    print("❌ 回测失败，没有交易记录")

# ========== 保存收益曲线图 ==========
plt.figure(figsize=(12, 6))
plt.plot(equity_curve, label='Equity Curve', linewidth=2)
plt.title('SPY 均线交叉策略回测 - 收益曲线', fontsize=14)
plt.xlabel('交易次数', fontsize=12)
plt.ylabel('总资产', fontsize=12)
plt.legend()
plt.grid(True, alpha=0.3)
plt.savefig('equity_curve_SPY.png', dpi=150)
print("\n✅ 收益曲线图已保存为: equity_curve_SPY.png")