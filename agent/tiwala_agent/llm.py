"""Minimal LLM interface. DeepSeek by default, OpenRouter and Anthropic optional; scripted fakes in tests.
Model output is treated as a proposal only: nothing here can sign or send."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: object = None


class LLM:
    def complete(self, system: str, messages: list[dict], tools: Optional[list[dict]] = None) -> LLMResponse:
        raise NotImplementedError


class AnthropicLLM(LLM):
    def __init__(self, model: str, max_tokens: int = 1024):
        import anthropic

        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model, self.max_tokens = model, max_tokens

    def complete(self, system, messages, tools=None):
        kw = dict(model=self.model, max_tokens=self.max_tokens, system=system, messages=messages)
        if tools:
            kw["tools"] = tools
        r = self.client.messages.create(**kw)
        text = "".join(b.text for b in r.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in r.content if b.type == "tool_use"]
        return LLMResponse(text, calls, r)


class ScriptedLLM(LLM):
    """Replays a list of responses, or calls a function(system, messages, tools) -> LLMResponse."""

    def __init__(self, script: list[LLMResponse] | Callable):
        self.script = script
        self.calls: list[dict] = []

    def complete(self, system, messages, tools=None):
        self.calls.append({"system": system, "messages": json.loads(json.dumps(messages, default=str)), "tools": tools})
        if callable(self.script):
            return self.script(system, messages, tools)
        return self.script.pop(0)


class DeepSeekLLM(LLM):
    """DeepSeek through its OpenAI-format API (https://api.deepseek.com). Converts the
    Anthropic-style history used internally (tool_use / tool_result blocks) to OpenAI
    chat messages and back."""

    BASE_URL = "https://api.deepseek.com"

    def __init__(self, model: str, max_tokens: int = 1024, client=None):
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                            base_url=os.environ.get("DEEPSEEK_BASE_URL", self.BASE_URL), timeout=60)
        self.client, self.model, self.max_tokens = client, model, max_tokens

    @staticmethod
    def to_openai(system: str, messages: list[dict]) -> list[dict]:
        out = [{"role": "system", "content": system}]
        for m in messages:
            c = m["content"]
            if isinstance(c, str):
                out.append({"role": m["role"], "content": c})
                continue
            if m["role"] == "assistant":
                text = "".join(b.get("text", "") for b in c if b["type"] == "text")
                calls = [{"id": b["id"], "type": "function",
                          "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                         for b in c if b["type"] == "tool_use"]
                msg = {"role": "assistant", "content": text or None}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
            else:
                for b in c:
                    if b["type"] == "tool_result":
                        out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
                    elif b["type"] == "text":
                        out.append({"role": "user", "content": b["text"]})
        return out

    @staticmethod
    def to_openai_tools(tools: list[dict]) -> list[dict]:
        return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                                  "parameters": t["input_schema"]}} for t in tools]

    def complete(self, system, messages, tools=None):
        kw = dict(model=self.model, max_tokens=self.max_tokens, messages=self.to_openai(system, messages),
                  temperature=0)
        if tools:
            kw["tools"] = self.to_openai_tools(tools)
        r = self._create(kw)
        msg = r.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_unparseable": tc.function.arguments}
            calls.append(ToolCall(tc.id, tc.function.name, args))
        return LLMResponse(msg.content or "", calls, r)

    def _create(self, kw, attempts: int = 5):
        """Retries HTTP 429 (free tiers rate-limit hard), honouring Retry-After. Other errors propagate,
        so the Checker still fails closed."""
        for i in range(attempts):
            try:
                return self.client.chat.completions.create(**kw)
            except Exception as e:
                if getattr(e, "status_code", None) != 429 or i == attempts - 1 or "per-day" in str(e):
                    raise  # a daily quota will not clear by waiting
                hdr = getattr(getattr(e, "response", None), "headers", None) or {}
                try:
                    wait = float(hdr.get("retry-after", ""))
                except ValueError:
                    wait = 2.0 * 2 ** i
                time.sleep(min(wait, 30.0))


class OpenRouterLLM(DeepSeekLLM):
    """Any OpenRouter model through the same OpenAI-format adapter. Used for free testing."""

    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, model: str, max_tokens: int = 4000, client=None):
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url=self.BASE_URL, timeout=120,
                            max_retries=0)
        super().__init__(model, max_tokens, client)


def from_env() -> dict[str, LLM]:
    """Coordinator, Treasury planner and Checker. TIWALA_LLM_PROVIDER = deepseek (default), openrouter or
    anthropic. The Checker defaults to a different model from the Coordinator so the two are less likely
    to share blind spots (except on openrouter, which is for free testing only)."""
    provider = os.environ.get("TIWALA_LLM_PROVIDER", "deepseek").lower()
    if provider == "openrouter":
        free = "nvidia/nemotron-3-ultra-550b-a55b:free"
        return {
            "coordinator": OpenRouterLLM(os.environ.get("TIWALA_COORDINATOR_MODEL", free)),
            "treasury": OpenRouterLLM(os.environ.get("TIWALA_TREASURY_MODEL", free)),
            "checker": OpenRouterLLM(os.environ.get("TIWALA_CHECKER_MODEL", free)),
        }
    if provider == "anthropic":
        return {
            "coordinator": AnthropicLLM(os.environ.get("TIWALA_COORDINATOR_MODEL", "claude-sonnet-5-5")),
            "treasury": AnthropicLLM(os.environ.get("TIWALA_TREASURY_MODEL", "claude-haiku-5-5")),
            "checker": AnthropicLLM(os.environ.get("TIWALA_CHECKER_MODEL", "claude-haiku-5-5"), max_tokens=300),
        }
    return {
        "coordinator": DeepSeekLLM(os.environ.get("TIWALA_COORDINATOR_MODEL", "deepseek-flash")),
        "treasury": DeepSeekLLM(os.environ.get("TIWALA_TREASURY_MODEL", "deepseek-flash")),
        "checker": DeepSeekLLM(os.environ.get("TIWALA_CHECKER_MODEL", "deepseek-v4-pro"), max_tokens=2000),
    }
