"""Copy the canonical licensed SMC directory into distribution resources."""

from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
source = root / "strategies/smc"
destination = root / "src/ai_stocks_quant/resources/smc"
destination.mkdir(parents=True, exist_ok=True)
for name in ("SMC_V6_strategy.pine", "README.md", "LICENSE.md", "CHANGELOG.md"):
    shutil.copyfile(source / name, destination / name)
