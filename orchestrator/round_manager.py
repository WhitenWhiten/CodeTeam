# orchestrator/round_manager.py
from threading import Event

class RoundManager:
    def __init__(self):
        self.round_done = Event()