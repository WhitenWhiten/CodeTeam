import argparse
import json
from training.protocol import METHODS


def main(argv=None):
    parser = argparse.ArgumentParser(description='Independent, matched CodeTeam SFT experiments')
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export-runtime')
    export.add_argument('experiment_dir'); export.add_argument('repositories_file'); export.add_argument('output_file')
    preparation = commands.add_parser('prepare'); preparation.add_argument('config')
    fit = commands.add_parser('train'); fit.add_argument('config'); fit.add_argument('--condition', choices=METHODS, required=True)
    fit.add_argument('--resume', help='Explicit Trainer checkpoint from the same condition')
    verify = commands.add_parser('verify-checkpoint'); verify.add_argument('checkpoint')
    evaluate = commands.add_parser('evaluate-checkpoint'); evaluate.add_argument('checkpoint')
    evaluate.add_argument('--prepared-dir', required=True); evaluate.add_argument('--output')
    evaluate.add_argument('--device', default='cpu')
    args = parser.parse_args(argv)
    if args.command == 'export-runtime':
        from training.export import export_runtime
        result = export_runtime(args.experiment_dir, args.repositories_file, args.output_file)
    elif args.command == 'prepare':
        from training.prepare import prepare
        result = prepare(args.config)
    elif args.command == 'train':
        from training.train import train
        result = train(args.config, args.condition, args.resume)
    elif args.command == 'verify-checkpoint':
        from training.checkpoint import verify_checkpoint
        result = verify_checkpoint(args.checkpoint)
    else:
        from training.checkpoint import evaluate_checkpoint
        result = evaluate_checkpoint(args.checkpoint, args.prepared_dir, args.output, args.device)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__': main()
