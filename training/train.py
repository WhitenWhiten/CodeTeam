"""Three independent HF/PEFT trainings under one immutable comparison protocol."""
from __future__ import annotations
import importlib.metadata
import json
import math
import os
from pathlib import Path
import time
import traceback
from experiments.common import digest, files_digest, read_json, write_json
from training.prepare import verify_prepared
from training.protocol import METHODS, TrainConfig


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


class TokenizedDataset:
    def __init__(self, path):
        self.rows = read_rows(path)
        if not self.rows:
            raise ValueError('Training and validation partitions must both be nonempty')

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        return {key: self.rows[index][key] for key in ('input_ids', 'attention_mask', 'labels')}


class SupervisedCollator:
    def __init__(self, pad_token_id):
        self.pad_token_id = pad_token_id

    def __call__(self, rows):
        import torch
        length = max(len(row['input_ids']) for row in rows)
        pads = {'input_ids': self.pad_token_id, 'attention_mask': 0, 'labels': -100}
        return {key: torch.tensor([row[key] + [pad] * (length - len(row[key])) for row in rows], dtype=torch.long)
                for key, pad in pads.items()}


def load_config(path):
    path = Path(path).resolve()
    cfg = TrainConfig.model_validate(read_json(path))
    values = cfg.model_dump()
    for field in ('prepared_dir', 'output_dir', 'deepspeed'):
        if values[field]: values[field] = str((path.parent / values[field]).resolve())
    candidate = path.parent / cfg.model
    if candidate.exists():
        values['model'] = str(candidate.resolve())
    elif not cfg.model_revision or len(cfg.model_revision) != 40 or any(c not in '0123456789abcdef' for c in cfg.model_revision.lower()):
        raise ValueError('Remote base models require an immutable 40-character commit revision')
    return TrainConfig.model_validate(values)


def preflight(cfg, world_size):
    import torch
    manifest = verify_prepared(cfg.prepared_dir)
    batch = cfg.micro_batch_size * cfg.gradient_accumulation_steps * world_size
    if cfg.expected_global_batch_size is not None and batch != cfg.expected_global_batch_size:
        raise ValueError(f'Global batch mismatch: {world_size} GPUs/processes x {cfg.micro_batch_size} x {cfg.gradient_accumulation_steps} = {batch}, expected {cfg.expected_global_batch_size}')
    if cfg.mode == 'qlora':
        if not torch.cuda.is_available(): raise ValueError('QLoRA requires a CUDA device and bitsandbytes')
        importlib.metadata.version('bitsandbytes')
    if cfg.dtype != 'float32' and not torch.cuda.is_available():
        raise ValueError('CPU verification requires dtype=float32; GPU precision must be explicitly supported')
    if cfg.dtype == 'bfloat16' and not torch.cuda.is_bf16_supported():
        raise ValueError('The selected CUDA device does not support bfloat16')
    if cfg.deepspeed:
        importlib.metadata.version('deepspeed')
        if cfg.mode == 'qlora' and read_json(cfg.deepspeed).get('zero_optimization', {}).get('stage') == 3:
            raise ValueError('QLoRA + ZeRO-3 is not validated by this trainer. Use QLoRA DDP or nonquantized LoRA/full ZeRO-3; report the chosen configuration.')
    return manifest, batch


