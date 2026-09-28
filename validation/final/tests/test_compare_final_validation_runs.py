from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "compare_final_validation_runs.py"


class CompareFinalValidationRunsTests(unittest.TestCase):
    def _write(self, directory: Path, name: str, payload: dict[str, object]) -> Path:
        path = directory / name
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return path

    def test_positional_contract_passes_equal_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = self._write(root, "first.json", {"value": 1})
            second = self._write(root, "second.json", {"value": 1})
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(first), str(second)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('"same": true', result.stdout)

    def test_positional_contract_fails_different_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = self._write(root, "first.json", {"value": 1})
            second = self._write(root, "second.json", {"value": 2})
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(first), str(second)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('"same": false', result.stdout)

    def test_option_form_remains_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = self._write(root, "first.json", {"value": 1})
            second = self._write(root, "second.json", {"value": 2})
            relaxed = subprocess.run(
                [sys.executable, str(SCRIPT), "--first", str(first), "--second", str(second)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            strict = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--first",
                    str(first),
                    "--second",
                    str(second),
                    "--assert-exact",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        self.assertEqual(relaxed.returncode, 0)
        self.assertEqual(strict.returncode, 1)


if __name__ == "__main__":
    unittest.main()
