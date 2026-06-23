from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from github import Github, GithubException
from state import AgentState
import os
import re


FILE_BLOCK_RE = re.compile(
    r"FILE:\s*(?P<path>.+?)\s*```(?:[a-zA-Z0-9_+-]+)?\s*(?P<content>.*?)\s*```",
    re.DOTALL,
)


def _extract_file_blocks(text: str) -> list[tuple[str, str]]:
    blocks = []
    for match in FILE_BLOCK_RE.finditer(text):
        path = match.group("path").strip()
        content = match.group("content")
        if path and content:
            blocks.append((path, content.rstrip() + "\n"))
    return blocks


def _commit_file_changes(repo, branch_name: str, file_blocks: list[tuple[str, str]], commit_prefix: str) -> None:
    for path, content in file_blocks:
        commit_message = f"{commit_prefix}: update {path}"
        try:
            existing = repo.get_contents(path, ref=branch_name)
            repo.update_file(
                path=path,
                message=commit_message,
                content=content,
                sha=existing.sha,
                branch=branch_name,
            )
        except GithubException as e:
            if getattr(e, "status", None) == 404:
                repo.create_file(
                    path=path,
                    message=commit_message,
                    content=content,
                    branch=branch_name,
                )
            else:
                raise

# ─────────────────────────────────────────────
# Agent 3 — Code Writer
# ─────────────────────────────────────────────


def code_writer_agent(state: AgentState) -> AgentState:
    """
    Agent 3: Generates the actual code fix based on the plan.
    Outputs a patch/diff or the new file content.
    """
    print("\n[Agent 3 - Code Writer] Writing fix...")

    try:
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
        response = llm.invoke([HumanMessage(content=f"""
You are an expert Python developer. Write a code fix based on this plan.

ISSUE:
{state['issue_title']}
{state['issue_body']}

RELEVANT CODE:
{state['code_context']}

FIX PLAN:
{state['fix_plan']}

Write ONLY the changed code. Format your response as:

FILE: path/to/file.py
```python
# full updated file content here
```

Be minimal — only change what's necessary to fix the issue.
""")])

        print(f"  ✓ Code patch generated")
        return {**state, "patch": response.content}

    except Exception as e:
        print(f"  ✗ Code Writer failed: {e}")
        return {**state, "error": f"Code Writer failed: {str(e)}"}


# ─────────────────────────────────────────────
# Agent 4 — Test Writer
# ─────────────────────────────────────────────


def test_writer_agent(state: AgentState) -> AgentState:
    """
    Agent 4: Writes pytest tests that verify the fix works.
    """
    print("\n[Agent 4 - Test Writer] Writing tests...")

    try:
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
        response = llm.invoke([HumanMessage(content=f"""
You are a Python testing expert. Write pytest tests for this bug fix.

ISSUE BEING FIXED:
{state['issue_title']}
{state['issue_body']}

THE FIX:
{state['patch']}

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
""")])

        print(f"  ✓ Tests generated")
        return {**state, "tests": response.content}

    except Exception as e:
        print(f"  ✗ Test Writer failed: {e}")
        return {**state, "error": f"Test Writer failed: {str(e)}"}


# ─────────────────────────────────────────────
# Agent 5 — PR Opener
# ─────────────────────────────────────────────


def pr_opener_agent(state: AgentState) -> AgentState:
    """
    Agent 5: Creates a new branch and opens a real GitHub Pull Request.
    """
    print("\n[Agent 5 - PR Opener] Opening pull request...")

    try:
        g = Github(os.getenv("GITHUB_TOKEN"))
        repo = g.get_repo(state["repo_full_name"])

        # Create a new branch from main
        main_branch = repo.get_branch("main")
        branch_name = f"fix/issue-auto-{state['issue_title'][:30].lower().replace(' ', '-').replace('/', '-')}"
        branch_name = "".join(c for c in branch_name if c.isalnum() or c in "-/")

        try:
            repo.create_git_ref(
                ref=f"refs/heads/{branch_name}", sha=main_branch.commit.sha
            )
            print(f"  ✓ Created branch: {branch_name}")
        except GithubException as e:
            if "already exists" in str(e):
                print(f"  ℹ Branch already exists, reusing: {branch_name}")
            else:
                raise

        patch_blocks = _extract_file_blocks(state.get("patch", ""))
        test_blocks = _extract_file_blocks(state.get("tests", ""))
        all_blocks = patch_blocks + test_blocks

        if not all_blocks:
            raise ValueError(
                "Generated fix did not include any file blocks, so no commit could be created."
            )

        _commit_file_changes(
            repo=repo,
            branch_name=branch_name,
            file_blocks=all_blocks,
            commit_prefix=f"fix: {state['issue_title'][:40]}",
        )

        print(f"  ✓ Committed {len(all_blocks)} file change(s) to {branch_name}")

        # Build PR body
        pr_body = f"""## 🤖 Automated Fix

This PR was generated by a multi-agent AI system in response to the issue.

### Issue
{state['issue_title']}

### Fix Plan
{state['fix_plan']}

### Changes
{state['patch']}

### Tests Added
```python
{state['tests']}
```

---
*Generated by [github-agent](https://github.com/{state['repo_full_name']})*
"""

        # Open the pull request
        comparison = repo.compare(base="main", head=branch_name)
        if comparison.ahead_by == 0:
            raise ValueError(
                f"Branch {branch_name} has no commits ahead of main after applying the generated fix."
            )

        pr = repo.create_pull(
            title=f"fix: {state['issue_title']}",
            body=pr_body,
            head=branch_name,
            base="main",
        )

        print(f"  ✓ PR opened: {pr.html_url}")
        return {**state, "pr_url": pr.html_url}

    except Exception as e:
        print(f"  ✗ PR Opener failed: {e}")
        return {**state, "error": f"PR Opener failed: {str(e)}"}


# ─────────────────────────────────────────────
# Error handler node
# ─────────────────────────────────────────────


def handle_error(state: AgentState) -> AgentState:
    print(f"\n[Orchestrator] Pipeline stopped due to error: {state.get('error')}")
    return state
