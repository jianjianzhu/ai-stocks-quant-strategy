import yfinance as yf
import pandas as pd

print("📊 开始下载 SPY 日线数据...")

# 下载 SPY 从 2000-01-01 到 2026-06-19 的日线数据
data = yf.download('SPY', start='2000-01-01', end='2026-06-19', interval='1d')

# 保存为 CSV 文件
data.to_csv('SPY_daily_2000_2026.csv')

print(f"✅ 日线数据下载完成！共 {len(data)} 条记录")
print(f"   时间范围: {data.index.min()} 到 {data.index.max()}")
print(data.head())