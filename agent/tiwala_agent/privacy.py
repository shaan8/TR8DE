"""Data minimisation for model calls: what the LLM provider never needs to see.

Phone numbers, e-mail addresses and account-number-like digit runs are masked one way. Wallet addresses are
swapped for placeholders (ADDR_1, ...) that code maps back in the model's text and tool arguments, so the model
can still refer to a payee while the provider never receives the address. Transaction hashes stay: they are public
and the reply grounding check needs them. Payee provenance is checked by code against the owner's unredacted words.
"""
from __future__ import annotations

import copy
import re
from typing import Optional

from .llm import LLM, LLMResponse, ToolCall

ADDR = re.compile(r"0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")
MASKS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"(?<![\w.])\+\d[\d\s-]{8,16}\d\b"), "[phone]"),
    (re.compile(r"\b09\d{2}[\s-]?\d{3}[\s-]?\d{4}\b"), "[phone]"),  # Philippine mobile
    (re.compile(r"\b\d{4}([ -])\d{4}\1\d{4}(?:\1\d{1,7})?\b"), "[account]"),
    (re.compile(r"(?<![\d.x])\d{12,19}(?![\d.])"), "[account]"),
]

HEX = re.compile(r"(0x[0-9a-fA-F]+)")


def mask_pii(s: str) -> str:
    """Mask phones, e-mails and account numbers, leaving 0x-hex (addresses, tx hashes) whole: a digit run inside
    a hash is not an account number."""
    parts = HEX.split(s)
    for i in range(0, len(parts), 2):
        for rx, rep in MASKS:
            parts[i] = rx.sub(rep, parts[i])
    return "".join(parts)


class Redactor:
    def __init__(self):
        self.to_ph: dict[str, str] = {}
        self.from_ph: dict[str, str] = {}

    def text(self, s: str) -> str:
        def addr(m):
            a = m.group(0)
            key = a.lower()
            if key not in self.to_ph:
                ph = f"ADDR_{len(self.to_ph) + 1}"
                self.to_ph[key], self.from_ph[ph] = ph, a
            return self.to_ph[key]
        return mask_pii(ADDR.sub(addr, s))

    def deep(self, obj):
        if isinstance(obj, str):
            return self.text(obj)
        if isinstance(obj, list):
            return [self.deep(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.deep(v) for k, v in obj.items()}
        return obj

    def restore(self, obj):
        if isinstance(obj, str):
            return re.sub(r"ADDR_\d+", lambda m: self.from_ph.get(m.group(0), m.group(0)), obj)
        if isinstance(obj, list):
            return [self.restore(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.restore(v) for k, v in obj.items()}
        return obj


class RedactingLLM(LLM):
    """Wraps any LLM: messages go out minimised, the response comes back with placeholders restored."""

    def __init__(self, inner: LLM, redactor: Optional[Redactor] = None):
        self.inner, self.r = inner, redactor or Redactor()

    def complete(self, system: str, messages: list[dict], tools: Optional[list[dict]] = None) -> LLMResponse:
        out = self.inner.complete(system, self.r.deep(copy.deepcopy(messages)), tools)
        return LLMResponse(self.r.restore(out.text or ""),
                           [ToolCall(c.id, c.name, self.r.restore(c.args)) for c in out.tool_calls], out.raw)
