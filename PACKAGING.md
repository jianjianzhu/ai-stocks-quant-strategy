# AI Stocks Quant Strategy — Python 资源包

Python 3.10+，无第三方运行依赖。0.1.0 提供策略目录、SMC Pine 源码、使用文档和许可的离线查看及导出。

## 安装

从仓库根目录安装：

```bash
python -m pip install .
```

或安装下载的 wheel：

```bash
python -m pip install ai_stocks_quant_strategy-0.1.0-py3-none-any.whl
```

尚未发布到 PyPI；不要假定同名 PyPI 项目属于此仓库。

## 使用

```bash
ai-stocks list
ai-stocks show smc
ai-stocks show smc --license
ai-stocks export smc --output ./smc-export
```

也可使用 `python -m ai_stocks_quant` 代替 `ai-stocks`。导出目录必须不存在，以避免覆盖已有文件。

导出后按 README 将 Pine 源码粘贴到 TradingView Pine Editor。SMC V6 是策略版本号，脚本语言为 Pine v5。Python 包不会执行 Pine、连接交易账户或下单；现有仓库根目录 Python 回测和实盘脚本尚未迁入此包，仍按原方式独立运行。

## 许可范围

Python 包装代码采用根目录 MIT 许可。附带的 SMC 衍生代码及文档采用 CC BY-NC-SA 4.0，保留 LuxAlgo 署名、来源、修改记录及独立许可。发行包元数据以 `MIT AND CC-BY-NC-SA-4.0` 标识包含两种许可，不表示两者可任选。不得将附带的 SMC 衍生内容重新标为 MIT。

## 开发与构建

`strategies/smc/` 为 SMC 唯一编辑源，资源副本由同步脚本生成。变更后运行：

```bash
python tools/sync_resources.py
python -m pip install build
python -m build
python -m pip install --force-reinstall dist/ai_stocks_quant_strategy-0.1.0-py3-none-any.whl
python -m unittest discover -s tests -v
```

测试检查资源一致性、许可随包分发、导出内容完整及拒绝覆盖。它不替代 TradingView 编译、回放和回测验证。收益表现与已知策略限制见 SMC 文档。
