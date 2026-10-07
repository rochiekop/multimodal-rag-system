from types import SimpleNamespace
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.core.config import Settings
from app.guardrails.input import InputVerdict, check_input, moderation_categories
from app.guardrails.json_reply import parse_json_reply
from app.guardrails.settings import GuardrailSettings
from app.llm.gateway import get_moderator

CLEAN: dict[str, bool] = {}


def _moderate(flags: dict[str, bool]):
    async def moderate(text: str) -> dict[str, bool]:
        return flags

    return moderate


def _classifier(reply: str):
    model = FakeListChatModel(responses=[reply])
    calls: list[str] = []

    def factory(name: str) -> FakeListChatModel:
        calls.append(name)
        return model

    return factory, calls


async def _check(
    settings: GuardrailSettings | None = None,
    *,
    flags: dict[str, bool] = CLEAN,
    reply: str = "{}",
    sensitive: bool = False,
):
    factory, calls = _classifier(reply)
    usage: list[tuple[str, Any]] = []
    decision = await check_input(
        settings or GuardrailSettings(),
        "question",
        moderate=_moderate(flags),
        chat_model=factory,
        sensitive_scope=sensitive,
        on_usage=lambda model, u: usage.append((model, u)),
    )
    return decision, calls


def test_moderation_categories_map_provider_names() -> None:
    flags = {"illicit_violent": True, "self_harm_intent": True, "hate": False, "sexual": True}
    assert moderation_categories(flags) == {"weapons", "self_harm", "sexual"}


async def test_blocking_category_is_a_strike_and_flag_category_is_allowed() -> None:
    blocked, _ = await _check(flags={"violence": True})
    assert (blocked.action, blocked.check, blocked.category, blocked.strike) == (
        "block",
        "moderation",
        "violence",
        True,
    )
    settings = GuardrailSettings(moderation={**GuardrailSettings().moderation, "violence": "flag"})
    flagged, _ = await _check(settings, flags={"violence": True})
    assert flagged.action == "allow" and flagged.flags == (("moderation", "violence"),)
    off = GuardrailSettings(moderation={**GuardrailSettings().moderation, "violence": "off"})
    assert (await _check(off, flags={"violence": True}))[0].flags == ()


async def test_self_harm_gets_support_not_a_strike() -> None:
    decision, _ = await _check(flags={"self_harm": True})
    assert (decision.action, decision.strike) == ("support", False)


async def test_prompt_injection_is_blocked() -> None:
    decision, calls = await _check(reply='{"prompt_injection": true}')
    assert (decision.action, decision.check, decision.strike) == ("block", "prompt_injection", True)
    assert calls == ["gpt-5-nano"]
    off, _ = await _check(
        GuardrailSettings(injection_check=False), reply='{"prompt_injection": true}'
    )
    assert off.action == "allow"


async def test_exfiltration_blocks_only_in_sensitive_scope() -> None:
    reply = '```json\n{"exfiltration": true}\n```'
    assert (await _check(reply=reply, sensitive=False))[0].action == "allow"
    decision, _ = await _check(reply=reply, sensitive=True)
    assert (decision.action, decision.check) == ("block", "exfiltration")


async def test_scope_check_redirects_off_topic_questions() -> None:
    reply = '{"off_topic": true}'
    assert (await _check(reply=reply))[0].action == "allow"  # scope check off by default
    settings = GuardrailSettings(scope_check=True, scope_description="HR policies")
    decision, _ = await _check(settings, reply=reply)
    assert (decision.action, decision.strike) == ("off_topic", False)


async def test_classifier_skipped_when_no_check_needs_it() -> None:
    settings = GuardrailSettings(injection_check=False, exfiltration_check=True)
    _, calls = await _check(settings, sensitive=False)
    assert calls == []


async def test_unreadable_classifier_reply_fails_open() -> None:
    decision, _ = await _check(reply="I think this is fine.")
    assert decision.action == "allow"


async def test_provider_failures_fail_open() -> None:
    async def broken_moderation(text: str) -> dict[str, bool]:
        raise RuntimeError("moderation down")

    def broken_model(name: str):
        raise RuntimeError("model down")

    decision = await check_input(
        GuardrailSettings(),
        "question",
        moderate=broken_moderation,
        chat_model=broken_model,
        sensitive_scope=True,
        on_usage=lambda model, usage: None,
    )
    assert decision.action == "allow"


def test_parse_json_reply_finds_the_object() -> None:
    assert parse_json_reply('Sure: {"off_topic": true} done', InputVerdict).off_topic is True


async def test_get_moderator_returns_category_flags() -> None:
    categories = SimpleNamespace(model_dump=lambda: {"violence": True, "hate": False})
    response = SimpleNamespace(results=[SimpleNamespace(categories=categories)])
    seen: dict[str, Any] = {}

    async def create(**kwargs: Any) -> SimpleNamespace:
        seen.update(kwargs)
        return response

    client = SimpleNamespace(moderations=SimpleNamespace(create=create))
    moderate = get_moderator(Settings(_env_file=None, jwt_secret="x" * 40), client=client)
    assert await moderate("hello") == {"violence": True, "hate": False}
    assert seen == {"model": "omni-moderation-latest", "input": "hello"}
