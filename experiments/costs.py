"""Cost exports keep measured usage distinct from budget reservations."""
from pathlib import Path
from experiments.common import read_json, write_json

def cost_report(experiment_dir, input_price=None, output_price=None):
    if any(p is not None and p < 0 for p in (input_price, output_price)):
        raise ValueError('Token prices must be nonnegative USD per million tokens')
    root = Path(experiment_dir).resolve()
    plan = read_json(root / 'plan.json')
    rows = []
    for job in plan['jobs']:
        run = root / 'runs' / job['run_id']
        result = read_json(run / 'result.json')
        records = [read_json(p) for p in sorted(run.glob('attempt-*/runtime/model_calls/*.json'))]
        usage = result['generation'].get('usage', {})
        complete = len(records) == usage.get('calls', 0) and all(r.get('token_breakdown_complete') for r in records)
        roles = {}
        for record in records:
            group = roles.setdefault(record.get('role', 'unattributed'), {'calls': 0, 'known_input_tokens': 0,
                'known_output_tokens': 0, 'reported_tokens': 0, 'estimated_tokens': 0, 'missing_breakdown_calls': 0,
                'model_latency_seconds': 0.0})
            group['calls'] += 1
            group['known_input_tokens'] += record.get('input_tokens') or 0
            group['known_output_tokens'] += record.get('output_tokens') or 0
            group['reported_tokens'] += record.get('reported_total_tokens') or 0
            group['estimated_tokens'] += record['tokens'] if record['usage_source'] == 'conservative_reservation' else 0
            group['missing_breakdown_calls'] += int(not record.get('token_breakdown_complete'))
            group['model_latency_seconds'] += record['elapsed_seconds']
        inputs = sum(g['known_input_tokens'] for g in roles.values())
        outputs = sum(g['known_output_tokens'] for g in roles.values())
        usd = (inputs * input_price + outputs * output_price) / 1e6 if complete and input_price is not None and output_price is not None else None
        row = {'run_id': job['run_id'], **result['identity'], 'status': result['generation']['status'],
               'usage': usage, 'roles': roles, 'token_breakdown_complete': complete,
               'input_tokens': inputs if complete else None, 'output_tokens': outputs if complete else None,
               'wall_time': result['generation'].get('timing'), 'model_call_log_complete': len(records) == usage.get('calls', 0),
               'monetary_equivalent_usd': usd, 'prices_usd_per_million': {'input': input_price, 'output': output_price},
               'gpu_hours': None}
        checkpoint = Path(result['attempt']) / 'runtime/checkpoint.json'
        if checkpoint.exists():
            saved = read_json(checkpoint)
            row['remaining_files'] = sorted({s['path'] for s in saved['chosen_sds']['file_specs']} - set(saved['completed']))
        else:
            row['remaining_files'] = None
        rows.append(row)
    write_json(root / 'costs.json', rows)
    return rows
