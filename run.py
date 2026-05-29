"""Start the YGO Collection & Deck Builder web app."""

import argparse
import socket
import subprocess
import sys
import webbrowser

import uvicorn

from ygo_app.config import DB_PATH


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _listening_pid(port: int) -> int | None:
    try:
        out = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    needle = f":{port}"
    for line in out.stdout.splitlines():
        if needle not in line or "LISTENING" not in line:
            continue
        parts = line.split()
        if parts:
            try:
                return int(parts[-1])
            except ValueError:
                continue
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print("Database not found. Run first:")
        print("  python -m ygo_app.import_data")
        print()

    port_busy = _port_in_use(args.host, args.port)
    owner_pid = _listening_pid(args.port) if port_busy else None

    if port_busy:
        pid_hint = f" (PID {owner_pid})" if owner_pid else ""
        print(
            f"Port {args.port} on {args.host} is already in use{pid_hint}.\n"
            "Another server is probably still running (e.g. an earlier `python run.py`).\n"
            "Stop it with Ctrl+C in that terminal, or start on a different port:\n"
            f"  python run.py --port {args.port + 1} --no-browser",
            file=sys.stderr,
        )
        sys.exit(1)

    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        webbrowser.open(url)

    uvicorn.run(
        "ygo_app.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
