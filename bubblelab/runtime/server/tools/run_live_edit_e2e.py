#!/usr/bin/env python3
"""Exercise authoritative paused bubble edits through the loopback HTTP transport."""
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

from bubblelab.runtime.server import serve_in_thread

ORIGIN = "http://127.0.0.1:4173"


def request_json(base_url: str, method: str, path: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url}{path}",
        method=method,
        data=data,
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def bubble(frame: dict, bubble_id: str) -> dict:
    return next(item for item in frame["bubbles"] if item["id"] == bubble_id)


def run(assertions: bool) -> dict:
    scenario_path = ROOT / "bubblelab" / "scenarios" / "runtime" / "transient-wind.scenario.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    server, thread = serve_in_thread(port=0, allowed_origins=(ORIGIN,))
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    result: dict = {}
    try:
        status, created = request_json(
            base_url,
            "POST",
            "/v1/sessions",
            {"scenario": scenario, "backend": "transient"},
        )
        session_id = created["session_id"]
        initial_time = created["snapshot"]["physical_time_s"]

        pause_status, paused = request_json(
            base_url,
            "POST",
            f"/v1/sessions/{session_id}/commands",
            {"command": "PAUSE"},
        )
        add_status, added = request_json(
            base_url,
            "POST",
            f"/v1/sessions/{session_id}/commands",
            {
                "command": "ADD_BUBBLE",
                "bubble_id": "bubble-2",
                "centroid_m": [0.018, 0.0, 0.0],
                "equivalent_radius_m": 0.004,
                "velocity_m_s": [-0.01, 0.0, 0.0],
                "surface_tension_n_m": 0.05,
            },
        )
        move_status, moved = request_json(
            base_url,
            "POST",
            f"/v1/sessions/{session_id}/commands",
            {
                "command": "MOVE_BUBBLE",
                "bubble_id": "bubble-1",
                "centroid_m": [-0.005, 0.0, 0.0],
            },
        )
        velocity_status, velocity = request_json(
            base_url,
            "POST",
            f"/v1/sessions/{session_id}/commands",
            {
                "command": "SET_BUBBLE_VELOCITY",
                "bubble_id": "bubble-1",
                "velocity_m_s": [0.02, 0.0, 0.0],
            },
        )
        step_status, stepped = request_json(
            base_url,
            "POST",
            f"/v1/sessions/{session_id}/commands",
            {"command": "STEP"},
        )

        result = {
            "session_id": session_id,
            "statuses": [status, pause_status, add_status, move_status, velocity_status, step_status],
            "initial_time_s": initial_time,
            "edit_time_s": velocity["snapshot"]["physical_time_s"],
            "step_time_s": stepped["snapshot"]["physical_time_s"],
            "edit_frame_id": velocity["latest_frame"]["frame_id"],
            "step_frame_id": stepped["latest_frame"]["frame_id"],
            "bubble_ids_after_edit": [item["id"] for item in velocity["latest_frame"]["bubbles"]],
            "bubble_ids_after_step": [item["id"] for item in stepped["latest_frame"]["bubbles"]],
            "command_result": velocity["command_result"],
        }

        if assertions:
            assert result["statuses"] == [201, 200, 200, 200, 200, 200], result
            assert paused["snapshot"]["state"] == "PAUSED", paused
            assert added["snapshot"]["physical_time_s"] == initial_time, added
            assert moved["snapshot"]["physical_time_s"] == initial_time, moved
            assert velocity["snapshot"]["physical_time_s"] == initial_time, velocity
            assert set(result["bubble_ids_after_edit"]) == {"bubble-1", "bubble-2"}, result
            assert bubble(moved["latest_frame"], "bubble-1")["centroid_m"][0] < -0.004999999999
            assert bubble(velocity["latest_frame"], "bubble-1")["velocity_m_s"] == [0.02, 0.0, 0.0]
            assert velocity["command_result"]["command"] == "SET_BUBBLE_VELOCITY", velocity
            assert velocity["command_result"]["physical_time_before_s"] == initial_time, velocity
            assert velocity["command_result"]["physical_time_after_s"] == initial_time, velocity
            assert stepped["snapshot"]["physical_time_s"] > initial_time, stepped
            assert set(result["bubble_ids_after_step"]) == {"bubble-1", "bubble-2"}, result
            assert stepped["command_result"]["command"] == "STEP", stepped
            assert stepped["snapshot"]["state"] == "PAUSED", stepped
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assert", dest="assertions", action="store_true")
    args = parser.parse_args()
    result = run(args.assertions)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
