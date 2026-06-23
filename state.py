
from typing import TypedDict, Optional

MODEL_NAME = 'gemini-3.1-flash-lite'


class AgentState(TypedDict):
    """
    Shared state object passed between every agent in the pipeline.
    Each agent reads from it and writes its output back into it.
    """

    # --- INPUT ---
    issue_url: str           # e.g. "https://github.com/user/repo/issues/42"
    issue_title: str         # fetched from GitHub
    issue_body: str          # the actual bug report / feature request

    # --- AGENT OUTPUTS (filled in as pipeline runs) ---
    repo_full_name: str      # e.g. "user/repo"
    code_context: str        # relevant file contents (Agent 1)
    fix_plan: str            # step-by-step plan in plain text (Agent 2)
    complexity: str          # "simple" or "complex" — drives routing (Agent 2)
    patch: str               # proposed code changes (Agent 3)
    tests: str               # pytest test code (Agent 4)
    pr_url: Optional[str]    # URL of the opened PR (Agent 5)

    # --- ERROR HANDLING ---
    error: Optional[str]     # if any agent fails, it writes here
