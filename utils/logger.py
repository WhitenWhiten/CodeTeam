# utils/logger.py
import logging, sys, time
from typing import Optional

def get_logger(name: str = "multiagent", level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    h = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter(fmt="%(asctime)s %(levelname)s %(name)s %(message)s")
    h.setFormatter(fmt)
    logger.addHandler(h)
    return logger

class StageTimer:
    def __init__(self, logger: logging.Logger, stage: str):
        self.logger = logger
        self.stage = stage
    def __enter__(self):
        self.t0 = time.perf_counter()
        self.logger.info(f"stage_start {self.stage}")
        return self
    def __exit__(self, exc_type, exc, tb):
        dt = time.perf_counter() - self.t0
        if exc:
            self.logger.error(f"stage_error {self.stage} err={exc} duration={dt:.2f}s")
        else:
            self.logger.info(f"stage_end {self.stage} duration={dt:.2f}s")