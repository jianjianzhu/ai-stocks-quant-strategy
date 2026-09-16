"""Offline strategy catalogue and export commands (MIT)."""

import argparse
from importlib.resources import files
from pathlib import Path

from . import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline Pine strategy resources")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List bundled strategies")
    show = commands.add_parser("show", help="Read bundled documentation")
    show.add_argument("strategy", choices=["smc"])
    show.add_argument("--license", action="store_true", help="Read license notice")
    export = commands.add_parser("export", help="Export Pine source and documentation")
    export.add_argument("strategy", choices=["smc"])
    export.add_argument("--output", type=Path, required=True, help="New destination directory")
    args = parser.parse_args(argv)
    if args.command == "list":
        print("smc | SMC V6 | Pine Script v5 / TradingView | CC-BY-NC-SA-4.0")
        return 0
    resource = files("ai_stocks_quant").joinpath("resources", "smc")
    if args.command == "show":
        name = "LICENSE.md" if args.license else "README.md"
        print(resource.joinpath(name).read_text(encoding="utf-8"))
        return 0
    # Require a new directory so existing scripts or user edits are never overwritten.
    try:
        args.output.mkdir(parents=True, exist_ok=False)
        for item in resource.iterdir():
            if item.is_file():
                with (args.output / item.name).open("xb") as stream:
                    stream.write(item.read_bytes())
    except OSError as exc:
        parser.exit(1, f"Export failed: {exc}\n")
    print(f"Exported SMC source, license and documentation to {args.output}")
    print("Run the .pine script in TradingView; this package does not execute Pine.")
    return 0
