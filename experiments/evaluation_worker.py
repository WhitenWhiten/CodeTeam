"""Stdlib-only bridge, executed in the official tool's Python environment."""
import json
import logging
import runpy
import sys
from pathlib import Path

def main(request):
    cfg = request['config']
    checkout = Path(cfg['checkout']).resolve()
    output = Path(request['output'])
    if request['kind'] == 'sketchbleu':
        output_jsonl = output.with_suffix('.jsonl')
        if output_jsonl.exists():
            raise ValueError('Official metric output already exists')
        sys.path.insert(0, str(checkout / 'validation/evaluation_scripts/codebleu'))
        sys.argv = ['get_metric.py', '--pred', request['workspace'], '--ref', cfg['reference'], '--metric_file', str(output_jsonl)]
        runpy.run_path(str(checkout / 'validation/evaluation_scripts/batch_eval/get_metric.py'), run_name='__main__')
        records = [json.loads(line) for line in output_jsonl.read_text(encoding='utf-8').splitlines() if line.strip()]
        if len(records) != 1:
            raise ValueError('Expected exactly one official metric record')
        raw = records[0]
    else:
        sys.path.insert(0, str(checkout))
        import test_data_service
        from openhands.post_processor import post_process_task
        test_data_service.read_all_test_data()
        tasks = [t for t in test_data_service.test_data_list if t.proName == cfg['project']]
        if len(tasks) != 1:
            raise ValueError('Official benchmark project must resolve to exactly one task')
        raw = post_process_task(request['task_uuid'], request['workspace'], tasks[0], logging.getLogger('codeteam.external'))
    output.write_text(json.dumps(raw, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')

if __name__ == '__main__':
    main(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
