# -*- coding: utf-8 -*-
"""
获取当前时间 - Python 版
"""

import datetime

def get_current_time():
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")

if __name__ == '__main__':
    print(get_current_time())