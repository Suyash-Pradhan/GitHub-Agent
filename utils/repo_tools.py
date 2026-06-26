"""
Tools the Code Reader agent can call during its investigation loop.

These are plain Python functions wrapping the GitHub API — no LLM calls here.
Each one is deliberately cheap and narrow, mirroring what a real harness
gives a coding agent: list, search, read. Nothing more.

New in this version:
  - read_lines(repo, path, start, end, cache)     targeted line-range read
  - grep_context(repo, pattern, cache, n)          grep + surrounding lines
  - parse_file_symbols(path, source_text)          lazy tree-sitter symbol index per file
  - lookup_symbol(name, symbol_cache)              query the symbol index
"""

import fnmatch

SKIP_DIRS = ("node_modules", "venv", ".git", "dist", "build", "__pycache__")
SOURCE_EXTENSIONS = (
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".java",
    ".rb",
    ".json",
    ".yaml",
    ".yml",
    ".md",
)

MAX_GREP_RESULTS = 15
MAX_READ_CHARS = 6000  # fallback cap for read_file only
MAX_CONTEXT_LINES = 20


# ─────────────────────────────────────────────
# Existing tools (unchanged)
# ─────────────────────────────────────────────


def list_dir(repo, path: str = "") -> str:
    """List files and folders at a given path in the repo."""
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
    Search for a text pattern across source files.
    Returns file path + line number + the matching line.
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
    Read full file content. Kept as a fallback for small files.
    Prefer read_lines for large files once you know the line range.
    """
    try:
        if path in _file_cache:
            content = _file_cache[path]
        else:
            file_obj = repo.get_contents(path)
            content = file_obj.decoded_content.decode("utf-8")
            _file_cache[path] = content

        if len(content) > MAX_READ_CHARS:
            content = (
                content[:MAX_READ_CHARS]
                + "\n... (truncated — use read_lines with a line range for deeper access)"
            )

        return content
    except Exception as e:
        return f"Error reading '{path}': {e}"


# ─────────────────────────────────────────────
# New tool 1: read_lines
# ─────────────────────────────────────────────


def read_lines(repo, path: str, start: int, end: int, _file_cache: dict) -> str:
    """
    Read a specific line range from a file.
    start and end are 1-indexed and inclusive.

    Use this after lookup_symbol gives you the exact line range —
    never guess a range, always get it from the symbol index first.
    """
    try:
        if path in _file_cache:
            content = _file_cache[path]
        else:
            file_obj = repo.get_contents(path)
            content = file_obj.decoded_content.decode("utf-8")
            _file_cache[path] = content

        lines = content.splitlines()
        total = len(lines)

        # clamp to actual file bounds
        start = max(1, start)
        end = min(total, end)

        if start > total:
            return f"Error: start line {start} exceeds file length ({total} lines)"

        selected = lines[start - 1 : end]
        # Prefix each line with its real line number so the agent can reason about positions
        numbered = "\n".join(
            f"{start + i:>4}: {line}" for i, line in enumerate(selected)
        )
        return f"[{path} lines {start}-{end} of {total}]\n{numbered}"

    except Exception as e:
        return f"Error reading lines from '{path}': {e}"


# ─────────────────────────────────────────────
# New tool 2: grep_context
# ─────────────────────────────────────────────


def grep_context(repo, pattern: str, _file_cache: dict, context_lines: int = 5) -> str:
    """
    Like grep, but returns N lines of surrounding context around each match.
    Useful when the agent needs to decide if a match is worth a full read_lines call.
    Caps at 5 matches to keep token cost down.
    """
    try:
        # Validate and clamp context_lines
        try:
            context_lines = int(context_lines)
        except (TypeError, ValueError):
            return "Error: grep_context.context_lines must be an integer"

        context_lines = max(0, min(context_lines, MAX_CONTEXT_LINES))
        results = []
        contents = repo.get_contents("")
        scanned = 0
        MAX_CONTEXT_MATCHES = 5

        while contents and scanned < 150 and len(results) < MAX_CONTEXT_MATCHES:
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
            all_lines = text.splitlines()

            for i, line in enumerate(all_lines):
                if fnmatch.fnmatch(line.lower(), f"*{pattern.lower()}*"):
                    lo = max(0, i - context_lines)
                    hi = min(len(all_lines), i + context_lines + 1)
                    snippet_lines = all_lines[lo:hi]
                    numbered = "\n".join(
                        f"{'>>>' if j == i else '   '} {lo + idx + 1:>4}: {l}"
                        for idx, (j, l) in enumerate(
                            (lo + k, snippet_lines[k])
                            for k in range(len(snippet_lines))
                        )
                    )
                    results.append(
                        f"--- {item.path} (match at line {i + 1}) ---\n{numbered}"
                    )
                    if len(results) >= MAX_CONTEXT_MATCHES:
                        break

        if not results:
            return f"No matches found for '{pattern}'"
        return "\n\n".join(results)

    except Exception as e:
        return f"Error in grep_context for '{pattern}': {e}"


# ─────────────────────────────────────────────
# New tool 3: parse_file_symbols  (tree-sitter, lazy)
# ─────────────────────────────────────────────

# Node types that represent named symbols, per language
_SYMBOL_NODE_TYPES = {
    "python": {"function_definition", "class_definition"},
    "javascript": {"function_declaration", "class_declaration", "variable_declarator"},
    "typescript": {
        "function_declaration",
        "class_declaration",
        "variable_declarator",
        "interface_declaration",
    },
    "go": {"function_declaration", "method_declaration", "type_declaration"},
}

# Which child node type holds the name, per language + node type
_NAME_CHILD_TYPE = {
    "go_method_declaration": "field_identifier",  # Go methods use field_identifier
}

_LANG_FROM_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
}


def _get_parser(lang_name: str):
    """Return a tree-sitter (Language, Parser) pair for the given language name."""

    if lang_name == "python":
        import tree_sitter_python as ts_lang

        language = ts_lang.language()
    elif lang_name == "javascript":
        import tree_sitter_javascript as ts_lang

        language = ts_lang.language()
    elif lang_name == "typescript":
        import tree_sitter_typescript as ts_lang

        language = ts_lang.language_typescript()
    elif lang_name == "go":
        import tree_sitter_go as ts_lang

        language = ts_lang.language()
    elif lang_name == "tsx":
        import tree_sitter_typescript as ts_lang

        language = ts_lang.language_tsx()
    else:
        return None, None

    from tree_sitter import Parser

    parser = Parser(language)
    return language, parser


def _walk_symbols(node, lang_name: str, results: list, source_lines: list):
    """
    Recursively walk the AST and collect named symbol definitions.
    Appends dicts of {name, kind, start, end} to results.
    """
    symbol_types = _SYMBOL_NODE_TYPES.get(lang_name, set())

    if node.type in symbol_types:
        name = None
        kind = node.type.replace("_definition", "").replace("_declaration", "")

        # Special case: JS/TS variable_declarator — only capture if it's an arrow fn or fn expression
        if node.type == "variable_declarator":
            has_fn = any(
                c.type in ("arrow_function", "function", "function_expression")
                for c in node.children
            )
            if not has_fn:
                # not a function assignment, skip
                for child in node.children:
                    _walk_symbols(child, lang_name, results, source_lines)
                return
            kind = "function"

        # Go method: name is field_identifier child
        name_child_type = _NAME_CHILD_TYPE.get(f"{lang_name}_{node.type}", "identifier")

        for child in node.children:
            if child.type == name_child_type:
                name = child.text.decode("utf-8", errors="replace")
                break

        # TypeScript interface / class uses type_identifier
        if name is None:
            for child in node.children:
                if child.type == "type_identifier":
                    name = child.text.decode("utf-8", errors="replace")
                    break

        if name:
            results.append(
                {
                    "name": name,
                    "kind": kind,
                    "start": node.start_point[0] + 1,  # 1-indexed
                    "end": node.end_point[0] + 1,
                }
            )

    for child in node.children:
        _walk_symbols(child, lang_name, results, source_lines)


def parse_file_symbols(path: str, source_text: str) -> list:
    """
    Parse one file and return a list of symbol dicts:
      [{"name": "login", "kind": "function", "start": 200, "end": 280}, ...]

    Called lazily — only after grep has already identified this file as relevant.
    Results should be stored in AgentState.symbol_cache[path] to avoid re-parsing.

    Returns empty list for unsupported file types (silently — not an error).
    """
    ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    lang_name = _LANG_FROM_EXT.get(ext)
    if not lang_name:
        return []

    try:
        _, parser = _get_parser(lang_name)
        if parser is None:
            return []

        source_bytes = source_text.encode("utf-8", errors="replace")
        tree = parser.parse(source_bytes)
        source_lines = source_text.splitlines()

        results = []
        _walk_symbols(tree.root_node, lang_name, results, source_lines)
        return results

    except Exception as e:
        print(f"Warning: Failed to parse symbols in '{path}': {e}")
        return []  # parsing failure is non-fatal — agent falls back to grep


# ─────────────────────────────────────────────
# New tool 4: lookup_symbol
# ─────────────────────────────────────────────


def lookup_symbol(name: str, symbol_cache: dict) -> str:
    """
    Search the symbol cache for a symbol by name (case-insensitive partial match).
    Returns a formatted string listing all matches with file + line range.

    symbol_cache format: { "path/to/file.py": [{name, kind, start, end}, ...], ... }
    """
    name_lower = name.lower()
    matches = []

    for filepath, symbols in symbol_cache.items():
        for sym in symbols:
            if name_lower in sym["name"].lower():
                matches.append(
                    f"{sym['name']} ({sym['kind']}) in {filepath} "
                    f"— lines {sym['start']}-{sym['end']}"
                )

    if not matches:
        return f"No symbol matching '{name}' found in parsed files. Try grepping for it first."
    return "\n".join(matches)
