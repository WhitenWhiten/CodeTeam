"""Export accepted CodeTeam targets without inventing other methods' supervision."""
import ast
import json
from pathlib import Path
from core.schemas import validate_sds, validate_qa_test_bundle
from core.text_utils import strip_code_fences
from experiments.common import digest, read_json, verify_artifact, write_json
from training.protocol import Sample

def export_runtime(experiment_dir, repositories_file, output_file):
    root = Path(experiment_dir).resolve()
    repositories = read_json(repositories_file)
    plan = read_json(root / 'plan.json')
    if set(repositories) != {j['task_id'] for j in plan['jobs']}:
        raise ValueError('Map every task to its true source repository_id')
    output = Path(output_file).resolve()
    if output.exists():
        raise ValueError('Sample export exists; choose a new path')
    samples, rejected = [], []
    for job in plan['jobs']:
        run = root / 'runs' / job['run_id']
        result = read_json(run / 'result.json')
        if result['generation']['status'] != 'success' or not result['artifact']:
            rejected.append({'run_id': job['run_id'], 'reason': 'run_not_qa_accepted'}); continue
        verify_artifact(result['artifact'])
        runtime = Path(result['attempt']) / 'runtime'
        for file in sorted(run.glob('attempt-*/runtime/model_calls/*.json')):
            record = read_json(file)
            call_runtime = file.parent.parent
            attempt_name = call_runtime.parent.name
            reason = None
            content = record.get('output')
            content = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            role = record.get('role')
            if record.get('provider') == 'mock' or record.get('error') or not content or not record.get('messages'):
                reason = 'mock_error_or_missing_target'
            else:
                try:
                    if role == 'Architect':
                        validate_sds(json.loads(strip_code_fences(content)))
                    elif role == 'CTO':
                        decision = json.loads(strip_code_fences(content))
                        candidates = read_json(call_runtime / 'planning/architect_candidates.json')
                        if type(decision['chosen_index']) is not int or not 0 <= decision['chosen_index'] < len(candidates) or not decision.get('rationale'):
                            raise ValueError('Invalid CTO decision')
                    elif role == 'Developer':
                        if record['file_path'] not in result['artifact']['files']:
                            raise ValueError('Target path is outside the accepted source snapshot')
                        target = Path(result['artifact']['path']) / record['file_path']
                        clean = strip_code_fences(content)
                        if target.suffix == '.py': ast.parse(clean)
                        if not target.is_file() or target.read_text(encoding='utf-8').strip() != clean.strip():
                            raise ValueError('Target is not the final accepted file')
                    elif role == 'QA':
                        bundle = json.loads(strip_code_fences(content)); validate_qa_test_bundle(bundle)
                        accepted = read_json(runtime / 'qa/test_bundle.json')
                        if {p: strip_code_fences(c) for p, c in bundle['tests'].items()} != accepted['tests']:
                            raise ValueError('Target is not the accepted QA bundle')
                        for code in bundle['tests'].values(): ast.parse(strip_code_fences(code))
                    else:
                        raise ValueError('Unattributed model call')
                except Exception as exc:
                    reason = f'invalid_target: {type(exc).__name__}: {exc}'
            if reason:
                rejected.append({'run_id': job['run_id'], 'call': record['call'], 'reason': reason}); continue
            sample = {'sample_id': f"{job['run_id']}-{attempt_name}-{record['call']}", 'repository_id': repositories[job['task_id']],
                'method': 'codeteam', 'stage': record['stage'], 'teacher': record.get('response_model') or record['model'],
                'messages': record['messages'] + [{'role': 'assistant', 'content': content}], 'accepted': True,
                'evidence': {'run_id': job['run_id'], 'attempt': attempt_name, 'call': record['call'], 'artifact_sha256': result['artifact']['sha256'],
                             'quality_control': 'role contract plus final QA-accepted run; developer targets match final source'}}
            samples.append(Sample.model_validate(sample).model_dump())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(''.join(json.dumps(s, ensure_ascii=False) + '\n' for s in samples), encoding='utf-8')
    audit = {'accepted': len(samples), 'rejected': rejected, 'sha256': digest(samples)}
    write_json(output.with_suffix('.audit.json'), audit)
    return audit
