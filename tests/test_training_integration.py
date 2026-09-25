"""Real CPU optimization and reload; optional training dependencies, no downloads."""
import json
import math
from pathlib import Path
import pytest
transformers = pytest.importorskip('transformers')
pytest.importorskip('peft')
pytest.importorskip('accelerate')
import torch
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast
from experiments.common import read_json, write_json
from training.checkpoint import evaluate_checkpoint, verify_checkpoint
from training.prepare import prepare
from training.protocol import METHODS
from training.train import train
from test_training import dataset_config


def setup_training(tmp_path, mode='full'):
    torch.set_num_threads(1)
    vocab = {t: i for i, t in enumerate(['[PAD]', '[UNK]', '[EOS]', 'user', 'assistant', ':', 'Build', 'repository', '0', '1', '2', '3', 'answer'])}
    raw = Tokenizer(WordLevel(vocab, unk_token='[UNK]')); raw.pre_tokenizer = Whitespace()
    tok = PreTrainedTokenizerFast(tokenizer_object=raw, pad_token='[PAD]', unk_token='[UNK]', eos_token='[EOS]')
    tok.chat_template = "{% for message in messages %}{{ message['role'] + ' : ' + message['content'] + ' ' }}{% endfor %}{% if add_generation_prompt %}{{ 'assistant : ' }}{% endif %}"
    base = tmp_path / 'base'
    tok.save_pretrained(base)
    torch.manual_seed(71)
    model = GPT2LMHeadModel(GPT2Config(vocab_size=len(vocab), n_positions=128, n_embd=16, n_layer=1, n_head=2,
        bos_token_id=2, eos_token_id=2, pad_token_id=0))
    model.save_pretrained(base)
    preparation = dataset_config(tmp_path)
    config = read_json(preparation); config['tokenizer'] = 'base'; write_json(preparation, config)
    prepare(preparation)
    training = tmp_path / 'train.json'
    write_json(training, {'prepared_dir': 'prepared', 'output_dir': 'trained', 'model': 'base',
        'mode': mode, 'dtype': 'float32', 'epochs': 1, 'gradient_accumulation_steps': 1,
        'expected_global_batch_size': 1, 'gradient_checkpointing': False, 'learning_rate': 0.001,
        'lora_rank': 2, 'lora_alpha': 4, 'target_modules': ['c_attn', 'c_proj']})
    return training, model


def test_three_independent_checkpoints_optimize_and_reload(tmp_path):
    config, base = setup_training(tmp_path)
    outputs = []
    for condition in METHODS:
        result = train(config, condition)
        assert result['status'] == 'completed' and result['global_step'] == 3
        assert result['attempts'][0]['allocated_gpu_hours'] == 0
        checkpoint = Path(result['checkpoint'])
        assert verify_checkpoint(checkpoint)['condition'] == condition
        validation = evaluate_checkpoint(checkpoint, tmp_path / 'prepared')
        assert math.isfinite(validation['token_weighted_loss']) and validation['supervised_tokens'] > 0
        restored = GPT2LMHeadModel.from_pretrained(checkpoint)
        assert not torch.equal(base.transformer.wte.weight, restored.transformer.wte.weight)
        outputs.append(checkpoint)
    assert len(set(outputs)) == 3
    with pytest.raises(ValueError, match='already exists'): train(config, 'vanilla')
    original = read_json(config); original['learning_rate'] = 0.02; write_json(config, original)
    with pytest.raises(ValueError, match='protocol changed'): train(config, 'codes')


def test_lora_adapter_is_saved_and_reloaded(tmp_path):
    config, _ = setup_training(tmp_path, 'lora')
    result = train(config, 'codeteam')
    checkpoint = Path(result['checkpoint'])
    assert (checkpoint / 'adapter_model.safetensors').exists()
    assert evaluate_checkpoint(checkpoint, tmp_path / 'prepared')['instances'] == 1
    with (checkpoint / 'adapter_config.json').open('a') as handle: handle.write(' ')
    with pytest.raises(ValueError, match='changed'): verify_checkpoint(checkpoint)


def test_batch_arithmetic_and_cuda_requirements_fail_before_training(tmp_path):
    config, _ = setup_training(tmp_path)
    cfg = read_json(config); cfg['expected_global_batch_size'] = 64; write_json(config, cfg)
    with pytest.raises(ValueError, match='Global batch mismatch'): train(config, 'vanilla')
    cfg['expected_global_batch_size'] = 1; cfg['mode'] = 'qlora'; write_json(config, cfg)
    if not torch.cuda.is_available():
        with pytest.raises(ValueError, match='CUDA'): train(config, 'vanilla')


def test_training_resumes_saved_optimizer_after_final_write_failure(tmp_path, monkeypatch):
    config, _ = setup_training(tmp_path)
    original = transformers.Trainer.save_model
    def interrupted(trainer, output_dir=None, *args, **kwargs):
        if output_dir and Path(output_dir).name == 'final':
            raise RuntimeError('simulated final publication interruption')
        return original(trainer, output_dir, *args, **kwargs)
    monkeypatch.setattr(transformers.Trainer, 'save_model', interrupted)
    with pytest.raises(RuntimeError, match='publication interruption'): train(config, 'vanilla')
    checkpoint = tmp_path / 'trained/vanilla/checkpoint-3'
    assert (checkpoint / 'trainer_state.json').is_file()
    assert (checkpoint / 'optimizer.pt').is_file()
    monkeypatch.setattr(transformers.Trainer, 'save_model', original)
    result = train(config, 'vanilla', checkpoint)
    assert result['status'] == 'completed'
    assert [a['status'] for a in result['attempts']] == ['failed', 'completed']
    assert verify_checkpoint(result['checkpoint'])['condition'] == 'vanilla'
