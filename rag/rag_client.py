class RAGClient:
    def __init__(self, cfg):
        self.cfg = cfg
        # 当前阶段先提供安全的空实现，避免阻塞主流程。

    def query(self, q: str) -> list[dict]:
        # 返回 [{"text": "...", "meta": {...}}, ...]
        return []
