# roles/architect_agent.py
from metagpt.roles import Role
from actions.generate_sds import GenerateSDSAction

class ArchitectAgent(Role):
    def __init__(self, name: str, llm, rag):
        super().__init__(name=name)
        self.llm = llm
        self.rag = rag
        self.set_actions([GenerateSDSAction(llm=llm)])
    async def propose_sds(self, question: str) -> dict:
        return await self.run(GenerateSDSAction, question=question, rag_client=self.rag)