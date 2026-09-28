#!/usr/bin/env python3
"""Compare two final-validation JSON reports for exact deterministic equality."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first_positional", nargs="?", type=Path)
    parser.add_argument("second_positional", nargs="?", type=Path)
    parser.add_argument("--first", dest="first_option", type=Path)
    parser.add_argument("--second", dest="second_option", type=Path)
    parser.add_argument("--assert-exact", action="store_true")
    args = parser.parse_args()

    if args.first_option is not None and args.first_positional is not None:
        parser.error("first report must be supplied either positionally or with --first, not both")
    if args.second_option is not None and args.second_positional is not None:
        parser.error("second report must be supplied either positionally or with --second, not both")

    first_path = args.first_option or args.first_positional
    second_path = args.second_option or args.second_positional
    if first_path is None or second_path is None:
        parser.error("two final-validation reports are required")

    first = json.loads(first_path.read_text(encoding="utf-8"))
    second = json.loads(second_path.read_text(encoding="utf-8"))
    same = first == second
    print(json.dumps({"same": same}, sort_keys=True))

    # The task-contract positional form is an exact-comparison gate. Preserve
    # the historical option form, where --assert-exact opts into failure.
    positional_contract = args.first_positional is not None or args.second_positional is not None
    if (args.assert_exact or positional_contract) and not same:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
