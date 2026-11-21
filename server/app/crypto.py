"""Field-level AES-256-GCM helpers.

A blob is a 12-byte random nonce followed by the ciphertext and tag. The associated data binds a blob to its row,
written as "<table>:<row id>", so a blob copied to another row fails to decrypt.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger("khata.crypto")

NONCE_LEN = 12


def load_key(env_key: str = "", key_path: Path | None = None) -> bytes:
    """Return the 32-byte key from base64 `env_key`, else from `key_path`, creating that file when absent."""
    if env_key:
        key = base64.b64decode(env_key)
        if len(key) != 32:
            raise ValueError("LEDGER_KEY must be base64 of exactly 32 bytes")
        return key
    if key_path is None:
        raise ValueError("no LEDGER_KEY and no key file path")
    key_path = Path(key_path)
    if key_path.exists():
        key = base64.b64decode(key_path.read_text().strip())
        if len(key) != 32:
            raise ValueError(f"{key_path} does not hold a 32-byte key")
        return key
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = AESGCM.generate_key(bit_length=256)
    key_path.write_text(base64.b64encode(key).decode("ascii"))
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    log.warning("LEDGER_KEY is not set: created a key file at %s", key_path)
    return key


class Crypto:
    def __init__(self, key: bytes):
        self._aes = AESGCM(key)

    def encrypt(self, value: Any, aad: str) -> bytes:
        """Encrypt a JSON-serialisable value (bytes are stored as given)."""
        plain = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
        nonce = os.urandom(NONCE_LEN)
        return nonce + self._aes.encrypt(nonce, plain, aad.encode("utf-8"))

    def decrypt_bytes(self, blob: bytes, aad: str) -> bytes:
        blob = bytes(blob)
        return self._aes.decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], aad.encode("utf-8"))

    def decrypt(self, blob: bytes, aad: str) -> Any:
        return json.loads(self.decrypt_bytes(blob, aad).decode("utf-8"))
