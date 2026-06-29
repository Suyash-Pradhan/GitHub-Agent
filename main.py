"""
Multi-Agent GitHub Issue Resolver
──────────────────────────────────
Usage:
    python main.py --issue-url https://github.com/user/repo/issues/42

Flow:
    GitHub Issue → Code Reader → Planner ──[simple]──→ Code Writer → Test Writer → PR Opener
                                          └──[complex]─→ Code Writer → Test Writer → PR Opener
"""

import argparse
import os
import re
import sys
from dotenv import load_dotenv
from github import Github

from langgraph.graph import StateGraph, END

from agents.code_writer_agent import code_writer_agent
from agents.handle_error import handle_error
from agents.pr_opener_agent import pr_opener_agent
from agents.test_writer_agent import test_writer_agent
from state import AgentState
from agents.code_reader import code_reader_agent
from agents.planner import planner_agent, route_by_complexity
# from agents.workers import code_writer_agent, test_writer_agent, pr_opener_agent, handle_error

load_dotenv()


def build_graph() -> StateGraph:
    """
    Constructs the LangGraph StateGraph.
    This is the core architecture — study this for interviews.
    """
    workflow = StateGraph(AgentState)

    # ── Register nodes (each is a function that takes + returns AgentState) ──
    workflow.add_node("code_reader",  code_reader_agent)
    workflow.add_node("planner",      planner_agent)
    workflow.add_node("code_writer",  code_writer_agent)
    workflow.add_node("test_writer",  test_writer_agent)
    workflow.add_node("pr_opener",    pr_opener_agent)
    workflow.add_node("handle_error", handle_error)
    

    # ── Define edges (control flow) ──
    workflow.set_entry_point("code_reader")
    workflow.add_edge("code_reader", "planner")

    # *** THE KEY PART: conditional routing based on complexity ***
    workflow.add_conditional_edges(
        "planner",
        route_by_complexity,          # function that returns "simple", "complex", or "handle_error"
        {
            "simple":       "code_writer",   # straightforward fix → go straight to writing
            "complex":      "code_writer",   # for now same path; later add a "research" node here
            "handle_error": "handle_error",
        }
    )

    workflow.add_edge("code_writer", "test_writer")
    workflow.add_edge("test_writer", "pr_opener")
    workflow.add_edge("pr_opener",   END)
    workflow.add_edge("handle_error", END)

    return workflow.compile()


def fetch_issue_details(issue_url: str) -> dict:
    """Parse issue URL and fetch title + body from GitHub."""
    match = re.match(r"https://github\.com/([^/]+/[^/]+)/issues/(\d+)", issue_url)
    if not match:
        print("Error: Invalid GitHub issue URL")
        sys.exit(1)

    repo_name = match.group(1)
    issue_number = int(match.group(2))

    g = Github(os.getenv("GITHUB_TOKEN"))
    repo = g.get_repo(repo_name)
    issue = repo.get_issue(number=issue_number)

    return {
        "repo_full_name": repo_name,
        "issue_title": issue.title,
        "issue_body": issue.body or "(no description provided)",
    }


def main():
    parser = argparse.ArgumentParser(description="AI agent that fixes GitHub issues")
    parser.add_argument("--issue-url", required=True, help="Full GitHub issue URL")
    args = parser.parse_args()

    # Validate env vars
    # if not os.getenv("OPENAI_API_KEY"):
    #     print("Error: OPENAI_API_KEY not set in .env")
    #     sys.exit(1)
    if not os.getenv("GITHUB_TOKEN"):
        print("Error: GITHUB_TOKEN not set in .env")
        sys.exit(1)

    print(f"\n{'='*50}")
    print("  Multi-Agent GitHub Issue Resolver")
    print(f"{'='*50}")
    print(f"  Issue: {args.issue_url}\n")

    # Fetch issue from GitHub
    print("[Setup] Fetching issue from GitHub...")
    issue_details = fetch_issue_details(args.issue_url)
    print(f"  ✓ Issue: {issue_details['issue_title']}")

    # Build initial state
    initial_state: AgentState = {
        "issue_url":      args.issue_url,
        "issue_title":    issue_details["issue_title"],
        "issue_body":     issue_details["issue_body"],
        "repo_full_name": issue_details["repo_full_name"],
        "code_context":   "",
        "fix_plan":       "",
        "complexity":     "simple",
        "patch":          "",
        "tests":          "",
        "pr_url":         None,
        "symbol_cache":   {},   # populated lazily by Code Reader as it investigates
        "error":          None,
    }

    # Build and run the graph
    graph = build_graph()
    final_state = graph.invoke(initial_state)

    # Results
    print(f"\n{'='*50}")
    if final_state.get("error"):
        print(f"  ✗ Pipeline failed: {final_state['error']}")
    elif final_state.get("pr_url"):
        print("  ✓ Done! Pull Request opened:")
        print(f"  → {final_state['pr_url']}")
    else:
        print("  Pipeline completed (no PR opened)")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()