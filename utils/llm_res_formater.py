# utils/llm.py

def get_text(response_or_content):
    content = getattr(response_or_content, "content", response_or_content)

    if isinstance(content, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )

    if isinstance(content, str):
        return content

    return str(content)