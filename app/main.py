from __future__ import annotations
import argparse
import asyncio
import json
import sys
from pathlib import Path

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.bootstrap import bootstrap
from core.contracts import to_jsonable
from core.requirements_preprocessor import load_requirements_text, preprocess_requirements
from orchestrator.workflow_async import MultiAgentCodegenWorkflowAsync


def parser():
    cli = argparse.ArgumentParser(description='Run CodeTeam Python repository generation and validation.')
    cli.add_argument('--config', help='JSON configuration file; environment and CLI override its values')
    cli.add_argument('--resume', help='Existing run artifacts directory containing checkpoint.json')
    cli.add_argument('--question')
    cli.add_argument('--requirements-file')
    cli.add_argument('--workspace')
    cli.add_argument('--artifacts-dir')
    cli.add_argument('--provider', choices=['mock', 'openai'])
    cli.add_argument('--model')
    cli.add_argument('--base-url')
    cli.add_argument('--architects', type=int)
    cli.add_argument('--max-rounds', type=int)
    cli.add_argument('--max-tokens', type=int, help='Total run token accounting limit')
    cli.add_argument('--max-calls', type=int)
    cli.add_argument('--max-seconds', type=float)
    cli.add_argument('--git', action=argparse.BooleanOptionalAction, default=None)
    cli.add_argument('--rag', action=argparse.BooleanOptionalAction, default=None)
    return cli


async def amain(argv=None):
    args = parser().parse_args(argv)
    targets = {'question': 'user_question', 'requirements_file': 'requirements_file',
               'workspace': 'workspace', 'artifacts_dir': 'artifacts_dir', 'resume': 'resume_from',
               'provider': 'llm.provider', 'model': 'llm.model', 'base_url': 'llm.base_url',
               'architects': 'architects', 'max_rounds': 'max_rounds', 'max_tokens': 'max_token_budget',
               'max_calls': 'max_model_calls', 'max_seconds': 'max_wall_clock_seconds',
               'git': 'git.enabled', 'rag': 'rag.enabled'}
    config_path = args.config
    if args.resume and not config_path:
        config_path = str(Path(args.resume) / 'effective_config.json')
    ctx = None
    try:
        cfg = load_config(config_path, {target: getattr(args, name) for name, target in targets.items()})
        if args.resume and args.question is None and args.requirements_file is None:
            saved = json.loads((Path(args.resume) / 'checkpoint.json').read_text(encoding='utf-8'))
            question = saved['question']
        else:
            question = load_requirements_text(cfg.requirements_file, cfg.user_question)
            if cfg.preprocess_requirements:
                question = preprocess_requirements(question)
        if not question.strip():
            raise ValueError('Requirements must not be empty')
        ctx = bootstrap(cfg)
        result = await MultiAgentCodegenWorkflowAsync(ctx).run(question)
        print(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2))
        return 0 if result.success else 1
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({'status': 'error', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        close = getattr(ctx.llm, 'close', None) if ctx else None
        if close:
            await close()


def main(argv=None):
    try:
        return asyncio.run(amain(argv))
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
