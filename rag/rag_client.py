class RAGClient:
    def __init__(self, cfg):
        self.cfg = cfg
        # 加载向量索引
    def query(self, q: str) -> list[dict]:
        # 返回 [{"text": "...", "meta": {...}}, ...]
        ...