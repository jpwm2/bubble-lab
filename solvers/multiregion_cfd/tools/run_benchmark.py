#!/usr/bin/env python3
"""Dispatch deterministic CFD evidence probes, including T1 coupling modes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_STRONG_MODES = {
    "t1-strong-feedback": "feedback",
    "t1-strong-conservation": "conservation",
    "t1-strong-refinement": "refinement",
    "t1-strong-symmetry": "symmetry",
}

_MANYCONTACT_MODES = {
    "manycontact-t1-feedback": "feedback",
    "manycontact-t1-causality": "causality",
    "manycontact-t1-conservation": "conservation",
    "manycontact-t1-refinement": "refinement",
    "manycontact-t1-symmetry": "symmetry",
}


def _run_strong(mode: str, assertions: bool) -> None:
    from bubblelab.solvers.multiregion_cfd import t1_strong_benchmarks

    function = getattr(t1_strong_benchmarks, _STRONG_MODES[mode])
    print(json.dumps(function(assertions), indent=2, sort_keys=True))


def _run_manycontact(mode: str, assertions: bool) -> None:
    from bubblelab.solvers.multiregion_cfd import manycontact_t1_benchmarks

    function = getattr(manycontact_t1_benchmarks, _MANYCONTACT_MODES[mode])
    print(json.dumps(function(assertions), indent=2, sort_keys=True))


def main() -> None:
    requested = sys.argv[1] if len(sys.argv) >= 2 else ""
    if requested in _STRONG_MODES:
        parser = argparse.ArgumentParser()
        parser.add_argument("mode", choices=tuple(_STRONG_MODES))
        parser.add_argument("--assert", dest="assertions", action="store_true")
        args = parser.parse_args()
        _run_strong(args.mode, args.assertions)
        return
    if requested in _MANYCONTACT_MODES:
        parser = argparse.ArgumentParser()
        parser.add_argument("mode", choices=tuple(_MANYCONTACT_MODES))
        parser.add_argument("--assert", dest="assertions", action="store_true")
        args = parser.parse_args()
        _run_manycontact(args.mode, args.assertions)
        return

    from run_benchmark_legacy import main as legacy_main

    legacy_main()


if __name__ == "__main__":
    main()
