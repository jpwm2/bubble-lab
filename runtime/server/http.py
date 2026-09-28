"""Loopback-only stdlib HTTP/JSON adapter for LiveSessionService."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

from .service import LiveSessionService, LiveSessionTransportError, TRANSPORT_VERSION

MAX_JSON_BYTES = 4 * 1024 * 1024
LOOPBACK_HOST = "127.0.0.1"


def normalize_trusted_origin(value: str) -> str:
    origin = value.strip()
    parsed = urlsplit(origin)
    if (
        origin in {"*", "null"}
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError(
            "trusted origins must be explicit http(s) origins without paths, "
            "credentials, query, or fragments"
        )
    return f"{parsed.scheme}://{parsed.netloc}"


class LiveSessionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        service: LiveSessionService | None = None,
        *,
        allowed_origins: Iterable[str] = (),
    ) -> None:
        self.service = service or LiveSessionService()
        self.allowed_origins = frozenset(
            normalize_trusted_origin(origin) for origin in allowed_origins
        )
        super().__init__(server_address, LiveSessionRequestHandler)


class LiveSessionRequestHandler(BaseHTTPRequestHandler):
    server: LiveSessionHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _request_origin(self) -> str | None:
        return self.headers.get("Origin")

    def _origin_is_trusted(self) -> bool:
        origin = self._request_origin()
        return origin is not None and origin in self.server.allowed_origins

    def _require_trusted_origin(self) -> None:
        if not self._origin_is_trusted():
            raise LiveSessionTransportError(
                "origin_not_allowed",
                "request Origin is not in the explicit trusted-origin set",
                status=403,
            )

    def _cors_headers(self) -> None:
        origin = self._request_origin()
        if origin is not None and origin in self.server.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def _send_json(self, status: int, payload: Any) -> None:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(encoded)

    def _send_error_payload(self, exc: LiveSessionTransportError) -> None:
        payload: dict[str, Any] = {
            "error": {"code": exc.code, "message": str(exc)},
            "transport_version": TRANSPORT_VERSION,
        }
        if exc.session_payload is not None:
            payload["session"] = exc.session_payload
        self._send_json(exc.status, payload)

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise LiveSessionTransportError(
                "invalid_content_length", "Content-Length must be an integer"
            ) from exc
        if length < 0 or length > MAX_JSON_BYTES:
            raise LiveSessionTransportError(
                "request_too_large",
                f"JSON body must not exceed {MAX_JSON_BYTES} bytes",
                status=413,
            )
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LiveSessionTransportError(
                "invalid_json", "request body must be valid UTF-8 JSON"
            ) from exc
        if not isinstance(value, dict):
            raise LiveSessionTransportError(
                "invalid_json_shape", "request JSON must be an object"
            )
        return value

    @staticmethod
    def _segments(path: str) -> list[str]:
        return [unquote(part) for part in path.split("/") if part]

    def do_OPTIONS(self) -> None:
        try:
            self._require_trusted_origin()
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self._cors_headers()
            self.end_headers()
        except LiveSessionTransportError as exc:
            self._send_error_payload(exc)

    def do_GET(self) -> None:
        try:
            path = urlsplit(self.path).path
            parts = self._segments(path)
            if parts == ["v1", "health"]:
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "transport_version": TRANSPORT_VERSION,
                        "bind_scope": "loopback-only",
                    },
                )
                return
            if parts[:2] == ["v1", "sessions"]:
                self._require_trusted_origin()
            if len(parts) == 3 and parts[:2] == ["v1", "sessions"]:
                self._send_json(200, self.server.service.get_session(parts[2]))
                return
            if (
                len(parts) == 5
                and parts[:2] == ["v1", "sessions"]
                and parts[3] == "checkpoints"
            ):
                self._send_json(
                    200,
                    self.server.service.get_checkpoint(parts[2], parts[4]),
                )
                return
            raise LiveSessionTransportError(
                "route_not_found", f"unknown route: {path}", status=404
            )
        except LiveSessionTransportError as exc:
            self._send_error_payload(exc)

    def do_POST(self) -> None:
        try:
            path = urlsplit(self.path).path
            parts = self._segments(path)
            if parts[:2] == ["v1", "sessions"]:
                self._require_trusted_origin()
            body = self._read_json()
            if parts == ["v1", "sessions"]:
                scenario = body.get("scenario")
                backend = body.get("backend")
                if backend is not None and not isinstance(backend, str):
                    raise LiveSessionTransportError(
                        "invalid_backend", "backend must be a string when supplied"
                    )
                self._send_json(
                    201,
                    self.server.service.create_session(scenario, backend),
                )
                return
            if (
                len(parts) == 4
                and parts[:2] == ["v1", "sessions"]
                and parts[3] == "commands"
            ):
                command: Any = body.get("command")
                if isinstance(command, dict):
                    command_payload = command
                elif isinstance(command, str):
                    command_payload = dict(body)
                else:
                    command_payload = body
                self._send_json(
                    200,
                    self.server.service.execute_command(parts[2], command_payload),
                )
                return
            if (
                len(parts) == 4
                and parts[:2] == ["v1", "sessions"]
                and parts[3] == "checkpoints"
            ):
                if body:
                    raise LiveSessionTransportError(
                        "checkpoint_request_must_be_empty",
                        "checkpoint save accepts no browser-supplied path or storage options",
                    )
                self._send_json(200, self.server.service.save_checkpoint(parts[2]))
                return
            raise LiveSessionTransportError(
                "route_not_found", f"unknown route: {path}", status=404
            )
        except LiveSessionTransportError as exc:
            self._send_error_payload(exc)

    def do_DELETE(self) -> None:
        try:
            path = urlsplit(self.path).path
            parts = self._segments(path)
            if parts[:2] == ["v1", "sessions"]:
                self._require_trusted_origin()
            if len(parts) == 3 and parts[:2] == ["v1", "sessions"]:
                self._send_json(200, self.server.service.close_session(parts[2]))
                return
            raise LiveSessionTransportError(
                "route_not_found", f"unknown route: {path}", status=404
            )
        except LiveSessionTransportError as exc:
            self._send_error_payload(exc)


def create_http_server(
    host: str = LOOPBACK_HOST,
    port: int = 8765,
    *,
    service: LiveSessionService | None = None,
    allowed_origins: Iterable[str] = (),
) -> LiveSessionHTTPServer:
    if host != LOOPBACK_HOST:
        raise ValueError("live session transport may bind only to 127.0.0.1")
    if not isinstance(port, int) or port < 0 or port > 65535:
        raise ValueError("port must be an integer from 0 through 65535")
    return LiveSessionHTTPServer(
        (host, port),
        service=service,
        allowed_origins=allowed_origins,
    )


def serve_in_thread(
    host: str = LOOPBACK_HOST,
    port: int = 0,
    *,
    service: LiveSessionService | None = None,
    allowed_origins: Iterable[str] = (),
) -> tuple[LiveSessionHTTPServer, Thread]:
    server = create_http_server(
        host,
        port,
        service=service,
        allowed_origins=allowed_origins,
    )
    thread = Thread(
        target=server.serve_forever,
        name="bubblelab-live-session-http",
        daemon=True,
    )
    thread.start()
    return server, thread
