from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from state import AgentState, MODEL_NAME
from utils.llm_res_formater import get_text
import re


_EXTENSION_TO_LANGUAGE = {
    ".py": ("Python", "python"),
    ".js": ("JavaScript", "javascript"),
    ".jsx": ("JavaScript", "javascript"),
    ".ts": ("TypeScript", "typescript"),
    ".tsx": ("TypeScript", "typescript"),
    ".go": ("Go", "go"),
}


def _infer_target_language(state: AgentState) -> tuple[str, str, str]:
    """
    Infer the target file path, display language, and fenced code label.

    Prefer file paths surfaced in the code context or fix plan because they
    already reflect the repository's actual language.
    """
    context_text = f"{state.get('code_context', '')}\n{state.get('fix_plan', '')}"
    path_matches = re.findall(r"[A-Za-z0-9_./\\-]+\.[A-Za-z0-9_+\-]+", context_text)

    for path in path_matches:
        lower_path = path.lower()
        for extension, (language_name, fence_label) in _EXTENSION_TO_LANGUAGE.items():
            if lower_path.endswith(extension):
                return path.replace("\\", "/"), language_name, fence_label

    return "path/to/file.py", "Python", "python"


def _build_writer_prompt(state: AgentState) -> str:
    target_path, language_name, fence_label = _infer_target_language(state)

    return f"""
You are an expert {language_name} developer. Write a code fix based on this plan.

ISSUE:
{state["issue_title"]}
{state["issue_body"]}

RELEVANT CODE:
{state["code_context"]}

FIX PLAN:
{state["fix_plan"]}

Write ONLY the changed code. Format your response as:

FILE: {target_path}
```{fence_label}
# full updated file content here
```

Be minimal — only change what's necessary to fix the issue.
"""


def code_writer_agent(state: AgentState) -> AgentState:
    """
    Agent 3: Generates the actual code fix based on the plan.
    Outputs a patch/diff or the new file content.
    """
    print("\n[Agent 3 - Code Writer] Writing fix...")

    try:
        llm = ChatGoogleGenerativeAI(model=MODEL_NAME, temperature=0)
        response = llm.invoke(
            [
                HumanMessage(
                    content=_build_writer_prompt(state)
                )
            ]
        )

        print("  ✓ Code patch generated")
        return {**state, "patch": get_text(response)}

    except Exception as e:
        print(f"  ✗ Code Writer failed: {e}")
        return {**state, "error": f"Code Writer failed: {str(e)}"}
