"""Run-scoped accounting. Unknown costs retain their reservation conservatively."""
from __future__ import annotations

import json
import time
from core.contracts import BudgetExceeded


class UsageLedger:
    def __init__(self, token_limit=None, call_limit=None):
        self.token_limit = token_limit
        self.call_limit = call_limit
        self.total_tokens = 0
        self.reserved_tokens = 0
        self.calls = 0
        self.records = []
        self.recorder = None

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
        record = {"call": self.calls, "prompt": prompt, "reserved": input_estimate + max_output,
                  "max_output_tokens": max_output, "started": time.monotonic()}
        self.reserved_tokens += record["reserved"]
        return record

    def finish(self, record, output=None, usage=None, error=None):
        self.reserved_tokens -= record["reserved"]
        reported = getattr(usage, "total_tokens", None)
        known = isinstance(reported, int) and not isinstance(reported, bool) and reported >= 0
        charged = reported if known else record["reserved"]
        self.total_tokens += charged
        record.update(output=output, error=error, tokens=charged,
                      usage_source="provider" if known else "conservative_reservation",
                      elapsed_seconds=time.monotonic() - record.pop("started"))
        self.records.append(record)
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
