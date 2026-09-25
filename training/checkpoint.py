from __future__ import annotations
import math
from pathlib import Path
from experiments.common import digest, files_digest, read_json, write_json
from training.prepare import verify_prepared
from training.train import TokenizedDataset, SupervisedCollator


def verify_checkpoint(path):
    root = Path(path).resolve()
    manifest = read_json(root / 'checkpoint_manifest.json')
    actual = files_digest(root); actual.pop('checkpoint_manifest.json', None)
    if actual != manifest['files'] or digest(actual) != manifest['sha256']:
        raise ValueError('Checkpoint files changed after training')
    required = 'config.json' if manifest['mode'] == 'full' else 'adapter_config.json'
    if required not in actual or not any(p.endswith(('.safetensors', '.bin')) for p in actual):
        raise ValueError('Checkpoint lacks model configuration or weights')
    return manifest


def evaluate_checkpoint(checkpoint, prepared_dir, output=None, device='cpu'):
    """Reload saved weights and measure token-weighted, held-out assistant loss."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    root = Path(checkpoint).resolve()
    meta = verify_checkpoint(root)
    prepared = Path(prepared_dir).resolve()
    if verify_prepared(prepared)['sha256'] != meta['prepared_sha256']:
        raise ValueError('Checkpoint and held-out dataset provenance do not match')
    output = Path(output).resolve() if output else root.parent / 'heldout_validation.json'
    if output.is_relative_to(root): raise ValueError('Validation output must be outside the immutable checkpoint')
    if output.exists(): raise ValueError('Validation report exists; choose a new output path')
    dtype = torch.float32 if device == 'cpu' else getattr(torch, meta['dtype'])
    quantized = meta['mode'] == 'qlora'
    if quantized and (not device.startswith('cuda') or not torch.cuda.is_available()):
        raise ValueError('QLoRA checkpoint validation requires --device cuda and bitsandbytes')
    if meta['mode'] == 'full':
        model = AutoModelForCausalLM.from_pretrained(str(root), dtype=dtype, trust_remote_code=False)
    else:
        from peft import PeftModel
        if Path(meta['model']).is_dir() and files_digest(meta['model']) != meta['base_identity']:
            raise ValueError('Adapter base model has changed')
        kwargs = {}
        if quantized:
            from transformers import BitsAndBytesConfig
            kwargs['quantization_config'] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=dtype)
            kwargs['device_map'] = {'': device}
        model = AutoModelForCausalLM.from_pretrained(meta['model'], revision=meta['model_revision'], dtype=dtype, trust_remote_code=False, **kwargs)
        model = PeftModel.from_pretrained(model, str(root), is_trainable=False)
    if not quantized: model.to(device)
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(str(root), trust_remote_code=False)
    collator = SupervisedCollator(tokenizer.pad_token_id or tokenizer.eos_token_id)
    dataset = TokenizedDataset(prepared / f"{meta['condition']}.validation.jsonl")
    loss_sum, tokens = 0.0, 0
    with torch.inference_mode():
        for row in dataset:
            batch = {k: v.to(device) for k, v in collator([row]).items()}
            n = int((batch['labels'][:, 1:] != -100).sum().item())
            if n == 0: raise ValueError('Validation sample has no supervised next-token targets')
            value = float(model(**batch).loss.item())
            if not math.isfinite(value): raise ValueError('Nonfinite checkpoint validation loss')
            loss_sum += value * n; tokens += n
    loss = loss_sum / tokens
    result = {'condition': meta['condition'], 'checkpoint_sha256': meta['sha256'],
        'prepared_sha256': meta['prepared_sha256'], 'instances': len(dataset), 'supervised_tokens': tokens,
        'token_weighted_loss': loss, 'perplexity': math.exp(loss) if loss < 709 else None,
        'device': device, 'meaning': 'Reloaded checkpoint held-out assistant-token loss; not a repository benchmark score.'}
    write_json(output, result)
    return result
