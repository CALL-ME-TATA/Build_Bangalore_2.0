"""Run the mock Gnani server: python -m mock_gnani --port 9090"""
import argparse

import uvicorn

from .app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="mock_gnani", description="Mock Gnani STT/TTS server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9090)
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
