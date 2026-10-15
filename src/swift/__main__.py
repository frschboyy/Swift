"""Command-line entry point: ``python -m swift``."""

from __future__ import annotations

import argparse
import sys

from swift import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="swift", description="Swift desktop agent")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    args = parser.parse_args(argv)

    if args.version:
        print(f"Swift {__version__}")
        return 0

    # The agent runtime arrives in Phase 1.
    parser.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
