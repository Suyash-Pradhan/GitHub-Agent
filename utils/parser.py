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
