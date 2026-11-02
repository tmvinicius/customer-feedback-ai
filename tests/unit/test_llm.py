"""LLM layer: pricing, cost log, cache, FakeLLM and the Anthropic adapter. No network."""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from customer_feedback_ai.llm.anthropic_client import AnthropicBatchClient, build_params, to_result
from customer_feedback_ai.llm.cache import ResultCache
from customer_feedback_ai.llm.cost_log import CallRecord, CostLog
from customer_feedback_ai.llm.fake import FakeLLM, fake_label
from customer_feedback_ai.llm.pricing import ModelPrices, Pricing, load_pricing
from customer_feedback_ai.llm.types import LLMRequest, LLMResult, TokenUsage
from customer_feedback_ai.settings import Settings

from .conftest import REPO_ROOT

REQUEST = LLMRequest(
    custom_id="abc",
    model="claude-haiku-5-5",
    system="Classifique.",
    user="<reclamacao>\nTexto sintético.\n</reclamacao>",
    max_tokens=1024,
    effort="low",
    json_schema={"type": "object"},
)


def pricing() -> Pricing:
    return Pricing(
        checked_at=date(2026, 11, 11),
        source="test",
        batch_discount=0.5,
        models={
            "m": ModelPrices(
                max_prompt_tokens=1000, input=1.0, output=10.0, cache_write_5m=1.25, cache_read=0.1
            )
        },
    )


# --- pricing ---------------------------------------------------------------------


def test_cost_uses_every_token_kind() -> None:
    usage = TokenUsage(
        input_tokens=100,
        output_tokens=10,
        cache_creation_input_tokens=200,
        cache_read_input_tokens=300,
    )
    expected = (100 * 1.0 + 10 * 10.0 + 200 * 1.25 + 300 * 0.1) / 1_000_000
    assert pricing().cost_usd("m", usage, batch=False) == pytest.approx(expected)
    assert pricing().cost_usd("m", usage, batch=True) == pytest.approx(expected / 2)


def test_cost_refuses_prompts_above_the_priced_tier() -> None:
    with pytest.raises(ValueError, match="priced tier"):
        pricing().cost_usd(
            "m",
            TokenUsage(input_tokens=900, output_tokens=0, cache_read_input_tokens=200),
            batch=True,
        )


def test_unknown_model_has_no_price() -> None:
    with pytest.raises(KeyError, match="no price"):
        pricing().cost_usd("other", TokenUsage(1, 1), batch=False)


def test_pricing_config_covers_the_default_models() -> None:
    config = load_pricing(REPO_ROOT / "configs" / "pricing.yaml")
    defaults = Settings(_env_file=None)
    for model in (defaults.llm_model_cheap, defaults.llm_model_premium, defaults.llm_model_draft):
        assert model in config.models
    assert config.batch_discount == 0.5
    assert config.source.startswith("https://platform.claude.com/")


# --- cost log --------------------------------------------------------------------


def record(cost: float) -> CallRecord:
    return CallRecord(
        experiment="e",
        backend="b",
        model="m",
        custom_id="id",
        status="succeeded",
        input_tokens=1,
        output_tokens=1,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        cost_usd=cost,
        batch=True,
        prompt_hash="h",
    )


def test_cost_log_sums_spend(tmp_path: Path) -> None:
    log = CostLog(tmp_path / "logs" / "llm_calls.jsonl")
    assert log.spent_usd() == 0
    log.append([record(0.5), record(0.25)])
    log.append([record(1.0)])
    assert log.spent_usd() == pytest.approx(1.75)
    assert all(r["timestamp"] for r in log.records())


def test_cost_log_has_no_text_fields() -> None:
    assert not {"text", "system", "user", "reclamacao_labeled"} & set(
        CallRecord.__dataclass_fields__
    )


# --- cache -----------------------------------------------------------------------


def test_cache_hits_only_the_same_request(tmp_path: Path) -> None:
    cache = ResultCache(tmp_path)
    result = LLMResult("abc", "succeeded", text='{"x": 1}', usage=TokenUsage(3, 4))
    cache.put(REQUEST, result)

    hit = cache.get(REQUEST)
    assert hit is not None
    assert hit.text == '{"x": 1}'
    assert hit.usage == TokenUsage(3, 4)
    for change in (
        {"model": "other"},
        {"system": "Outro."},
        {"user": "x"},
        {"max_tokens": 9},
        {"effort": "high"},
        {"json_schema": {"type": "string"}},
    ):
        assert cache.get(LLMRequest(**{**REQUEST.__dict__, **change})) is None


