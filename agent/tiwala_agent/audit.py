"""Append-only, hash-chained audit log (JSONL). Each entry commits to the previous one,
so editing or removing any entry but the last breaks `verify()`. Deleting the tail (or the
whole file) is caught only against an external checkpoint: `/anchor` writes the entry count
and head hash to Sepolia (see `anchor_payload`), and `scripts/verify_audit.py` checks the log
against those anchors. Secrets and raw account identifiers are redacted before writing.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import threading
import time
from pathlib import Path

from .privacy import mask_pii

ANCHOR_PREFIX = b"TIWALA-AUDIT-v1"


def anchor_payload(count: int, head: str) -> bytes:
    """Calldata of an anchor transaction: prefix, entry count (8 bytes, big-endian), head hash (32 bytes)."""
    return ANCHOR_PREFIX + count.to_bytes(8, "big") + bytes.fromhex(head)


def parse_anchor(data: bytes):
    """(count, head) from anchor calldata, or None if it is not an anchor."""
    if not data.startswith(ANCHOR_PREFIX) or len(data) != len(ANCHOR_PREFIX) + 40:
        return None
    rest = data[len(ANCHOR_PREFIX):]
    return int.from_bytes(rest[:8], "big"), rest[8:].hex()


def check_anchor(entries: list[dict], count: int, head: str) -> str:
    """'' if the log still holds entry `count` with hash `head`, else what is wrong."""
    if len(entries) < count:
        return f"log has {len(entries)} entries but an anchor recorded {count}: entries were deleted"
    if entries[count - 1].get("hash") != head:
        return f"entry {count} does not match its anchor: the log was rewritten"
    return ""


_REDACT_KEYS = {"private_key", "key", "account_number", "token", "password", "salt"}


def _redact(obj):
    if isinstance(obj, dict):
        return {k: ("[redacted]" if k.lower() in _REDACT_KEYS else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    if isinstance(obj, str):  # tx hashes are 32-byte hex and must stay; private keys never reach here by key name
        return mask_pii(obj)  # phones, e-mails and account numbers in free text are not kept at rest
    return obj


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()  # one append at a time, or two writers chain off the same prev
        self._size = -1  # file size after our last read or write; another process appending changes it
        self.count = 0  # entries written so far; the last entry's 1-based line number
        self._prev = "0" * 64
        self._sync()

    def _sync(self) -> None:
        """Re-read count and head hash if the file changed since we last touched it."""
        size = self.path.stat().st_size if self.path.exists() else 0
        if size == self._size:
            return
        self.count, last = 0, None
        if self.path.exists():
            with self.path.open() as f:
                for line in f:
                    if line.strip():
                        last = line
                        self.count += 1
        self._prev = json.loads(last)["hash"] if last else "0" * 64
        self._size = size

    def write(self, event: str, **data) -> dict:
        with self._lock, self.path.open("a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)  # other processes (bot, console, CLI) may share this file
            try:
                self._sync()
                entry = {"ts": int(time.time()), "event": event, "data": _redact(data), "prev": self._prev}
                body = json.dumps(entry, sort_keys=True, default=str)
                entry["hash"] = hashlib.sha256(body.encode()).hexdigest()
                f.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
                f.flush()
                self._prev = entry["hash"]
                self.count += 1
                self._size = self.path.stat().st_size
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
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
