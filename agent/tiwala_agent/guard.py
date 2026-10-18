"""Input guard: source tagging and instruction detection for the two untrusted channels.

Channels: direct user chat, and free-text fields read from the contract (PO refs).
Contract text is never handed to a model as an instruction: it is escaped, truncated
and wrapped as quoted data. The flags feed the risk flagger and the audit log; they
never loosen anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

USER_CHAT = "user_chat"
CONTRACT_TEXT = "contract_text"

_PATTERNS = [
    (r"\bignore\b.{0,40}\b(rules?|instructions?|policy|polic(y|ies)|limits?|previous|above)\b", "override_attempt"),
    (r"\b(disregard|bypass|override|skip)\b.{0,40}\b(rules?|checks?|policy|limits?|confirmation|checker)\b", "override_attempt"),
    (r"\b(system prompt|you are now|developer mode|act as|new instructions?)\b", "role_hijack"),
    (r"\b(release|send|pay|transfer|withdraw)\b.{0,30}\b(all|full|entire|everything|whole)\b", "drain_request"),
    (r"0x[0-9a-fA-F]{40}", "raw_address"),
    (r"\b(i am|this is) (the )?(owner|admin|bank|platform|tiwala)\b", "authority_claim"),
    (r"\b(goods|order|delivery)\b.{0,20}\b(arrived|delivered|received)\b", "delivery_claim"),
]
_COMPILED = [(re.compile(p, re.I | re.S), name) for p, name in _PATTERNS]
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")
MAX_CONTRACT_TEXT = 120


@dataclass(frozen=True)
class Tagged:
    text: str
    source: str
    flags: tuple = field(default_factory=tuple)

    @property
    def suspicious(self) -> bool:
        return any(f in {"override_attempt", "role_hijack", "drain_request", "authority_claim"} for f in self.flags)


def scan(text: str) -> tuple:
    return tuple(sorted({name for rx, name in _COMPILED if rx.search(text or "")}))


def tag_user(text: str) -> Tagged:
    clean = _CTRL.sub("", text or "")
    return Tagged(clean, USER_CHAT, scan(clean))


def tag_contract(text: str) -> Tagged:
    clean = _CTRL.sub("", text or "")
    return Tagged(clean, CONTRACT_TEXT, scan(clean))


def as_data(t: Tagged, label: str) -> str:
    """Render contract free text for a prompt: escaped, truncated, quoted, labelled."""
    body = t.text[:MAX_CONTRACT_TEXT].replace("\\", "\\\\").replace('"', '\\"').replace("<", "&lt;").replace(">", "&gt;")
    note = f' flags="{",".join(t.flags)}"' if t.flags else ""
    return f'<untrusted source="{label}"{note}>"{body}"</untrusted>'
