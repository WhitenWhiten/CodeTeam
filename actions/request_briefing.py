from __future__ import annotations

try:
    from metagpt.actions import Action
except ImportError:
    class Action:
        def __init__(self, name: str = ""):
            self.name = name

        async def run(self, *args, **kwargs):
            raise NotImplementedError


class RequestBriefingAction(Action):
    def __init__(self):
        try:
            super().__init__()
        except TypeError:
            super().__init__(name="RequestBriefingAction")

    async def run(self, target_file: str, brief_manager):
        return brief_manager.get_brief(target_file)
