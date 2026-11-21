"""Mock of the Gnani STT and TTS WebSocket services, used by tests and the latency harness."""
from .app import create_app
from .testing import start_mock

__all__ = ["create_app", "start_mock"]
