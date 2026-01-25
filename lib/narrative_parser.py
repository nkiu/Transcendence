import re
from typing import Dict, List


AGENDA_TOKENS = {"SURVIVE", "REFORM", "EXPLORE", "DOMINATE", "WITHDRAW"}
STANCE_TOKENS = {"PRAGMATIC", "ZEALOUS", "CYNICAL", "COMPASSIONATE", "NIHILISTIC"}


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


def parse_agenda(text: str) -> str:
    if not text:
        return "SURVIVE"
    match = re.search(r"(?im)^\s*AGENDA\s*:\s*([A-Z]+)\s*$", text)
    if not match:
        return "SURVIVE"
    token = match.group(1).strip().upper()
    if token in AGENDA_TOKENS:
        return token
    return "SURVIVE"


def parse_stance(text: str) -> str:
    if not text:
        return "PRAGMATIC"
    match = re.search(r"(?im)^\s*STANCE\s*:\s*([A-Z]+)\s*$", text)
    if not match:
        return "PRAGMATIC"
    token = match.group(1).strip().upper()
    if token in STANCE_TOKENS:
        return token
    return "PRAGMATIC"


def strip_control_lines(text: str) -> str:
    if not text:
        return text
    cleaned = re.sub(r"(?im)^\s*AGENDA\s*:\s*[A-Z]+\s*$\n?", "", text)
    cleaned = re.sub(r"(?im)^\s*STANCE\s*:\s*[A-Z]+\s*$\n?", "", cleaned)
    return cleaned.strip()
