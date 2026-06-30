import re

FILE_BLOCK_RE = re.compile(
    r"^FILE:\s*(?P<path>[^\r\n]+?)[ \t]*```(?:[a-zA-Z0-9_+-]+)?[ \t]*\r?\n?",
    re.MULTILINE,
)


def _extract_file_blocks(text: str) -> list[tuple[str, str]]:
    blocks = []
    matches = list(FILE_BLOCK_RE.finditer(text))
    for index, match in enumerate(matches):
        path = match.group("path").strip()
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[match.end() : next_start].rstrip()

        if content.endswith("```"):
            content = content[:-3].rstrip()

        if path and content:
            blocks.append((path, content + "\n"))
    return blocks
