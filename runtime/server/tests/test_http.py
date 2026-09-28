from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bubblelab.runtime.server.http import create_http_server, normalize_trusted_origin, serve_in_thread

ROOT = Path(__file__).resolve().parents[4]
SCENARIO = ROOT / "bubblelab" / "scenarios" / "runtime" / "transient-wind.scenario.json"
TRUSTED_ORIGIN = "http://127.0.0.1:4173"
HOSTILE_ORIGIN = "https://hostile.example"


def load_scenario() -> dict:
    return json.loads(SCENARIO.read_text(encoding="utf-8"))


class LiveSessionHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server, cls.thread = serve_in_thread(
            port=0,
            allowed_origins={TRUSTED_ORIGIN},
        )
        host, port = cls.server.server_address[:2]
        cls.base = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        origin: str | None = TRUSTED_ORIGIN,
    ):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if origin is not None:
            headers["Origin"] = origin
        request = Request(
            self.base + path,
            data=data,
            method=method,
            headers=headers,
        )
        try:
            response = urlopen(request, timeout=10)
            raw = response.read()
            return (
                response.status,
                dict(response.headers),
                json.loads(raw.decode("utf-8")) if raw else {},
            )
        except HTTPError as error:
            raw = error.read()
            return (
                error.code,
                dict(error.headers),
                json.loads(raw.decode("utf-8")) if raw else {},
            )

    def test_health_cors_and_server_configuration_are_explicit(self):
        status, headers, body = self.request(
            "GET",
            "/v1/health",
            origin=TRUSTED_ORIGIN,
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["bind_scope"], "loopback-only")
        self.assertEqual(headers["Access-Control-Allow-Origin"], TRUSTED_ORIGIN)
        self.assertNotEqual(headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(headers["Vary"], "Origin")

        status, headers, body = self.request(
            "GET",
            "/v1/health",
            origin=HOSTILE_ORIGIN,
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)

        with self.assertRaises(ValueError):
            create_http_server("0.0.0.0", 0, allowed_origins={TRUSTED_ORIGIN})
        for invalid in ("*", "null", "file:///", "http://127.0.0.1:4173/path"):
            with self.assertRaises(ValueError):
                normalize_trusted_origin(invalid)

    def test_untrusted_origin_cannot_create_read_control_checkpoint_or_close(self):
        status, headers, denied = self.request(
            "POST",
            "/v1/sessions",
            {"scenario": load_scenario(), "backend": "transient"},
            origin=HOSTILE_ORIGIN,
        )
        self.assertEqual(status, 403)
        self.assertEqual(denied["error"]["code"], "origin_not_allowed")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

        status, _, created = self.request(
            "POST",
            "/v1/sessions",
            {"scenario": load_scenario(), "backend": "transient"},
        )
        self.assertEqual(status, 201)
        session_id = created["session_id"]

        hostile_requests = [
            ("GET", f"/v1/sessions/{session_id}", None),
            ("POST", f"/v1/sessions/{session_id}/commands", {"command": "PAUSE"}),
            ("POST", f"/v1/sessions/{session_id}/checkpoints", {}),
            ("GET", f"/v1/sessions/{session_id}/checkpoints/latest", None),
            ("DELETE", f"/v1/sessions/{session_id}", None),
        ]
        for method, path, payload in hostile_requests:
            with self.subTest(method=method, path=path):
                status, headers, denied = self.request(
                    method,
                    path,
                    payload,
                    origin=HOSTILE_ORIGIN,
                )
                self.assertEqual(status, 403)
                self.assertEqual(denied["error"]["code"], "origin_not_allowed")
                self.assertNotIn("Access-Control-Allow-Origin", headers)

        status, _, still_there = self.request("GET", f"/v1/sessions/{session_id}")
        self.assertEqual(status, 200)
        self.assertEqual(still_there["snapshot"]["state"], "CREATED")
        status, _, closed = self.request("DELETE", f"/v1/sessions/{session_id}")
        self.assertEqual(status, 200)
        self.assertTrue(closed["closed"])

    def test_preflight_allows_only_trusted_origin(self):
        status, headers, _ = self.request(
            "OPTIONS",
            "/v1/sessions",
            origin=TRUSTED_ORIGIN,
        )
        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Origin"], TRUSTED_ORIGIN)

        status, headers, denied = self.request(
            "OPTIONS",
            "/v1/sessions",
            origin=HOSTILE_ORIGIN,
        )
        self.assertEqual(status, 403)
        self.assertEqual(denied["error"]["code"], "origin_not_allowed")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_http_session_lifecycle_and_structured_rejection(self):
        status, _, created = self.request(
            "POST", "/v1/sessions", {"scenario": load_scenario(), "backend": "transient"}
        )
        self.assertEqual(status, 201)
        session_id = created["session_id"]
        self.assertRegex(session_id, r"^live-[A-Za-z0-9_-]{32}$")
        self.assertEqual(created["snapshot"]["state"], "CREATED")

        status, _, rejected = self.request(
            "POST",
            f"/v1/sessions/{session_id}/commands",
            {"command": "STEP"},
        )
        self.assertEqual(status, 409)
        self.assertEqual(rejected["error"]["code"], "invalid_command")
        self.assertEqual(rejected["session"]["command_result"]["result"], "REJECTED")
        self.assertEqual(rejected["session"]["snapshot"]["state"], "CREATED")

        status, _, paused = self.request(
            "POST",
            f"/v1/sessions/{session_id}/commands",
            {"command": "PAUSE"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(paused["snapshot"]["state"], "PAUSED")

        status, _, stepped = self.request(
            "POST",
            f"/v1/sessions/{session_id}/commands",
            {"command": "STEP"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(stepped["snapshot"]["frame_index"], 1)
        self.assertGreater(stepped["latest_frame"]["simulation_time_s"], 0.0)

        status, _, checkpointed = self.request(
            "POST", f"/v1/sessions/{session_id}/checkpoints", {}
        )
        self.assertEqual(status, 200)
        checkpoint_id = checkpointed["checkpoint"]["frame_id"]
        status, _, fetched_checkpoint = self.request(
            "GET", f"/v1/sessions/{session_id}/checkpoints/{checkpoint_id}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(fetched_checkpoint["checkpoint"], checkpointed["checkpoint"])

        status, _, forbidden = self.request(
            "POST",
            f"/v1/sessions/{session_id}/commands",
            {"command": "SAVE_CHECKPOINT", "path": "../../escape.json"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(forbidden["error"]["code"], "filesystem_path_forbidden")

        status, _, closed = self.request("DELETE", f"/v1/sessions/{session_id}")
        self.assertEqual(status, 200)
        self.assertTrue(closed["closed"])
        status, _, missing = self.request("GET", f"/v1/sessions/{session_id}")
        self.assertEqual(status, 404)
        self.assertEqual(missing["error"]["code"], "session_not_found")


if __name__ == "__main__":
    unittest.main()
