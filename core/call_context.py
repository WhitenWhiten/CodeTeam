"""Context-local attribution, safe across concurrent developer coroutines."""
from contextlib import contextmanager
from contextvars import ContextVar

current_call_context = ContextVar('codeteam_model_call', default={})

@contextmanager
def model_call_context(**metadata):
    token = current_call_context.set({**current_call_context.get(), **metadata})
    try:
        yield
    finally:
        current_call_context.reset(token)
