from __future__ import annotations
from collections import Counter
from pathlib import Path
import json
import re
from experiments.common import digest, files_digest, read_json, write_json
from training.protocol import METHODS, PrepareConfig, Sample

def load_tokenizer(name, revision=None):
    from transformers import AutoTokenizer
    if not Path(name).exists() and (not revision or not re.fullmatch('[a-fA-F0-9]{40}', revision)):
        raise ValueError('Remote tokenizers require an immutable 40-character commit revision')
    tokenizer = AutoTokenizer.from_pretrained(name, revision=revision, trust_remote_code=False)
    if not tokenizer.chat_template:
        raise ValueError('Tokenizer must have an explicit chat template')
    return tokenizer

def encode_sample(sample, tokenizer, max_length):
    messages = [m.model_dump() for m in sample.messages]
    prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False)
    if full[:len(prompt)] != prompt:
        raise ValueError('Chat template does not preserve the prompt prefix')
    if len(full) > max_length:
        raise ValueError('sequence_too_long')
    if len(full) <= len(prompt):
        raise ValueError('empty_supervised_target')
    return {'sample_id': sample.sample_id, 'repository_id': sample.repository_id, 'stage': sample.stage,
            'input_ids': full, 'attention_mask': [1] * len(full),
            'labels': [-100] * len(prompt) + full[len(prompt):],
            'tokens': len(full), 'supervised_tokens': len(full) - len(prompt),
            'teacher': sample.teacher, 'evidence': sample.evidence}

def prepare(config_path, tokenizer=None):
    config_path = Path(config_path).resolve()
    cfg = PrepareConfig.model_validate(read_json(config_path))
    root = (config_path.parent / cfg.output_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError('Prepared output must be empty; preserve previous dataset versions')
    root.mkdir(parents=True, exist_ok=True)
    name = str((config_path.parent / cfg.tokenizer).resolve()) if (config_path.parent / cfg.tokenizer).exists() else cfg.tokenizer
    tokenizer = tokenizer or load_tokenizer(name, cfg.tokenizer_revision)
    pools = {m: {} for m in METHODS}
    rejected = Counter()
    source_hashes = {}
    seen_ids, seen_instances, seen_contents = set(), set(), {}
    raw_samples = []
    for method in METHODS:
        path = (config_path.parent / cfg.datasets[method]).resolve()
        source_hashes[method] = digest(path.read_text(encoding='utf-8-sig'))
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if not line.strip():
                continue
            sample = Sample.model_validate(json.loads(line))
            if sample.method != method:
                raise ValueError('Dataset method does not match the declared condition')
            key = (method, sample.sample_id)
            if key in seen_ids:
                raise ValueError('Duplicate sample identifier')
            seen_ids.add(key)
            raw_samples.append(sample)
    for sample in sorted(raw_samples, key=lambda s: (s.repository_id, s.method, s.sample_id)):
        fingerprint = digest([m.model_dump() for m in sample.messages])
        if not sample.accepted:
            rejected['not_quality_accepted'] += 1; continue
        if sample.repository_id in cfg.exclude_repositories or fingerprint in cfg.exclude_content_sha256:
            rejected['contamination_exclusion'] += 1; continue
        previous = seen_contents.get(fingerprint)
        if previous is not None and previous != sample.repository_id:
            rejected['cross_repository_duplicate'] += 1; continue
        content_key = (sample.method, fingerprint)
        if content_key in seen_instances:
            rejected['duplicate_instance'] += 1; continue
        seen_instances.add(content_key)
        seen_contents[fingerprint] = sample.repository_id
        try:
            encoded = encode_sample(sample, tokenizer, cfg.max_sequence_length)
        except ValueError as exc:
            if str(exc) not in {'sequence_too_long', 'empty_supervised_target'}:
                raise
            rejected[str(exc)] += 1; continue
        pools[sample.method].setdefault(sample.repository_id, []).append(encoded)
    common = set.intersection(*(set(pool) for pool in pools.values()))
    if len(common) < 2:
        raise ValueError('At least two shared source repositories are needed for repository-level validation')
    ordered_repos = sorted(common, key=lambda r: digest([cfg.seed, r]))
    n_validation = min(len(common) - 1, max(1, round(len(common) * cfg.validation_fraction)))
    split = {r: 'validation' if i < n_validation else 'train' for i, r in enumerate(ordered_repos)}
    selected = {m: {'train': [], 'validation': []} for m in METHODS}
    for repository in ordered_repos:
        available = min(len(pools[m][repository]) for m in METHODS)
        count = cfg.samples_per_repository or available
        if count > available:
            raise ValueError(f'Not enough independent samples for repository {repository}')
        for method in METHODS:
            candidates = sorted(pools[method][repository], key=lambda r: digest([cfg.seed, r['sample_id']]))
            selected[method][split[repository]].extend(candidates[:count])
    counts = {m: {s: {'instances': len(rows), 'tokens': sum(r['tokens'] for r in rows),
                      'supervised_tokens': sum(r['supervised_tokens'] for r in rows),
                      'repositories': sorted({r['repository_id'] for r in rows})}
                  for s, rows in partitions.items()} for m, partitions in selected.items()}
    token_differences = {}
    for partition in ('train', 'validation'):
        tokens = [counts[m][partition]['tokens'] for m in METHODS]
        token_differences[partition] = (max(tokens) - min(tokens)) / max(tokens)
    matched = all(v <= cfg.token_tolerance_fraction for v in token_differences.values())
    audit = {'version': 1, 'config': cfg.model_dump(), 'source_sha256': source_hashes,
             'split': split, 'counts': counts, 'rejected': dict(rejected), 'input_instances': len(raw_samples),
             'excluded_nonshared_repositories': sorted(set.union(*(set(p) for p in pools.values())) - common),
             'relative_token_differences': token_differences, 'matched': matched,
             'token_definition': 'nonpadding chat-template input plus assistant target; prompt labels masked',
             'duplicate_policy': 'exact message-content hash across repositories; within-condition deduplication'}
    write_json(root / 'matching_report.json', audit)
    if not matched:
        raise ValueError('Token volumes do not meet the declared tolerance; see matching_report.json. Supply matched examples; padding is not counted as data.')
    for method, partitions in selected.items():
        for partition, rows in partitions.items():
            (root / f'{method}.{partition}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    tokenizer.save_pretrained(str(root / 'tokenizer'))
    files = files_digest(root)
    write_json(root / 'manifest.json', {'version': 1, 'files': files, 'sha256': digest(files), 'matched': True})
    return audit

def verify_prepared(root):
    root = Path(root).resolve()
    manifest = read_json(root / 'manifest.json')
    actual = files_digest(root); actual.pop('manifest.json', None)
    if not manifest['matched'] or actual != manifest['files'] or digest(actual) != manifest['sha256']:
        raise ValueError('Prepared dataset changed or matching was not completed')
    report = read_json(root / 'matching_report.json')
    partitions = {name: {r for r, part in report['split'].items() if part == name} for name in ('train', 'validation')}
    if not partitions['train'] or not partitions['validation'] or partitions['train'] & partitions['validation']:
        raise ValueError('Invalid repository split')
    return manifest
