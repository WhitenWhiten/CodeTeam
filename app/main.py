# app/main.py
from __future__ import annotations
import asyncio
from app.config import load_config
from app.bootstrap import bootstrap
from orchestrator.workflow import MultiAgentCodegenWorkflow

def main():
    cfg = load_config()
    # set config here
    cfg.user_question = "生成一个带有命令行ui的简易图书管理系统,要求进入主程序时有添加图书、图书查询、图书列表三项功能，并在执行完一项功能后返回主界面"
    cfg.rag.enabled = True
    cfg.llm.base_url = "https://api.openai-proxy.org/v1"
    cfg.architects = 3
    cfg.sds_retry = 2
    cfg.max_rounds = 3
    cfg.workspace = "./workspace"
    ctx = bootstrap(cfg)
    wf = MultiAgentCodegenWorkflow(ctx)
    repo_path = asyncio.run(wf.run(question=cfg.user_question))
    print(f"Done. Repo at: {repo_path}")

if __name__ == "__main__":
    main()
