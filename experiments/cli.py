from __future__ import annotations
import argparse
import asyncio
import json
import sys
from experiments.protocol import make_plan
from experiments.runner import run_experiment
from experiments.evaluation import evaluate

def main(argv=None):
    cli = argparse.ArgumentParser(description='Plan and execute reproducible CodeTeam experiments')
    sub = cli.add_subparsers(dest='command', required=True)
    for name in ('plan', 'run', 'evaluate'):
        p = sub.add_parser(name)
        p.add_argument('manifest')
        if name != 'plan':
            p.add_argument('--resume', action='store_true')
    args = cli.parse_args(argv)
    try:
        if args.command == 'plan':
            result = make_plan(args.manifest)
        else:
            runner = run_experiment if args.command == 'run' else evaluate
            result = asyncio.run(runner(args.manifest, args.resume))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
