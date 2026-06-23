"""
Agent 1: Code Reader — now an investigating agent, not a one-shot fetcher.

Instead of grabbing N arbitrary files and hoping they're relevant, this agent
runs a manual ReAct-style loop:

  1. Model sees the issue + a list of tools it can call
  2. Model picks ONE action: list_dir, grep, read_file, or "done"
  3. We execute that action against the real repo and feed the result back
  4. Repeat, up to MAX_TURNS, until the model says "done" or we hit the cap

This is the harness pattern: small steps, model decides what to look at,
no upfront relevance guessing. Built manually (no LangChain bind_tools)
so every step is visible and explainable.
"""

import json
import re
from github import Github
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from state import AgentState, MODEL_NAME
from utils.repo_tools import list_dir, grep, read_file
import os
from utils.llm_res_formater import get_text

MAX_TURNS = 1

SYSTEM_INSTRUCTIONS = """You are a code investigator helping debug a GitHub issue.
You do NOT have the codebase yet. You must investigate it yourself using these actions:

1. list_dir(path) — see what files/folders exist at a path. Use "" for repo root.
2. grep(pattern) — search all source files for a text pattern (function names, error strings, etc).
3. read_file(path) — read the full content of one specific file.
4. done() — call this when you have enough context to describe the relevant code.

Respond with ONLY valid JSON for ONE action per turn, no markdown, no explanation outside the JSON:
{"action": "list_dir", "path": ""}
{"action": "grep", "pattern": "calculate_total"}
{"action": "read_file", "path": "utils/parser.py"}
{"action": "done", "summary": "your findings here — relevant files, functions, and what needs to change"}

Think like a developer: start broad (list_dir or grep for keywords from the issue),
then narrow in on specific files. Don't call read_file on something you haven't
located via list_dir or grep first, unless the issue explicitly names the file.
"""


def _parse_action(raw_text: str) -> dict:
    print(type(raw_text))
    print('raaawww')
    print(raw_text)
    """Extract the JSON action from the model's response, tolerating code fences."""
    cleaned = re.sub(r"```json|```", "", raw_text).strip()
    return json.loads(cleaned)


def code_reader_agent(state: AgentState) -> AgentState:
    print("\n[Agent 1 - Code Reader] Starting investigation loop...")

    try:
        g = Github(os.getenv("GITHUB_TOKEN"))
        repo = g.get_repo(state["repo_full_name"])
        llm = ChatGoogleGenerativeAI(model=MODEL_NAME, temperature=0)

        file_cache = {}  # avoid re-fetching the same file twice in one investigation
        transcript = (
            []
        )  # running log of actions + results, fed back to the model each turn
        final_summary = None

        opening_prompt = f"""{SYSTEM_INSTRUCTIONS}

ISSUE:
{state['issue_title']}
{state['issue_body']}

Begin your investigation. What's your first action?"""

        messages = [HumanMessage(content=opening_prompt)]
        print("msg: " + messages[0].content + "\n")

        for turn in range(1, MAX_TURNS + 1):
            response = llm.invoke(messages)
            print(response)
            print('reponseee')
            print("res: " + get_text(response) + "\n")

            try:
                action = _parse_action(get_text(response))
            except Exception:
                print(
                    f"  ⚠ Turn {turn}: model returned unparseable action, stopping loop"
                )
                break

            action_type = action.get("action")

            if action_type == "done":
                final_summary = action.get("summary", "")
                print(f"  ✓ Turn {turn}: investigation complete")
                break

            elif action_type == "list_dir":
                path = action.get("path", "")
                result = list_dir(repo, path)
                print(f"  → Turn {turn}: list_dir('{path}')")

            elif action_type == "grep":
                pattern = action.get("pattern", "")
                result = grep(repo, pattern, file_cache)
                print(
                    f"  → Turn {turn}: grep('{pattern}') — {len(result.splitlines())} matches"
                )

            elif action_type == "read_file":
                path = action.get("path", "")
                result = read_file(repo, path, file_cache)
                print(f"  → Turn {turn}: read_file('{path}')")

            else:
                print(f"  ⚠ Turn {turn}: unknown action '{action_type}', stopping loop")
                break

            transcript.append(f"Action: {action}\nResult:\n{result}")

            # Feed the running transcript back so the model has memory of what it's seen
            messages = [HumanMessage(content=f"""{opening_prompt}

INVESTIGATION SO FAR:
{chr(10).join(transcript)}

What's your next action? (Turn {turn + 1} of {MAX_TURNS} max)""")]

        else:
            # Loop exhausted MAX_TURNS without the model calling "done"
            print(
                f"  ⚠ Hit {MAX_TURNS}-turn cap without explicit 'done' — using gathered context as-is"
            )

        if final_summary is None:
            # Either hit turn cap or parsing failed — fall back to whatever was gathered
            if transcript:
                final_summary = (
                    "Investigation did not conclude explicitly. Raw findings:\n\n"
                    + "\n\n".join(transcript)
                )
            else:
                final_summary = "No investigation data was gathered."

        files_read = list(file_cache.keys())
        print(
            f"  ✓ Investigation used {len(transcript)} tool call(s), read {len(files_read)} file(s): {files_read}"
        )

        return {**state, "code_context": final_summary}

    except Exception as e:
        print(f"  ✗ Code Reader failed: {e}")
        return {**state, "error": f"Code Reader failed: {str(e)}"}
