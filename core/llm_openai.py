# core/llm_openai.py
from __future__ import annotations
import os, json, asyncio
from core.model_usage import UsageLedger, MeteredModel
from core.contracts import ModelRequestTimeout
from typing import Any, Dict, Optional
try:
    import jsonschema
except ImportError:
    jsonschema = None

from core.schemas import (
    QA_TEST_BUNDLE_SCHEMA,
    SDS_SCHEMA,
    UPDATE_REASON_SCHEMA,
    validate_qa_test_bundle,
    validate_sds,
    validate_update_reason,
)

try:
    from openai import AsyncOpenAI
except Exception:
    AsyncOpenAI = None

class OpenAILLM(MeteredModel):
    def __init__(
        self,
        model: str = "gpt-4o",
        temperature: float = 0.2,
        max_tokens: int = 4000,
        top_p: float = 0.95,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        request_timeout: float = 60,
        request_retries: int = 2,
        token_limit: int | None = None,
        call_limit: int | None = None,
        client=None,
    ):
        if AsyncOpenAI is None and client is None:
            raise RuntimeError("Install the openai dependency to use this provider")
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key and client is None:
            raise RuntimeError("OPENAI_API_KEY not set")
        self.client = client or AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=request_timeout, max_retries=0)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.request_timeout = request_timeout
        self.request_retries = request_retries
        self.usage = UsageLedger(token_limit, call_limit)

    async def close(self):
        await self.client.close()

    async def text(self, prompt: str) -> str:
        return await self._request(prompt, json_mode=False)

    async def _request(self, prompt, json_mode):
        system = "Return ONLY a valid JSON object." if json_mode else "You are a senior software engineer."
        for attempt in range(self.request_retries + 1):
            record = self.usage.reserve(system + prompt, self.max_tokens)
            record.update(model=self.model, temperature=self.temperature, top_p=self.top_p, attempt=attempt + 1)
            try:
                options = {"response_format": {"type": "json_object"}} if json_mode else {}
                async with asyncio.timeout(self.request_timeout):
                    resp = await self.client.chat.completions.create(
                    model=self.model,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    max_tokens=record["max_output_tokens"],
                    messages=[{"role":"system","content":system},
                              {"role":"user","content":prompt}],
                    **options,
                )
                content = resp.choices[0].message.content or ""
            except BaseException as exc:
                self.usage.finish(record, error=type(exc).__name__)
                status = getattr(exc, "status_code", None)
                transient = isinstance(exc, (TimeoutError, ConnectionError)) or type(exc).__name__ in {"APIConnectionError", "APITimeoutError"} or status in {408, 409, 429} or isinstance(status, int) and status >= 500
                if not transient or attempt == self.request_retries:
                    if isinstance(exc, TimeoutError):
                        raise ModelRequestTimeout("Model request timeout exhausted") from exc
                    raise
                await asyncio.sleep(min(0.5 * 2 ** attempt, 4))
                continue
            self.usage.finish(record, output=content, usage=getattr(resp, "usage", None))
            self.usage.check()
            return content

    async def structured_json(self, prompt: str, schema: str | Dict[str, Any] | None = None, max_retries: int = 3) -> Dict[str, Any]:
        # Use response_format to force JSON, then validate and repair against the schema.
        schema_dict = None
        named_validator = None
        if isinstance(schema, dict):
            schema_dict = schema
        elif isinstance(schema, str):
            if schema.upper() == "SDS":
                schema_dict = SDS_SCHEMA
                named_validator = validate_sds
            elif schema.upper() == "CTO_DECISION":
                schema_dict = {"type":"object","required":["chosen_index"],"properties":{"chosen_index":{"type":"number"},"rationale":{"type":"string"}}}
            elif schema.upper() == "UPDATE_REASON":
                schema_dict = UPDATE_REASON_SCHEMA
                named_validator = validate_update_reason
            elif schema.upper() == "QA_TEST_BUNDLE":
                schema_dict = QA_TEST_BUNDLE_SCHEMA
                named_validator = validate_qa_test_bundle
            else:
                raise ValueError(f"Unknown structured output schema: {schema}")

        content = await self._gen_json_once(prompt)
        parsed = self._safe_parse_json(content)
        if schema_dict:
            ok, errs = self._validate(parsed, schema_dict, validator=named_validator)
            if ok:
                return parsed
        else:
            if parsed is not None:
                return parsed

        # Repair retries.
        last_msg = content
        for i in range(max_retries):
            repair_prompt = self._build_repair_prompt(last_msg, schema_dict)
            content = await self._gen_json_once(repair_prompt)
            parsed = self._safe_parse_json(content)
            if schema_dict:
                ok, errs = self._validate(parsed, schema_dict, validator=named_validator)
                if ok:
                    return parsed
                last_msg = content + f"\n\nSchemaErrors: {errs}"
            else:
                if parsed is not None:
                    return parsed
                last_msg = content
        raise ValueError("Failed to produce valid structured JSON after retries")

    async def files(self, prompt: str, max_retries: int = 3) -> Dict[str, str]:
        # Expect the model to return {"path": "content", ...}.
        content = await self._gen_json_once(prompt)
        parsed = self._safe_parse_json(content)
        if isinstance(parsed, dict) and all(isinstance(k,str) and isinstance(v,str) for k,v in parsed.items()):
            return parsed
        # Try repair.
        for i in range(max_retries):
            repair_prompt = f"Please return ONLY a valid JSON object mapping file paths to string contents. Example: {{\"tests/test_x.py\":\"content\"}}. Your previous content:\n{content}"
            content = await self._gen_json_once(repair_prompt)
            parsed = self._safe_parse_json(content)
            if isinstance(parsed, dict) and all(isinstance(k,str) and isinstance(v,str) for k,v in parsed.items()):
                return parsed
        raise ValueError("Failed to produce files JSON")

    async def _gen_json_once(self, prompt: str) -> str:
        return await self._request(prompt, json_mode=True)

    def _safe_parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        # Extract the outermost JSON object.
        if not text.strip().startswith("{"):
            # Try slicing from the first { to the last }.
            m1 = text.find("{")
            m2 = text.rfind("}")
            if m1 != -1 and m2 != -1 and m2 > m1:
                text = text[m1:m2+1]
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _validate(self, obj: Any, schema: Dict[str, Any], validator=None) -> tuple[bool, str]:
        try:
            if validator is not None:
                validator(obj)
            elif jsonschema is not None:
                jsonschema.validate(obj, schema)
            else:
                raise RuntimeError("jsonschema is required to validate structured output")
            return True, ""
        except Exception as e:
            return False, str(e)

    def _build_repair_prompt(self, last_json_text: str, schema: Optional[Dict[str, Any]]) -> str:
        schema_hint = json.dumps(schema, ensure_ascii=False) if schema else "{}"
        return f"""
Your previous JSON was invalid or schema-incompatible.
Output ONLY a valid JSON object that conforms to this JSON Schema:
{schema_hint}

Previous content:
{last_json_text}
"""
