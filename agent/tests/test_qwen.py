"""Offline checks: credential persistence, provider selection, and Qwen tool calling."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from tiwala_agent.llm import QwenLLM, from_env, negotiation_llms

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "setup_qwen.py"
spec = importlib.util.spec_from_file_location("setup_qwen", SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_env_preserves_other_settings_replaces_duplicates_and_sets_all_roles(tmp_path):
    env = tmp_path / ".env"
    original = "# My config\nOWNER_PRIVATE_KEY=existing-owner\nWHATSAPP_TOKEN=existing-token\n"
    env.write_text(original + "export DASHSCOPE_API_KEY=old\nDASHSCOPE_API_KEY=duplicate\n"
                   "TIWALA_LLM_PROVIDER=deepseek\nTIWALA_CHECKER_MODEL=old-model\nCUSTOM=value")
    setup.update_env(env, "sk-fake-test-key")
    data = env.read_text()
    assert data.startswith(original)
    assert "CUSTOM=value\n" in data
    assert data.count("DASHSCOPE_API_KEY=") == 1
    assert "DASHSCOPE_API_KEY=sk-fake-test-key\n" in data
    assert "TIWALA_LLM_PROVIDER=qwen\n" in data
    assert "QWEN_ENABLE_THINKING=true\n" in data
    for name, model in setup.MODEL_SETTINGS.items():
        assert f"{name}={model}\n" in data
    if os.name != "nt":
        assert env.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".qwen-config-*"))
    setup.update_env(env, "sk-fake-test-key")
    assert env.read_text() == data


@pytest.mark.parametrize("key", ["", "  ", "sk-test\nEVIL=value", "$(command)", "sk-key#comment", '"sk-key"'])
def test_invalid_key_does_not_modify_env(tmp_path, key):
    env = tmp_path / ".env"
    env.write_text("EXISTING=keep\n")
    with pytest.raises(ValueError):
        setup.update_env(env, key)
    assert env.read_text() == "EXISTING=keep\n"


def test_atomic_write_failure_preserves_original_and_cleans_temp(tmp_path):
    env = tmp_path / ".env"
    env.write_text("EXISTING=keep\n")
    with patch.object(setup.os, "replace", side_effect=OSError("test failure")):
        with pytest.raises(OSError):
            setup.update_env(env, "sk-fake-test-key")
    assert env.read_text() == "EXISTING=keep\n"
    assert not list(tmp_path.glob(".qwen-config-*"))


def test_env_can_be_created_and_symlinks_are_refused(tmp_path):
    env = tmp_path / ".env"
    setup.update_env(env, "sk-fake-test-key")
    linked = tmp_path / "linked"
    linked.symlink_to(env)
    with pytest.raises(ValueError):
        setup.update_env(linked, "sk-new-test-key")
    assert "sk-fake-test-key" in env.read_text()


def test_prompt_uses_getpass_and_does_not_print_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(setup, "find_project", lambda explicit: tmp_path)
    monkeypatch.setattr("sys.argv", [str(SCRIPT)])
    monkeypatch.setattr(setup.getpass, "getpass", lambda prompt: "sk-fake-test-key")
    assert setup.main() == 0
    assert "sk-fake-test-key" not in capsys.readouterr().out


def test_qwen_tool_conversion_thinking_and_reasoning_not_returned():
    sent = []
    def create(**kwargs):
        sent.append(kwargs)
        return NS(choices=[NS(message=NS(content="Checking your wallet.", reasoning_content="private reasoning",
            tool_calls=[NS(id="call_1", function=NS(name="get_overview", arguments="{}"))]))])
    client = NS(chat=NS(completions=NS(create=create)))
    llm = QwenLLM(client=client)
    result = llm.complete("SYS", [{"role": "user", "content": "What's open?"}],
                          [{"name": "get_overview", "input_schema": {"type": "object"}}])
    assert sent[0]["model"] == "qwen3.7-plus"
    assert sent[0]["extra_body"] == {"enable_thinking": True}
    assert sent[0]["tools"][0]["function"]["name"] == "get_overview"
    assert result.text == "Checking your wallet."
    assert result.tool_calls[0].name == "get_overview"
    assert result.tool_calls[0].args == {}


def test_qwen_provider_and_negotiation_configuration(monkeypatch):
    monkeypatch.setenv("TIWALA_LLM_PROVIDER", "qwen")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-fake-test-key")
    monkeypatch.setenv("QWEN_ENABLE_THINKING", "true")
    for name in (*setup.MODEL_KEYS, "DASHSCOPE_BASE_URL", "TIWALA_SUPPLIER_AGENT", "TIWALA_NEGOTIATOR"):
        monkeypatch.delenv(name, raising=False)
    wallet = from_env()
    negotiation = negotiation_llms()
    assert wallet["coordinator"].model == "qwen3.7-plus"
    assert wallet["treasury"].model == "qwen3.7-plus"
    assert wallet["checker"].model == "qwen3.8-flash"
    models = [*wallet.values(), *(negotiation[k] for k in ("negotiator", "interpreter", "supplier"))]
    assert all(isinstance(model, QwenLLM) for model in models)
    assert all(model.model == "qwen3.7-plus" for role, model in wallet.items() if role != "checker")
    assert all(negotiation[k].model == "qwen3.7-plus" for k in ("negotiator", "interpreter", "supplier"))
    assert wallet["coordinator"].model != wallet["checker"].model
    assert len({id(model) for model in models}) == len(models)
    assert all(str(model.client.base_url).rstrip("/") == setup.BASE_URL for model in models)
    monkeypatch.setenv("TIWALA_SUPPLIER_AGENT", "scripted")
    monkeypatch.setenv("TIWALA_NEGOTIATOR", "rules")
    off = negotiation_llms()
    assert all(off[k] is None for k in ("negotiator", "interpreter", "supplier"))


def test_missing_qwen_key_is_actionable(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="setup_qwen.py"):
        QwenLLM()


def test_token_plan_keys_use_the_token_plan_endpoint(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    assert QwenLLM.base_url_for("sk-sp-abc") == QwenLLM.TOKEN_PLAN_URL
    assert QwenLLM.base_url_for("sk-abc") == QwenLLM.BASE_URL
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://example.test/v1")
    assert QwenLLM.base_url_for("sk-sp-abc") == "https://example.test/v1"
