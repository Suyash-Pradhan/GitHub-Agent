from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from state import AgentState, MODEL_NAME
from utils.llm_res_formater import get_text


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
                    content=f"""
You are an expert Python developer. Write a code fix based on this plan.

ISSUE:
{state["issue_title"]}
{state["issue_body"]}

RELEVANT CODE:
{state["code_context"]}

FIX PLAN:
{state["fix_plan"]}

Write ONLY the changed code. Format your response as:

FILE: path/to/file.py
```python
# full updated file content here
```

Be minimal — only change what's necessary to fix the issue.
"""
                )
            ]
        )

        print("  ✓ Code patch generated")
        return {**state, "patch": get_text(response)}

    except Exception as e:
        print(f"  ✗ Code Writer failed: {e}")
        return {**state, "error": f"Code Writer failed: {str(e)}"}
