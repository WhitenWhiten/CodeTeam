# core/llm_openai.py
from __future__ import annotations
import os, json, asyncio, time, re
from typing import Any, Dict, Optional
import jsonschema
from core.schemas import SDS_SCHEMA, UPDATE_REASON_SCHEMA  # 如需也可传入自定义schema

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

class OpenAILLM:
    def __init__(self, model: str = "gpt-4o", temperature: float = 0.2, max_tokens: int = 4000, base_url: Optional[str] = None, api_key: Optional[str] = None):
        assert OpenAI is not None, "Please `pip install openai`>=1.0"
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        self.client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def text(self, prompt: str) -> str:
        # 简单封装；你可以添加重试策略
        for attempt in range(3):
            try:
                resp = await asyncio.to_thread(self.client.chat.completions.create,
                    model=self.model,
                    temperature=self.temperature,
                    messages=[{"role":"system","content":"You are a senior software engineer."},
                              {"role":"user","content":prompt}],
                )
                return resp.choices[0].message.content or ""
            except Exception as e:
                if attempt == 2: raise
                await asyncio.sleep(1.5 * (attempt+1))
        return ""

    async def structured_json(self, prompt: str, schema: str | Dict[str, Any] | None = None, max_retries: int = 3) -> Dict[str, Any]:
        # 使用 response_format 强制 JSON，再做 schema 校验与纠错
        schema_dict = None
        if isinstance(schema, dict):
            schema_dict = schema
        elif isinstance(schema, str):
            if schema.upper() == "SDS":
                schema_dict = SDS_SCHEMA
            elif schema.upper() == "CTO_DECISION":
                schema_dict = {"type":"object","required":["chosen_index"],"properties":{"chosen_index":{"type":"number"},"rationale":{"type":"string"}}}
            elif schema.upper() == "UPDATE_REASON":
                schema_dict = UPDATE_REASON_SCHEMA

        content = await self._gen_json_once(prompt)
        parsed = self._safe_parse_json(content)
        if schema_dict:
            ok, errs = self._validate(parsed, schema_dict)
            if ok:
                return parsed
        else:
            if parsed is not None:
                return parsed

        # 纠错重试
        last_msg = content
        for i in range(max_retries):
            repair_prompt = self._build_repair_prompt(last_msg, schema_dict)
            content = await self._gen_json_once(repair_prompt)
            parsed = self._safe_parse_json(content)
            if schema_dict:
                ok, errs = self._validate(parsed, schema_dict)
                if ok:
                    return parsed
                last_msg = content + f"\n\nSchemaErrors: {errs}"
            else:
                if parsed is not None:
                    return parsed
        raise ValueError("Failed to produce valid structured JSON after retries")

    async def files(self, prompt: str, max_retries: int = 3) -> Dict[str, str]:
        # 期望模型返回 {"path":"content", ...}
        content = await self._gen_json_once(prompt)
        parsed = self._safe_parse_json(content)
        if isinstance(parsed, dict) and all(isinstance(k,str) and isinstance(v,str) for k,v in parsed.items()):
            return parsed
        # 尝试修复
        for i in range(max_retries):
            repair_prompt = f"Please return ONLY a valid JSON object mapping file paths to string contents. Example: {{\"tests/test_x.py\":\"content\"}}. Your previous content:\n{content}"
            content = await self._gen_json_once(repair_prompt)
            parsed = self._safe_parse_json(content)
            if isinstance(parsed, dict) and all(isinstance(k,str) and isinstance(v,str) for k,v in parsed.items()):
                return parsed
        raise ValueError("Failed to produce files JSON")

    async def _gen_json_once(self, prompt: str) -> str:
        resp = await asyncio.to_thread(self.client.chat.completions.create,
            model=self.model,
            temperature=self.temperature,
            response_format={"type":"json_object"},
            messages=[
                {"role":"system","content":"Return ONLY valid minified JSON. Do not include extra commentary."},
                {"role":"user","content":prompt},
            ],
        )
        return resp.choices[0].message.content or ""

    def _safe_parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        # 提取最外层JSON对象
        if not text.strip().startswith("{"):
            # 尝试从文本中截取第一个 { 到最后一个 }
            m1 = text.find("{")
            m2 = text.rfind("}")
            if m1 != -1 and m2 != -1 and m2 > m1:
                text = text[m1:m2+1]
        try:
            return json.loads(text)
        except Exception:
            return None

    def _validate(self, obj: Any, schema: Dict[str, Any]) -> tuple[bool, str]:
        try:
            jsonschema.validate(obj, schema)
            return True, ""
        except jsonschema.ValidationError as e:
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