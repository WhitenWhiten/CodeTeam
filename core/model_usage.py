"""Run-scoped accounting. Unknown costs retain their reservation conservatively."""
from __future__ import annotations

import json
import time
from core.contracts import BudgetExceeded
from core.call_context import current_call_context


class UsageLedger:
    def __init__(self, token_limit=None, call_limit=None):
        self.token_limit = token_limit
        self.call_limit = call_limit
        self.total_tokens = 0
        self.reserved_tokens = 0
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.reported_tokens = 0
        self.estimated_tokens = 0
        self.unknown_usage_calls = 0
        self.pending_calls = 0
        self.records = []
        self.recorder = None
        self.state_recorder = None

    def snapshot(self):
        return {"total_tokens": self.total_tokens, "reserved_tokens": self.reserved_tokens, "calls": self.calls,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "reported_tokens": self.reported_tokens, "estimated_tokens": self.estimated_tokens,
                "unknown_usage_calls": self.unknown_usage_calls, "pending_calls": self.pending_calls}

    def restore(self, state):
        self.total_tokens = int(state["total_tokens"]) + int(state.get("reserved_tokens", 0))
        self.calls = int(state["calls"])
        self.reserved_tokens = 0
        self.input_tokens = int(state.get('input_tokens', 0))
        self.output_tokens = int(state.get('output_tokens', 0))
        self.reported_tokens = int(state.get('reported_tokens', 0))
        self.estimated_tokens = int(state.get('estimated_tokens', state['total_tokens'])) + int(state.get('reserved_tokens', 0))
        self.unknown_usage_calls = int(state.get('unknown_usage_calls', 0)) + int(state.get('pending_calls', 0))
        self.pending_calls = 0
        if self.total_tokens < 0 or self.calls < 0:
            raise ValueError("Invalid persisted usage counters")
        self.check()

    def reserve(self, prompt, max_output):
        # UTF-8 bytes plus message overhead: conservative admission estimate,
        # not a model-specific tokenizer or a promise about provider billing.
        input_estimate = len(prompt.encode("utf-8")) + 128
        if self.call_limit is not None and self.calls >= self.call_limit:
            raise BudgetExceeded("Model call budget exhausted")
        if self.token_limit is not None:
            available = self.token_limit - self.total_tokens - self.reserved_tokens - input_estimate
            max_output = min(max_output, available)
        if max_output < 1:
            raise BudgetExceeded("Token budget cannot admit another model request")
        self.calls += 1
        self.pending_calls += 1
        record = {"call": self.calls, "prompt": prompt, "reserved": input_estimate + max_output,
                  "max_output_tokens": max_output, "started": time.monotonic(),
                  "started_at_unix": time.time(), **current_call_context.get()}
        self.reserved_tokens += record["reserved"]
        if self.state_recorder:
            self.state_recorder(self.snapshot())
        return record

    def finish(self, record, output=None, usage=None, error=None):
        self.reserved_tokens -= record["reserved"]
        self.pending_calls -= 1
        def count(name):
            value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
            return value if type(value) is int and value >= 0 else None
        prompt, completion, reported = count('prompt_tokens'), count('completion_tokens'), count('total_tokens')
        if reported is None and prompt is not None and completion is not None:
            reported = prompt + completion
        known = isinstance(reported, int) and not isinstance(reported, bool) and reported >= 0
        charged = reported if known else record["reserved"]
        self.total_tokens += charged
        self.input_tokens += prompt or 0
        self.output_tokens += completion or 0
        self.reported_tokens += reported or 0
        self.estimated_tokens += 0 if known else charged
        self.unknown_usage_calls += int(not known)
        record.update(output=output, error=error, tokens=charged,
                      input_tokens=prompt, output_tokens=completion, reported_total_tokens=reported,
                      token_breakdown_complete=prompt is not None and completion is not None,
                      provider_usage=usage if isinstance(usage, dict) else usage.model_dump() if hasattr(usage, 'model_dump') else None,
                      finished_at_unix=time.time(),
                      usage_source="provider" if known else "conservative_reservation",
                      elapsed_seconds=time.monotonic() - record.pop("started"))
        self.records.append(record)
        if self.state_recorder:
            self.state_recorder(self.snapshot())
        if self.recorder:
            self.recorder(record)

    def check(self):
        if self.token_limit is not None and self.total_tokens > self.token_limit:
            raise BudgetExceeded("Provider usage exceeded the configured token budget")


class MeteredModel:
    @property
    def total_tokens(self):
        return self.usage.total_tokens

    @property
    def total_calls(self):
        return self.usage.calls


def metered_mock(cfg, token_limit=None, call_limit=None):
    from core.llm import LLMClient

    class Mock(MeteredModel, LLMClient):
        async def _invoke(self, method, prompt, **kwargs):
            record = self.usage.reserve(prompt, cfg.max_tokens)
            record.update(model=cfg.model, provider='mock', sampling_seed=getattr(cfg, 'seed', None))
            record['messages'] = [{'role': 'user', 'content': prompt}]
            try:
                value = await method(prompt, **kwargs)
            except BaseException as exc:
                self.usage.finish(record, error=type(exc).__name__)
                raise
            self.usage.finish(record, output=value)
            self.usage.check()
            return value

        async def text(self, prompt):
            return await self._invoke(super().text, prompt)

        async def structured_json(self, prompt, schema=None, **kwargs):
            return await self._invoke(super().structured_json, prompt, schema=schema)

        async def files(self, prompt):
            return await self._invoke(super().files, prompt)

    model = Mock(cfg)
    model.usage = UsageLedger(token_limit, call_limit)
    return model
