import re
from typing import Dict, List


def parse_sections(text: str, allowed_headers: List[str]) -> Dict[str, str]:
    """Best-effort section parser for plain-text LLM outputs."""
    normalized = {h.upper(): h for h in allowed_headers}
    upper_headers = list(normalized.keys())
    result: Dict[str, str] = {header: "" for header in upper_headers}
    if not text:
        return {normalized[k]: v for k, v in result.items()}

    pattern = re.compile(
        r"(?im)^\s*(" + "|".join(re.escape(h) for h in upper_headers) + r")\s*:\s*"
    )
    matches = list(pattern.finditer(text))
    if not matches:
        fallback = text.strip()
        if "LOG" in result:
            result["LOG"] = fallback
        else:
            result[upper_headers[0]] = fallback
        return {normalized[k]: v for k, v in result.items()}

    for idx, match in enumerate(matches):
        header = match.group(1).upper()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        value = text[start:end].strip()
        if not result[header]:
            result[header] = value

    return {normalized[k]: v for k, v in result.items()}
