# roles/architect_agent.py
from __future__ import annotations
try:
    from metagpt.roles import Role
except ImportError:
    class Role:
        def __init__(self, name: str = ""):
            self.name = name
        def set_actions(self, actions): self._actions = actions
        async def run(self, action_cls, **kwargs):
            action = None
            for a in self._actions:
                if isinstance(a, action_cls) or (a.__class__ is action_cls):
                    action = a
                    break
            return await action.run(**kwargs)

from actions.generate_sds import GenerateSDSAction

class ArchitectAgent(Role):
    def __init__(self, name: str, llm, rag):
        super().__init__(name=name)
        self.llm = llm
        self.rag = rag
        self._gen = GenerateSDSAction(llm=llm)

    async def propose_sds(
        self,
        question: str,
        design_preference: str = "",
        claimed_summary: str = "",
        return_trace: bool = False,
    ) -> dict:
        return await self._gen.run(
            question=question,
            rag_client=self.rag,
            design_preference=design_preference,
            claimed_summary=claimed_summary,
            return_trace=return_trace,
        )
