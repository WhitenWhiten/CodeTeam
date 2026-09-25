from __future__ import annotations
from typing import Literal
from pydantic import Field, model_validator
from app.config import ConfigModel

METHODS = ('vanilla', 'codes', 'codeteam')

class Message(ConfigModel):
    role: Literal['system', 'user', 'assistant']
    content: str = Field(min_length=1)

class Sample(ConfigModel):
    sample_id: str
    repository_id: str
    method: Literal['vanilla', 'codes', 'codeteam']
    stage: str
    teacher: str = Field(min_length=1)
    messages: list[Message] = Field(min_length=2)
    accepted: bool = False
    evidence: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def target_message(self):
        if self.messages[-1].role != 'assistant' or self.messages[-2].role != 'user':
            raise ValueError('Each sample ends with a user prompt and assistant target')
        if not self.repository_id.strip() or not self.sample_id.strip():
            raise ValueError('Repository and sample identifiers must not be empty')
        return self

class PrepareConfig(ConfigModel):
    datasets: dict[str, str]
    output_dir: str
    tokenizer: str
    tokenizer_revision: str | None = None
    seed: int = Field(default=42, ge=0)
    validation_fraction: float = Field(default=0.05, gt=0, lt=1)
    max_sequence_length: int = Field(default=32768, ge=8)
    samples_per_repository: int | None = Field(default=None, ge=1)
    token_tolerance_fraction: float = Field(default=0, ge=0, lt=1)
    exclude_repositories: list[str] = Field(default_factory=list)
    exclude_content_sha256: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def methods(self):
        if set(self.datasets) != set(METHODS):
            raise ValueError('Supply independent vanilla, codes and codeteam datasets')
        return self

class TrainConfig(ConfigModel):
    prepared_dir: str
    output_dir: str
    model: str
    model_revision: str | None = None
    mode: Literal['full', 'lora', 'qlora'] = 'qlora'
    dtype: Literal['float32', 'bfloat16', 'float16'] = 'bfloat16'
    epochs: int = Field(default=3, ge=1)
    learning_rate: float = Field(default=0.0001, gt=0)
    weight_decay: float = Field(default=0.1, ge=0)
    warmup_ratio: float = Field(default=0.03, ge=0, lt=1)
    max_grad_norm: float = Field(default=1.0, gt=0)
    micro_batch_size: int = Field(default=1, ge=1)
    gradient_accumulation_steps: int = Field(default=16, ge=1)
    expected_global_batch_size: int | None = Field(default=None, ge=1)
    gradient_checkpointing: bool = True
    lora_rank: int = Field(default=64, ge=1)
    lora_alpha: int = Field(default=128, ge=1)
    lora_dropout: float = Field(default=0.05, ge=0, lt=1)
    target_modules: list[str] = Field(default_factory=lambda: ['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj'])
    deepspeed: str | None = None
    attention_implementation: str = 'sdpa'
    seed: int = Field(default=42, ge=0)
