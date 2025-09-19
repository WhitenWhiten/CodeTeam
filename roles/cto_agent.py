# roles/cto_agent.py
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

from actions.select_sds import SelectSDSAction

class CTOAgent(Role):
    def __init__(self, llm, rag):
        super().__init__(name="CTO")
        self.llm = llm
        self.rag = rag
        self.set_actions([SelectSDSAction(llm=llm)])

    async def choose(self, question, sds_list):
        return await self.run(SelectSDSAction, question=question, sds_list=sds_list, rag_client=self.rag)
