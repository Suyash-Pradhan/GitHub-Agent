from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from state import AgentState, MODEL_NAME
import json
import re
from utils.llm_res_formater import get_text


def planner_agent(state: AgentState) -> AgentState:
    """
    Agent 2: Reads the issue + code context and creates a structured fix plan.
    """
    print("\n[Agent 2 - Planner] Creating fix plan...")

    try:
        llm = ChatGoogleGenerativeAI(model=MODEL_NAME, temperature=0)
        response = llm.invoke(
            [
                HumanMessage(
                    content=f"""
You are a senior software engineer planning a bug fix.

ISSUE:
{state["issue_title"]}
{state["issue_body"]}

RELEVANT CODE:
{state["code_context"]}

Create a fix plan and respond ONLY with valid JSON (no markdown, no explanation):
{{
  "steps": [
    "Step 1: ...",
    "Step 2: ..."
  ],
  "files_to_edit": ["path/to/file.py"],
  "summary": "One sentence describing the fix"
}}
"""
                )
            ]
        )

        # Parse JSON from response
        text = get_text(response)
        raw = text.strip()
        # Strip markdown code fences if LLM adds them
        raw = re.sub(r"```json|```", "", raw).strip()
        plan_data = json.loads(raw)

        plan_text = (
            f"Summary: {plan_data['summary']}\n\n"
            f"Files to edit: {', '.join(plan_data['files_to_edit'])}\n\n"
            f"Steps:\n" + "\n".join(f"  {s}" for s in plan_data["steps"])
        )

        print(f"  ✓ Plan created")
        return {**state, "fix_plan": plan_text}

    except Exception as e:
        print(f"  ✗ Planner failed: {e}")
        return {**state, "error": f"Planner failed: {str(e)}"}


def route_after_planner(state: AgentState) -> str:
    """
    Conditional edge function: tells LangGraph which node to go to next.
    """
    if state.get("error"):
        return "handle_error"
    return "code_writer"
