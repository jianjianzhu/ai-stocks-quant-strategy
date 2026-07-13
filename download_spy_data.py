import yfinance as yf, pandas as pd, time

all_dfs = []
cache = 'data_SPY_1d.csv'

for y in range(2000, 2027):
    s = f'{y}-01-01'
    e = f'{y}-12-31' if y < 2026 else '2026-06-19'
    try:
        df = yf.Ticker('SPY').history(start=s, end=e, interval='1d', timeout=30)
        if len(df) > 0:
            all_dfs.append(df)
            print(f'{y}: {len(df)} bars OK')
        time.sleep(2)
    except Exception as ex:
        print(f'{y}: FAIL - {ex}')

if all_dfs:
    full = pd.concat(all_dfs)
    full = full[~full.index.duplicated()]
    full.sort_index(inplace=True)
    full.to_csv(cache)
    print(f'DONE: {len(full)} total bars saved to {cache}')
else:
    print('FAIL: No data downloaded')