from app.config import load_config
from app.bootstrap import bootstrap
from orchestrator.workflow import MultiAgentCodegenWorkflow

def main():
    cfg = load_config()
    ctx = bootstrap(cfg)
    workflow = MultiAgentCodegenWorkflow(ctx)
    repo_path = workflow.run(question=cfg.user_question)
    print(f"Done. Repo at: {repo_path}")

if __name__ == "__main__":
    main()