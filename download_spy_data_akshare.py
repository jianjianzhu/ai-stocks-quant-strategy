import akshare as ak
import pandas as pd

df = ak.stock_us_hist(symbol="SPY", period="daily", start_date="20000101", end_date="20260619", adjust="")
df.to_csv('SPY_2000_2026_akshare.csv', index=False)
print(f"✅ 下载完成！共 {len(df)} 条数据")
print(df.head())