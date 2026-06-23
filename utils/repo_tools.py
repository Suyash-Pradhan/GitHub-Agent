"""
Tools the Code Reader agent can call during its investigation loop.

These are plain Python functions wrapping the GitHub API — no LLM calls here.
Each one is deliberately cheap and narrow, mirroring what a real harness
gives a coding agent: list, search, read. Nothing more.
"""

import fnmatch

SKIP_DIRS = ("node_modules", "venv", ".git", "dist", "build", "__pycache__")
SOURCE_EXTENSIONS = (".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".rb",
                      ".json", ".yaml", ".yml", ".md")

MAX_GREP_RESULTS = 15
MAX_READ_CHARS = 6000  # truncate very large files so one read_file call can't blow the budget


def list_dir(repo, path: str = "") -> str:
    """
    List files and folders at a given path in the repo.
    Cheap: returns names only, no content.
    """
    try:
        contents = repo.get_contents(path)
        if not isinstance(contents, list):
            contents = [contents]

        lines = []
        for item in contents:
            if item.type == "dir":
                if any(skip in item.path for skip in SKIP_DIRS):
                    continue
                lines.append(f"  [dir]  {item.path}/")
            else:
                lines.append(f"  [file] {item.path}")

        return "\n".join(lines) if lines else "(empty directory)"
    except Exception as e:
        return f"Error listing '{path}': {e}"


def grep(repo, pattern: str, _file_cache: dict) -> str:
    """
    Search for a text pattern across source files in the repo.
    Returns matching file paths + the matching line (not full file content).
    Uses _file_cache to avoid re-fetching files already read this session.
    """
    try:
        matches = []
        contents = repo.get_contents("")
        scanned = 0

        while contents and scanned < 150 and len(matches) < MAX_GREP_RESULTS:
            item = contents.pop(0)

            if item.type == "dir":
                if any(skip in item.path for skip in SKIP_DIRS):
                    continue
                contents.extend(repo.get_contents(item.path))
                continue

            if not item.path.endswith(SOURCE_EXTENSIONS):
                continue

            try:
                if item.path in _file_cache:
                    text = _file_cache[item.path]
                else:
                    text = item.decoded_content.decode("utf-8")
                    _file_cache[item.path] = text
            except Exception:
                continue

            scanned += 1

            for i, line in enumerate(text.splitlines(), start=1):
                if fnmatch.fnmatch(line.lower(), f"*{pattern.lower()}*"):
                    matches.append(f"{item.path}:{i}: {line.strip()[:120]}")
                    if len(matches) >= MAX_GREP_RESULTS:
                        break

        if not matches:
            return f"No matches found for '{pattern}'"
        return "\n".join(matches)

    except Exception as e:
        return f"Error searching for '{pattern}': {e}"


def read_file(repo, path: str, _file_cache: dict) -> str:
    """
    Read the full content of one file. The only 'expensive' tool —
    this is the one that actually costs meaningful tokens downstream.
    """
    try:
        if path in _file_cache:
            content = _file_cache[path]
        else:
            file_obj = repo.get_contents(path)
            content = file_obj.decoded_content.decode("utf-8")
            _file_cache[path] = content

        if len(content) > MAX_READ_CHARS:
            content = content[:MAX_READ_CHARS] + "\n... (truncated, file too large)"

        return content
    except Exception as e:
        return f"Error reading '{path}': {e}"