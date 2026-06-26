"""
Agent 1: Code Reader — investigating agent with a dynamic ReAct-style loop.

Each turn the agent:
  1. Sees the issue + full transcript of everything found so far
  2. Decides which tools to call (can batch multiple per turn)
  3. We execute all of them and feed results back
  4. Repeat up to MAX_TURNS, or until agent calls report_findings

Key design decisions:
  - No pre-assigned roles per turn. Agent decides dynamically each turn.
  - Batched tool calls: agent can call multiple tools in one turn (one LLM call).
  - Lazy symbol parsing: parse_file_symbols only called after grep finds a file.
  - symbol_cache persists across turns in AgentState — no re-parsing same file.
  - report_findings is the normal exit. MAX_TURNS is the safety cap, not the target.
  - Manual loop (no LangChain bind_tools) — every step is visible and explainable.
"""

import json
import re
from github import Github
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from state import AgentState, MODEL_NAME
from utils.repo_tools import (
    list_dir,
    grep,
    read_file,
    read_lines,
    grep_context,
    parse_file_symbols,
    lookup_symbol,
)
import os
from utils.llm_res_formater import get_text

MAX_TURNS = 4

SYSTEM_INSTRUCTIONS = """You are a code investigator helping debug a GitHub issue.
You do NOT have the codebase yet. You must investigate it step by step using tools.

AVAILABLE TOOLS:
1. list_dir(path)                        — list files/folders at a path. Use "" for repo root.
2. grep(pattern)                         — search all source files for a text pattern.
3. grep_context(pattern, context_lines)  — like grep but returns surrounding lines for context. Use this when grep alone isn't enough to decide if a file is relevant.
4. read_file(path)                       — read full file (use only for small files, prefer read_lines).
5. read_lines(path, start, end)          — read an exact line range. Always use this after lookup_symbol gives you line numbers.
6. parse_and_cache_symbols(path)         — parse a file's symbols (functions, classes) into the cache. Call this after grep finds a file you want to explore deeply.
7. lookup_symbol(name)                   — find a symbol by name in already-parsed files. Returns file + line range.
8. report_findings(summary, files, confidence) — call this when you have enough context. This ends the investigation.

RESPONSE FORMAT:
Respond ONLY with a JSON array of tool calls. No explanation, no markdown:
[
  {"tool": "grep", "pattern": "handleLogin"},
  {"tool": "grep", "pattern": "router.push"}
]

Or a single report_findings to finish:
[
  {"tool": "report_findings", "summary": "...", "files": ["src/auth/LoginForm.jsx"], "confidence": "high"}
]

INVESTIGATION STRATEGY:
- First turn: extract all keywords from the issue (function names, error strings, file hints) and grep them ALL in one turn. Don't do one grep and wait.
- After grep finds candidate files: call parse_and_cache_symbols on them, then lookup_symbol to get exact line ranges. On the following turn, call read_lines with the exact file and line range returned by lookup_symbol; never guess ranges or rely on defaults.
- Each turn, look at everything found so far and decide what's still missing. If a read wasn't useful, try a different symbol or file next turn — don't stop early.
- Only call report_findings when you can explain what needs to change and why.
- confidence must be "high", "medium", or "low". Low confidence means Planner will flag for human review.
- BATCH tool calls — call everything you need this turn in one array. Don't do one thing per turn when you could do three.
"""


def _parse_tool_calls(raw_text: str) -> list:
    """
    Parse the model response into a list of tool call dicts.
    Tolerates markdown code fences.
    Returns empty list if parsing fails.
    """
    cleaned = re.sub(r"```json|```", "", raw_text).strip()
    parsed = json.loads(cleaned)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _execute_tool(tool_call: dict, repo, file_cache: dict, symbol_cache: dict) -> str:
    """
    Dispatch one tool call dict to the correct repo_tools function.
    Returns the result as a string to append to the transcript.
    """
    tool = tool_call.get("tool", "")

    if tool == "list_dir":
        path = tool_call.get("path", "")
        return list_dir(repo, path)

    elif tool == "grep":
        pattern = tool_call.get("pattern", "")
        return grep(repo, pattern, file_cache)

    elif tool == "grep_context":
        pattern = tool_call.get("pattern", "")
        try:
            ctx = int(tool_call.get("context_lines", 5))
        except (TypeError, ValueError):
            return "Error: grep_context.context_lines must be an integer"
        return grep_context(repo, pattern, file_cache, context_lines=ctx)

    elif tool == "read_file":
        path = tool_call.get("path", "")
        return read_file(repo, path, file_cache)

    elif tool == "read_lines":
        path = tool_call.get("path", "")
        try:
            start = int(tool_call.get("start", 1))
            end = int(tool_call.get("end", start + 50))
        except (TypeError, ValueError):
            return "Error: read_lines.start and read_lines.end must be integers"
        return read_lines(repo, path, start, end, file_cache)

    elif tool == "parse_and_cache_symbols":
        path = tool_call.get("path", "")
        if path in symbol_cache:
            return f"Symbols for '{path}' already cached ({len(symbol_cache[path])} symbols)."
        if path not in file_cache:
            # fetch the file first
            result = read_file(repo, path, file_cache)
            if result.startswith("Error"):
                return result
        symbols = parse_file_symbols(path, file_cache[path])
        symbol_cache[path] = symbols
        if not symbols:
            return (
                f"No symbols extracted from '{path}' (unsupported type or empty file)."
            )
        summary = ", ".join(
            f"{s['name']}({s['start']}-{s['end']})" for s in symbols[:20]
        )
        more = f" ... +{len(symbols) - 20} more" if len(symbols) > 20 else ""
        return f"Cached {len(symbols)} symbols from '{path}': {summary}{more}"

    elif tool == "lookup_symbol":
        name = tool_call.get("name", "")
        return lookup_symbol(name, symbol_cache)

    elif tool == "report_findings":
        # Handled in the loop — won't reach here
        return ""

    else:
        return f"Unknown tool '{tool}' — check your spelling. Available: list_dir, grep, grep_context, read_file, read_lines, parse_and_cache_symbols, lookup_symbol, report_findings"


