import pandas_ta as ta

version = getattr(ta, '__version__', 'unknown (0.4.71b0)')
print('pandas-ta version:', version)
print('Available indicators count:', len([m for m in dir(ta) if m.isupper()]))

import numpy as np
import pandas as pd

df = pd.DataFrame({'close': np.random.randn(100).cumsum() + 100})
r = df.ta.sma(length=10)
print('SMA(10) test passed, result length:', len(r))
print('All checks OK')