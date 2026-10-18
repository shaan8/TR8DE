"""DeepSeek adapter: Anthropic-style history <-> OpenAI chat format, with a fake client (no network)."""
import json
from types import SimpleNamespace as NS

from tiwala_agent.agents import COORDINATOR_TOOLS, checker_review
from tiwala_agent.llm import DeepSeekLLM, OpenRouterLLM, from_env


class FakeClient:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.sent.append(kw)
        content, calls = self.replies.pop(0)
        tcs = [NS(id=f"call_{i}", function=NS(name=n, arguments=json.dumps(a))) for i, (n, a) in enumerate(calls)]
        return NS(choices=[NS(message=NS(content=content, tool_calls=tcs or None))])


def test_history_conversion_round_trip():
    history = [
        {"role": "user", "content": "Pay the Lumen down payment"},
        {"role": "assistant", "content": [{"type": "text", "text": "Checking."},
                                          {"type": "tool_use", "id": "t1", "name": "get_overview", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{\"free_php\": 1}"}]},
    ]
    out = DeepSeekLLM.to_openai("SYS", history)
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool"]
    assert out[2]["tool_calls"][0]["function"] == {"name": "get_overview", "arguments": "{}"}
    assert out[3]["tool_call_id"] == "t1"
    tools = DeepSeekLLM.to_openai_tools(COORDINATOR_TOOLS)
    assert tools[3]["function"]["name"] == "draft_create_deal"
    assert tools[3]["function"]["parameters"]["required"][0] == "supplier"


def test_tool_calls_parsed_and_model_sent():
    fc = FakeClient([(None, [("draft_release_balance", {"deal_id": 3})])])
    llm = DeepSeekLLM("deepseek-flash", client=fc)
    r = llm.complete("SYS", [{"role": "user", "content": "release deal 3"}], COORDINATOR_TOOLS)
    assert r.tool_calls[0].name == "draft_release_balance" and r.tool_calls[0].args == {"deal_id": 3}
    assert fc.sent[0]["model"] == "deepseek-flash" and fc.sent[0]["temperature"] == 0


def test_checker_on_deepseek_fails_closed_on_empty_content():
    ok, _ = checker_review(DeepSeekLLM("deepseek-v4-pro", client=FakeClient([("", [])])), "req", {"kind": "x"})
    assert ok is False
    ok2, _ = checker_review(DeepSeekLLM("deepseek-v4-pro", client=FakeClient([('{"approve": true, "reason": "ok"}', [])])),
                            "req", {"kind": "x"})
    assert ok2 is True


class RateLimited(Exception):
    status_code = 429
    response = NS(headers={"retry-after": "0"})


def test_openrouter_retries_429_then_succeeds():
    fc = FakeClient([('{"approve": true, "reason": "ok"}', [])])
    real, n = fc._create, []

    def flaky(**kw):
        n.append(1)
        if len(n) < 3:
            raise RateLimited()
        return real(**kw)

    fc.chat.completions.create = flaky
    ok, _ = checker_review(OpenRouterLLM("m", client=fc), "pay", {"x": 1})
    assert ok and len(n) == 3


def test_openrouter_429_exhausted_fails_closed(monkeypatch):
    monkeypatch.setattr("tiwala_agent.llm.time.sleep", lambda s: None)
    fc = FakeClient([])

    def always(**kw):
        raise RateLimited()

    fc.chat.completions.create = always
    ok, reason = checker_review(OpenRouterLLM("m", client=fc), "pay", {"x": 1})
    assert not ok and "failing closed" in reason


def test_openrouter_provider_defaults(monkeypatch):
    monkeypatch.setenv("TIWALA_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    for k in ("TIWALA_COORDINATOR_MODEL", "TIWALA_TREASURY_MODEL", "TIWALA_CHECKER_MODEL"):
        monkeypatch.delenv(k, raising=False)
    llms = from_env()
    assert {l.model for l in llms.values()} == {"nvidia/nemotron-3-ultra-550b-a55b:free"}
    assert str(llms["checker"].client.base_url).startswith("https://openrouter.ai/api/v1")


def test_daily_quota_429_is_not_retried():
    fc, n = FakeClient([]), []

    class Daily(RateLimited):
        def __str__(self):
            return "Rate limit exceeded: free-models-per-day"

    def always(**kw):
        n.append(1)
        raise Daily()

    fc.chat.completions.create = always
    ok, reason = checker_review(OpenRouterLLM("m", client=fc), "pay", {"x": 1})
    assert not ok and len(n) == 1