def train(config_path, condition, resume=None):
    if condition not in METHODS: raise ValueError(f'Unknown training condition: {condition}')
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments, set_seed
    cfg = load_config(config_path)
    world = int(os.environ.get('WORLD_SIZE', '1'))
    rank = int(os.environ.get('RANK', '0'))
    manifest, batch = preflight(cfg, world)
    root = Path(cfg.output_dir)
    output = root / condition
    prepared = Path(cfg.prepared_dir)
    protocol = {'version': 1, 'config': cfg.model_dump(), 'prepared_sha256': manifest['sha256'],
                'trainer_source_sha256': digest(files_digest(Path(__file__).parent)),
                'world_size': world, 'global_batch_size': batch,
                'base_identity': files_digest(cfg.model) if Path(cfg.model).is_dir() else {'model': cfg.model, 'revision': cfg.model_revision},
                'deepspeed_config': read_json(cfg.deepspeed) if cfg.deepspeed else None,
                'libraries': {p: importlib.metadata.version(p) for p in ('torch', 'transformers', 'peft', 'accelerate')}}
    protocol['sha256'] = digest(protocol)
    # A common parent protocol prevents accidental per-method optimization changes.
    previous = root / 'training_protocol.json'
    if previous.exists() and read_json(previous) != protocol:
        raise ValueError('Training protocol changed; choose a new output directory for all conditions')
    resumed = None
    if resume:
        resumed = Path(resume).resolve()
        if not resumed.is_relative_to(output.resolve()) or not (resumed / 'trainer_state.json').exists():
            raise ValueError('Resume requires a Trainer checkpoint from this exact condition')
        if not previous.exists(): raise ValueError('Resume requires the original training protocol')
    elif output.exists() and any(output.iterdir()):
        raise ValueError('Condition output already exists; use an explicit --resume checkpoint or a new protocol directory')
    if (output / 'final' / 'checkpoint_manifest.json').exists():
        raise ValueError('This condition already has a completed independent checkpoint')
    args = TrainingArguments(output_dir=str(output), num_train_epochs=cfg.epochs,
        per_device_train_batch_size=cfg.micro_batch_size, per_device_eval_batch_size=cfg.micro_batch_size,
        gradient_accumulation_steps=cfg.gradient_accumulation_steps,
        learning_rate=cfg.learning_rate, weight_decay=cfg.weight_decay, warmup_ratio=cfg.warmup_ratio,
        max_grad_norm=cfg.max_grad_norm, lr_scheduler_type='cosine', optim='adamw_torch',
        eval_strategy='epoch', save_strategy='epoch', save_total_limit=2,
        load_best_model_at_end=True, metric_for_best_model='eval_loss', greater_is_better=False,
        gradient_checkpointing=cfg.gradient_checkpointing,
        gradient_checkpointing_kwargs={'use_reentrant': False},
        bf16=cfg.dtype == 'bfloat16', fp16=cfg.dtype == 'float16', use_cpu=not torch.cuda.is_available(),
        seed=cfg.seed, data_seed=cfg.seed, report_to=[], logging_steps=1, disable_tqdm=True,
        dataloader_num_workers=0, deepspeed=cfg.deepspeed, ddp_find_unused_parameters=False)
    # TrainingArguments initializes distributed execution. Only rank zero writes shared metadata.
    def barrier():
        if torch.distributed.is_initialized(): torch.distributed.barrier()
    barrier()
    if rank == 0:
        root.mkdir(parents=True, exist_ok=True)
        output.mkdir(parents=True, exist_ok=True)
        if not previous.exists(): write_json(previous, protocol)
    barrier()
    set_seed(cfg.seed)
    started = time.monotonic()
    previous_attempts = read_json(output / 'training_result.json').get('attempts', []) if (output / 'training_result.json').exists() else []
    attempt = {'resume_from_checkpoint': str(resumed) if resumed else None, 'status': 'running'}
    if rank == 0: write_json(output / 'training_result.json', {'condition': condition, 'status': 'running', 'attempts': previous_attempts + [attempt]})
    try:
        tokenizer = AutoTokenizer.from_pretrained(str(prepared / 'tokenizer'), trust_remote_code=False)
        if tokenizer.pad_token_id is None:
            if tokenizer.eos_token_id is None: raise ValueError('Tokenizer needs a padding or EOS token')
            tokenizer.pad_token = tokenizer.eos_token
        dtype = getattr(torch, cfg.dtype)
        kwargs = {'revision': cfg.model_revision, 'trust_remote_code': False, 'dtype': dtype,
                  'attn_implementation': cfg.attention_implementation}
        if cfg.mode == 'qlora':
            from transformers import BitsAndBytesConfig
            kwargs['quantization_config'] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=dtype)
            kwargs['device_map'] = {'': int(os.environ.get('LOCAL_RANK', '0'))}
        model = AutoModelForCausalLM.from_pretrained(cfg.model, **kwargs)
        base_tokenizer = AutoTokenizer.from_pretrained(cfg.model, revision=cfg.model_revision, trust_remote_code=False)
        if tokenizer.get_vocab() != base_tokenizer.get_vocab() or tokenizer.chat_template != base_tokenizer.chat_template:
            raise ValueError('Prepared tokenizer differs from the base tokenizer or chat template')
        if len(tokenizer) > model.get_input_embeddings().num_embeddings:
            raise ValueError('Prepared tokenizer vocabulary differs from the base model; use its original tokenizer')
        if cfg.mode != 'full':
            from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
            if cfg.mode == 'qlora': model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=cfg.gradient_checkpointing)
            model = get_peft_model(model, LoraConfig(task_type='CAUSAL_LM', r=cfg.lora_rank,
                lora_alpha=cfg.lora_alpha, lora_dropout=cfg.lora_dropout, target_modules=cfg.target_modules))
        model.config.use_cache = False
        if torch.cuda.is_available(): torch.cuda.reset_peak_memory_stats()
        trainer = Trainer(model=model, args=args, processing_class=tokenizer,
            train_dataset=TokenizedDataset(prepared / f'{condition}.train.jsonl'),
            eval_dataset=TokenizedDataset(prepared / f'{condition}.validation.jsonl'),
            data_collator=SupervisedCollator(tokenizer.pad_token_id))
        trained = trainer.train(resume_from_checkpoint=str(resumed) if resumed else None)
        final_metrics = trainer.evaluate()
        if not math.isfinite(final_metrics['eval_loss']): raise ValueError('Nonfinite validation loss')
        final = output / 'final'
        trainer.save_model(str(final))
        local_peak = torch.cuda.max_memory_allocated() if torch.cuda.is_available() else 0
        peaks = [local_peak]
        if torch.distributed.is_initialized():
            peaks = [None] * world
            torch.distributed.all_gather_object(peaks, local_peak)
        if rank == 0:
            tokenizer.save_pretrained(str(final))
            files = files_digest(final)
            write_json(final / 'checkpoint_manifest.json', {'version': 1, 'condition': condition,
                'mode': cfg.mode, 'dtype': cfg.dtype, 'model': cfg.model, 'model_revision': cfg.model_revision,
                'base_identity': protocol['base_identity'], 'prepared_sha256': manifest['sha256'],
                'protocol_sha256': protocol['sha256'], 'best_checkpoint': trainer.state.best_model_checkpoint,
                'validation_loss': final_metrics['eval_loss'], 'files': files, 'sha256': digest(files)})
            attempt.update(status='completed', wall_seconds=time.monotonic() - started,
                gpu_count=world if torch.cuda.is_available() else 0, peak_allocated_bytes_per_rank=peaks)
            attempt['allocated_gpu_hours'] = attempt['wall_seconds'] * attempt['gpu_count'] / 3600
            result = {'condition': condition, 'status': 'completed', 'checkpoint': str(final),
                'attempts': previous_attempts + [attempt], 'train_metrics': trained.metrics,
                'validation_metrics': final_metrics, 'global_step': trainer.state.global_step,
                'protocol_sha256': protocol['sha256'],
                'cost_note': 'Allocated GPU hours = active attempt wall time x GPU count; excludes process-death gaps and is not utilization telemetry.'}
            write_json(output / 'training_result.json', result)
        barrier()
        return read_json(output / 'training_result.json')
    except BaseException as exc:
        if rank == 0:
            attempt.update(status='failed', wall_seconds=time.monotonic() - started, error=f'{type(exc).__name__}: {exc}')
            write_json(output / 'training_result.json', {'condition': condition, 'status': 'failed', 'attempts': previous_attempts + [attempt]})
            (output / 'failure.log').write_text(traceback.format_exc(), encoding='utf-8')
        raise