def code_reader_agent(state: AgentState) -> AgentState:
    print("\n[Agent 1 - Code Reader] Starting investigation loop...")

    try:
        g = Github(os.getenv("GITHUB_TOKEN"))
        repo = g.get_repo(state["repo_full_name"])
        llm = ChatGoogleGenerativeAI(model=MODEL_NAME, temperature=0)

        file_cache: dict = {}
        # Carry over symbol_cache from state if it exists (future: multi-run pipelines)
        symbol_cache: dict = state.get("symbol_cache") or {}

        transcript = []
        final_summary = None
        confidence = "low"
        files_found = []

        opening_prompt = f"""{SYSTEM_INSTRUCTIONS}

ISSUE TITLE: {state["issue_title"]}

ISSUE BODY:
{state["issue_body"]}

Begin your investigation. What tool calls do you need this first turn?"""

        messages = [HumanMessage(content=opening_prompt)]

        for turn in range(1, MAX_TURNS + 1):
            print(f"\n  [Turn {turn}/{MAX_TURNS}]")

            response = llm.invoke(messages)
            raw = get_text(response)

            try:
                tool_calls = _parse_tool_calls(raw)
            except Exception as e:
                print(
                    f"  ⚠ Turn {turn}: unparseable response — {e}\n  Raw: {raw[:200]}"
                )
                break

            if not tool_calls:
                print(f"  ⚠ Turn {turn}: empty tool call list, stopping")
                break

            # Extract report_findings (if present)
            report_call = next(
                (c for c in tool_calls if c.get("tool") == "report_findings"),
                None,
            )

            # Everything except report_findings
            exploratory_calls = [
                c for c in tool_calls if c.get("tool") != "report_findings"
            ]

            # Only finish if report_findings is the ONLY call
            is_final = report_call is not None and not exploratory_calls

            # Execute exploratory tools
            turn_results = []

            for call in exploratory_calls:
                result = _execute_tool(call, repo, file_cache, symbol_cache)

                turn_results.append(f"  tool: {json.dumps(call)}\n  result:\n{result}")

                print(
                    f"    → {call.get('tool')}("
                    f"{', '.join(str(v) for k, v in call.items() if k != 'tool')})"
                )

            # Save transcript
            turn_entry = f"=== Turn {turn} ===\n" + "\n\n".join(turn_results)
            transcript.append(turn_entry)

            # Finish only when report_findings was the sole tool
            if is_final:
                final_summary = report_call.get("summary", "")
                confidence = report_call.get("confidence", "low")
                files_found = report_call.get("files", [])

                print(
                    f"  ✓ Turn {turn}: investigation complete "
                    f"(confidence: {confidence})"
                )
                break

            # Build next turn prompt
            transcript_text = "\n\n".join(transcript)

            messages = [
                HumanMessage(
                    content=f"""{opening_prompt}

INVESTIGATION SO FAR:
{transcript_text}

Turn {turn + 1} of {MAX_TURNS} max. What do you need to look at next?
Remember: batch all tool calls you need this turn into one array."""
                )
            ]

        else:
            print(
                f"  ⚠ Hit {MAX_TURNS}-turn cap without report_findings — using gathered context"
            )

        # Build final summary if agent never called report_findings
        if final_summary is None:
            if transcript:
                final_summary = (
                    "Investigation hit turn cap without a conclusion. Raw findings:\n\n"
                    + "\n\n".join(transcript)
                )
                confidence = "low"
            else:
                final_summary = "No investigation data was gathered."
                confidence = "low"

        # Format code_context for downstream agents
        code_context = (
            f"[Confidence: {confidence}]\n\n"
            f"Summary:\n{final_summary}\n\n"
            f"Files identified: {', '.join(files_found) if files_found else 'see transcript'}\n\n"
            f"Full investigation transcript:\n{'=' * 40}\n" + "\n\n".join(transcript)
        )

        print(
            f"\n  ✓ Investigation done — {len(transcript)} turn(s), "
            f"{len(file_cache)} file(s) fetched, "
            f"{sum(len(v) for v in symbol_cache.values())} symbols cached, "
            f"confidence: {confidence}"
        )

        return {
            **state,
            "code_context": code_context,
            "symbol_cache": symbol_cache,
        }

    except Exception as e:
        print(f"  ✗ Code Reader failed: {e}")
        return {**state, "error": f"Code Reader failed: {str(e)}"}
