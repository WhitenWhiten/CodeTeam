"""Compatibility module: both command-line entrypoints use the same runner."""
from app.main import amain, main

if __name__ == '__main__':
    raise SystemExit(main())
