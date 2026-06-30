from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from state import MODEL_NAME, AgentState
from utils.llm_res_formater import get_text


def test_writer_agent(state: AgentState) -> AgentState:
    """
    Agent 4: Writes pytest tests that verify the fix works.
    """
    print("\n[Agent 4 - Test Writer] Writing tests...")

    try:
        llm = ChatGoogleGenerativeAI(model=MODEL_NAME, temperature=0)
        response = llm.invoke(
            [
                HumanMessage(
                    content=f"""
You are a Python testing expert. Write pytest tests for this bug fix.

ISSUE BEING FIXED:
{state["issue_title"]}
{state["issue_body"]}

THE FIX:
{state["patch"]}

Write 2-3 focused pytest tests that:
1. Reproduce the original bug (should have failed before the fix)
2. Verify the fix works correctly
3. Test any edge cases

Format as a complete test file starting with imports.
Return it in this exact format:

FILE: tests/test_generated_fix.py
```python
<complete test file>
```
"""
                )
            ]
        )

        print("  ✓ Tests generated")
        return {**state, "tests": get_text(response)}

    except Exception as e:
        print(f"  ✗ Test Writer failed: {e}")
        return {**state, "error": f"Test Writer failed: {str(e)}"}
