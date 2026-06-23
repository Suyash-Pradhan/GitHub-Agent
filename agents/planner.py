from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from state import AgentState
import json
import re


def planner_agent(state: AgentState) -> AgentState:
    """
    Agent 2: Reads the issue + code context and creates a structured fix plan.
    Also sets complexity = "simple" or "complex" to drive conditional routing.
    """
    print("\n[Agent 2 - Planner] Creating fix plan...")

    try:
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
        response = llm.invoke([
            HumanMessage(content=f"""
You are a senior software engineer planning a bug fix.

ISSUE:
{state['issue_title']}
{state['issue_body']}

RELEVANT CODE:
{state['code_context']}

Create a fix plan and respond ONLY with valid JSON (no markdown, no explanation):
{{
  "complexity": "simple",
  "steps": [
    "Step 1: ...",
    "Step 2: ..."
  ],
  "files_to_edit": ["path/to/file.py"],
  "summary": "One sentence describing the fix"
}}

complexity must be "simple" (1-2 files, clear fix) or "complex" (multiple files or unclear root cause).
""")
        ])

        # Parse JSON from response
        raw = response.content.strip()
        # Strip markdown code fences if LLM adds them
        raw = re.sub(r"```json|```", "", raw).strip()
        plan_data = json.loads(raw)

        complexity = plan_data.get("complexity", "simple")
        plan_text = (
            f"Summary: {plan_data['summary']}\n\n"
            f"Files to edit: {', '.join(plan_data['files_to_edit'])}\n\n"
            f"Steps:\n" + "\n".join(f"  {s}" for s in plan_data["steps"])
        )

        print(f"  ✓ Plan created (complexity: {complexity})")
        return {**state, "fix_plan": plan_text, "complexity": complexity}

    except Exception as e:
        print(f"  ✗ Planner failed: {e}")
        return {**state, "error": f"Planner failed: {str(e)}"}


def route_by_complexity(state: AgentState) -> str:
    """
    Conditional edge function: tells LangGraph which node to go to next.
    This is the key architectural decision in the graph.
    """
    if state.get("error"):
        return "handle_error"
    complexity = state.get("complexity", "simple")
    print(f"\n[Orchestrator] Routing → {complexity} path")
    return complexity  # "simple" or "complex"