def test_cache_ignores_failed_results(tmp_path: Path) -> None:
    cache = ResultCache(tmp_path)
    cache.put(REQUEST, LLMResult("abc", "errored", error="overloaded"))
    assert cache.get(REQUEST) is None


# --- FakeLLM ---------------------------------------------------------------------


def test_fake_llm_is_deterministic_and_offline() -> None:
    fake = FakeLLM()
    batch = fake.submit_batch([REQUEST])
    assert not fake.is_external
    assert fake.batch_ended(batch)
    first = list(fake.batch_results(batch))
    other = FakeLLM()
    second = list(other.batch_results(other.submit_batch([REQUEST])))
    assert first == second
    assert json.loads(str(first[0].text)) == fake_label(REQUEST.user)


def test_fake_llm_breaks_first_attempt_when_asked() -> None:
    fake = FakeLLM(invalid_first_every=1)
    batch = fake.submit_batch([REQUEST])
    assert next(fake.batch_results(batch)).text == "not json"
    assert next(fake.batch_results(batch)).text != "not json"


# --- Anthropic adapter -----------------------------------------------------------


def test_params_ask_for_structured_output_and_effort() -> None:
    params: dict[str, Any] = dict(build_params(REQUEST))
    assert params["model"] == "claude-haiku-5-5"
    assert params["max_tokens"] == 1024
    assert params["messages"] == [{"role": "user", "content": REQUEST.user}]
    assert params["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": {"type": "object"}},
    }
    assert params["system"] == "Classifique."
    assert "thinking" not in params


def test_params_can_cache_the_system_prompt() -> None:
    params: dict[str, Any] = dict(
        build_params(LLMRequest(**{**REQUEST.__dict__, "cache_system": True}))
    )
    assert params["system"] == [
        {"type": "text", "text": "Classifique.", "cache_control": {"type": "ephemeral"}}
    ]


def message(stop_reason: str, text: str | None = '{"a": 1}') -> SimpleNamespace:
    content = [SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=text)]
    usage = SimpleNamespace(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=None,
        cache_read_input_tokens=2,
    )
    return SimpleNamespace(
        type="succeeded",
        message=SimpleNamespace(stop_reason=stop_reason, content=content, usage=usage),
    )


def test_results_are_mapped_by_stop_reason() -> None:
    ok = to_result("a", message("end_turn"))
    assert (ok.status, ok.text, ok.usage) == ("succeeded", '{"a": 1}', TokenUsage(10, 5, 0, 2))
    assert to_result("a", message("refusal")).status == "refused"
    assert to_result("a", message("max_tokens")).status == "truncated"
    errored = to_result(
        "a", SimpleNamespace(type="errored", error=SimpleNamespace(type="overloaded_error"))
    )
    assert (errored.status, errored.error) == ("errored", "overloaded_error")
    assert to_result("a", SimpleNamespace(type="expired")).status == "expired"


class StubBatches:
    def __init__(self) -> None:
        self.created: list[Any] = []

    def create(self, requests: list[Any]) -> SimpleNamespace:
        self.created.extend(requests)
        return SimpleNamespace(id="msgbatch_1")

    def retrieve(self, batch_id: str) -> SimpleNamespace:
        return SimpleNamespace(processing_status="ended")

    def results(self, batch_id: str) -> list[SimpleNamespace]:
        return [SimpleNamespace(custom_id="abc", result=message("end_turn"))]


def test_client_submits_and_reads_batches_through_the_sdk() -> None:
    batches = StubBatches()
    sdk = SimpleNamespace(messages=SimpleNamespace(batches=batches))
    client = AnthropicBatchClient(sdk=sdk)  # type: ignore[arg-type]

    assert client.is_external
    assert client.name == "anthropic"
    assert client.submit_batch([REQUEST]) == "msgbatch_1"
    assert batches.created[0]["custom_id"] == "abc"
    assert client.batch_ended("msgbatch_1")
    assert [r.custom_id for r in client.batch_results("msgbatch_1")] == ["abc"]
