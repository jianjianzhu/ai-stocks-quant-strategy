import pandas as pd
import pandas_ta as ta

def load_data(file_path):
    return pd.read_csv(file_path)

def ma_cross_strategy(data, short_window, long_window):
    data['short_mavg'] = data['close'].rolling(window=short_window, min_periods=1, center=False).mean()
    data['long_mavg'] = data['close'].rolling(window=long_window, min_periods=1, center=False).mean()
    
    data['signal'] = 0.0
    data['signal'][short_window:] = np.where(data['short_mavg'][short_window:] > data['long_mavg'][short_window:], 1.0, 0.0)
    data['positions'] = data['signal'].diff()
    
    return data

def backtest_strategy(data, initial_capital=100000.0):
    data['holdings'] = data['positions'] * data['close']
    data['cash'] = initial_capital - (data['positions'] * data['close']).cumsum()
    data['total'] = data['cash'] + (data['holdings'] * data['close'])
    
    return data

def calculate_metrics(data):
    total_return = (data['total'].iloc[-1] / data['total'].iloc[0]) - 1
    annualized_return = (1 + total_return) ** (252 / len(data)) - 1
    max_drawdown = (data['total'].cummax() - data['total']).max() / data['total'].cummax().max()
    sharpe_ratio = (data['total'].pct_change().mean() / data['total'].pct_change().std()) * np.sqrt(252)
    win_rate = (data['positions'] * data['close'].diff() > 0).mean()
    
    return {
        '总收益率': total_return,
        '年化收益率': annualized_return,
        '最大回撤': max_drawdown,
        '夏普比率': sharpe_ratio,
        '胜率': win_rate
    }

def plot_equity_curve(data, file_name):
    import matplotlib.pyplot as plt
    plt.figure(figsize=(10, 6))
    plt.plot(data['date'], data['total'], label='Equity Curve')
    plt.title('Equity Curve')
    plt.xlabel('Date')
    plt.ylabel('Total Value')
    plt.legend()
    plt.savefig(file_name)
    plt.close()

if __name__ == "__main__":
    data = load_data('SPY_simulated.csv')
    data = ma_cross_strategy(data, short_window=50, long_window=200)
    data = backtest_strategy(data)
    metrics = calculate_metrics(data)
    print(metrics)
    plot_equity_curve(data, 'equity_curve_SPY_simulated.png')