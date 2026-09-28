"""Run the Bubble Lab authoritative live-session transport on loopback."""
from __future__ import annotations

import argparse

from .http import LOOPBACK_HOST, create_http_server


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Serve authoritative Bubble Lab RuntimeSession controls over loopback HTTP/JSON."
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--allow-origin",
        action="append",
        required=True,
        help=(
            "Explicit trusted browser origin, for example http://127.0.0.1:4173. "
            "Repeat to allow more than one origin. Wildcards and Origin null are rejected."
        ),
    )
    args = parser.parse_args()
    server = create_http_server(
        LOOPBACK_HOST,
        args.port,
        allowed_origins=args.allow_origin,
    )
    host, port = server.server_address[:2]
    print(f"Bubble Lab live session transport listening on http://{host}:{port}")
    print("Trusted browser origins:")
    for origin in sorted(server.allowed_origins):
        print(f"  {origin}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
