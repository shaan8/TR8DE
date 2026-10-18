"""Append-only, hash-chained audit log (JSONL). Each entry commits to the previous one,
so any edit or deletion breaks `verify()`. Secrets and raw account identifiers are
redacted before writing.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

_REDACT_KEYS = {"private_key", "key", "account_number", "token", "password", "salt"}


def _redact(obj):
    if isinstance(obj, dict):
        return {k: ("[redacted]" if k.lower() in _REDACT_KEYS else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    if isinstance(obj, str):
        return obj  # tx hashes are 32-byte hex and must stay; private keys never reach here by key name
    return obj


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.count = 0  # entries written so far; the last entry's 1-based line number
        self._prev = self._last_hash()

    def _last_hash(self) -> str:
        if not self.path.exists():
            return "0" * 64
        last = None
        with self.path.open() as f:
            for line in f:
                if line.strip():
                    last = line
                    self.count += 1
        return json.loads(last)["hash"] if last else "0" * 64

    def write(self, event: str, **data) -> dict:
        entry = {"ts": int(time.time()), "event": event, "data": _redact(data), "prev": self._prev}
        body = json.dumps(entry, sort_keys=True, default=str)
        entry["hash"] = hashlib.sha256(body.encode()).hexdigest()
        with self.path.open("a") as f:
            f.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
        self._prev = entry["hash"]
        self.count += 1
        return entry

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]

    def verify(self) -> bool:
        prev = "0" * 64
        for e in self.entries():
            h = e.pop("hash")
            if e["prev"] != prev:
                return False
            if hashlib.sha256(json.dumps(e, sort_keys=True, default=str).encode()).hexdigest() != h:
                return False
            prev = h
        return True
