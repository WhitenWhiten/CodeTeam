import asyncio
from types import SimpleNamespace as NS
import pytest

from app.bootstrap import bootstrap
from app.config import SystemConfig
from core.contracts import BudgetExceeded, RunStatus
from core.llm_openai import OpenAILLM
from orchestrator.workflow import MultiAgentCodegenWorkflow


def client(create):
    return NS(chat=NS(completions=NS(create=create)))


def response(text="ok", tokens=5):
    return NS(choices=[NS(message=NS(content=text))], usage=NS(total_tokens=tokens) if tokens is not None else None)


def test_structured_repair_counts_every_provider_attempt():
    replies = iter([response("invalid"), response('{"a": 1}')])
    async def create(**kwargs):
        return next(replies)
    model = OpenAILLM(client=client(create))
    assert asyncio.run(model.structured_json("task")) == {"a": 1}
    assert model.total_tokens == 10 and model.total_calls == 2


def test_unknown_usage_is_charged_and_call_budget_is_enforced():
    async def create(**kwargs):
        return response(tokens=None)
    model = OpenAILLM(client=client(create), call_limit=1, max_tokens=20)
    asyncio.run(model.text("task"))
    assert model.total_tokens > 20
    assert model.usage.records[0]["usage_source"] == "conservative_reservation"
    with pytest.raises(BudgetExceeded):
        asyncio.run(model.text("task"))


def test_concurrent_reservations_prevent_oversubscription_and_cancel_client():
    async def scenario():
        started = asyncio.Event()
        cancelled = asyncio.Event()
        async def create(**kwargs):
            started.set()
            try:
                await asyncio.sleep(100)
            finally:
                cancelled.set()
        model = OpenAILLM(client=client(create), token_limit=250, max_tokens=100)
        task = asyncio.create_task(model.text("task"))
        await started.wait()
        with pytest.raises(BudgetExceeded):
            await model.text("task")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()
        assert model.usage.reserved_tokens == 0
        assert model.total_calls == 1 and model.total_tokens == 250
    asyncio.run(scenario())


def test_auth_errors_are_not_retried():
    class AuthError(Exception):
        status_code = 401
    async def create(**kwargs):
        raise AuthError("invalid credentials")
    model = OpenAILLM(client=client(create))
    with pytest.raises(AuthError):
        asyncio.run(model.text("task"))
    assert model.total_calls == 1


def test_request_timeout_finishes_without_background_request():
    finished = []
    async def create(**kwargs):
        try:
            await asyncio.sleep(100)
        finally:
            finished.append(True)
    model = OpenAILLM(client=client(create), request_timeout=0.01, request_retries=0)
    with pytest.raises(TimeoutError):
        asyncio.run(model.text("task"))
    assert finished and model.usage.reserved_tokens == 0


def test_workflow_preserves_planning_and_developer_budget_status(tmp_path):
    for calls in (0, 6):
        cfg = SystemConfig(workspace=str(tmp_path / str(calls)), max_model_calls=calls, architects=4)
        cfg.git.enabled = False
        result = MultiAgentCodegenWorkflow(bootstrap(cfg)).run_sync("shop")
        assert result.status == RunStatus.BUDGET_EXHAUSTED, result.reason


def test_unknown_provider_is_not_silently_mocked(tmp_path):
    cfg = SystemConfig(workspace=str(tmp_path))
    cfg.llm.provider = "typo"
    with pytest.raises(ValueError, match="Unsupported"):
        bootstrap(cfg)
