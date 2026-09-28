#!/usr/bin/env python3
"""End-to-end qualification of loopback transport against direct RuntimeSession semantics."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.runtime.server.http import serve_in_thread
from bubblelab.runtime.server.service import LiveSessionService
from bubblelab.runtime.session_control import RuntimeSession

SCENARIO_PATH = ROOT / "bubblelab" / "scenarios" / "runtime" / "transient-wind.scenario.json"
TRUSTED_ORIGIN = "http://127.0.0.1:4173"


def request(
    base: str,
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    origin: str = TRUSTED_ORIGIN,
) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Origin": origin,
        },
    )
    try:
        response = urlopen(req, timeout=30)
        raw = response.read()
        return response.status, json.loads(raw.decode("utf-8")) if raw else {}
    except HTTPError as error:
        raw = error.read()
        return error.code, json.loads(raw.decode("utf-8")) if raw else {}


def json_wire(value):
    """Normalize Python-only tuple/list distinctions through the actual JSON wire contract."""
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))


def assert_matches_direct(envelope: dict, direct: RuntimeSession) -> None:
    expected_snapshot = LiveSessionService.snapshot(direct)
    if envelope["snapshot"] != expected_snapshot:
        raise AssertionError("transport snapshot diverged from direct RuntimeSession")
    if envelope["latest_frame"] != direct.frames[-1]:
        raise AssertionError("transport latest FRAME diverged from direct RuntimeSession")
    if envelope["command_history"] != direct.command_history:
        raise AssertionError("transport command history diverged from direct RuntimeSession")
    if envelope["snapshot"]["physical_time_s"] != envelope["latest_frame"]["simulation_time_s"]:
        raise AssertionError("authoritative snapshot time and latest FRAME time disagree")


def run(assert_mode: bool) -> dict:
    scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    direct = RuntimeSession(scenario, "transient")
    server, thread = serve_in_thread(
        port=0,
        allowed_origins={TRUSTED_ORIGIN},
    )
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    summary: dict = {"base": base, "trusted_origin": TRUSTED_ORIGIN, "steps": []}
    try:
        status, remote = request(
            base, "POST", "/v1/sessions", {"scenario": scenario, "backend": "transient"}
        )
        if status != 201:
            raise AssertionError(f"session create returned HTTP {status}: {remote}")
        session_id = remote["session_id"]
        if not session_id.startswith("live-") or len(session_id) != 37:
            raise AssertionError("session identifier is not an opaque 192-bit URL-safe capability")
        assert_matches_direct(remote, direct)
        summary["steps"].append({"operation": "CREATE", "time_s": remote["snapshot"]["physical_time_s"]})

        commands = [
            {"command": "PAUSE"},
            {"command": "STEP"},
            {"command": "RESUME"},
            {"command": "RUN_TO_TIME", "target_time_s": 0.001},
        ]
        for command in commands:
            expected = direct.execute(command)
            status, remote = request(
                base,
                "POST",
                f"/v1/sessions/{session_id}/commands",
                command,
            )
            if status != 200:
                raise AssertionError(f"{command['command']} returned HTTP {status}: {remote}")
            if remote.get("command_result") != expected:
                raise AssertionError(f"{command['command']} command result diverged")
            assert_matches_direct(remote, direct)
            summary["steps"].append(
                {
                    "operation": command["command"],
                    "time_s": remote["snapshot"]["physical_time_s"],
                    "frame_index": remote["snapshot"]["frame_index"],
                }
            )

        expected_checkpoint_result = direct.save_checkpoint()
        status, remote = request(
            base, "POST", f"/v1/sessions/{session_id}/checkpoints", {}
        )
        if status != 200:
            raise AssertionError(f"SAVE_CHECKPOINT returned HTTP {status}: {remote}")
        if remote.get("command_result") != expected_checkpoint_result:
            raise AssertionError("checkpoint command result diverged")
        if remote.get("checkpoint") != json_wire(direct.checkpoints[-1]):
            raise AssertionError("canonical checkpoint JSON document diverged")
        expected_provenance = RuntimeSession._checkpoint_provenance(direct.checkpoints[-1])
        if remote.get("checkpoint_provenance") != json_wire(expected_provenance):
            raise AssertionError("checkpoint provenance diverged")
        assert_matches_direct(remote, direct)
        summary["steps"].append(
            {
                "operation": "SAVE_CHECKPOINT",
                "checkpoint": remote["checkpoint"]["frame_id"],
                "time_s": remote["snapshot"]["physical_time_s"],
            }
        )

        expected_reset = direct.reset()
        status, remote = request(
            base,
            "POST",
            f"/v1/sessions/{session_id}/commands",
            {"command": "RESET"},
        )
        if status != 200 or remote.get("command_result") != expected_reset:
            raise AssertionError(f"RESET diverged: HTTP {status}: {remote}")
        assert_matches_direct(remote, direct)
        summary["steps"].append(
            {
                "operation": "RESET",
                "time_s": remote["snapshot"]["physical_time_s"],
                "frame_index": remote["snapshot"]["frame_index"],
            }
        )

        status, closed = request(base, "DELETE", f"/v1/sessions/{session_id}")
        if status != 200 or closed.get("closed") is not True:
            raise AssertionError(f"close failed: HTTP {status}: {closed}")
        status, missing = request(base, "GET", f"/v1/sessions/{session_id}")
        if status != 404 or missing.get("error", {}).get("code") != "session_not_found":
            raise AssertionError("closed session remained addressable")
        summary["steps"].append({"operation": "CLOSE"})
        summary["ok"] = True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    if assert_mode and not summary.get("ok"):
        raise AssertionError("transport qualification did not complete")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assert", dest="assert_mode", action="store_true")
    args = parser.parse_args()
    summary = run(args.assert_mode)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
