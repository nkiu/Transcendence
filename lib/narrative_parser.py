import logging
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

    # Match headers at line start OR after sentence-ending punctuation
    pattern = re.compile(
        r"(?i)(?:^|\n|(?<=[.!?])\s+)\s*(" + "|".join(re.escape(h) for h in upper_headers) + r")\s*:\s*"
    )
    matches = list(pattern.finditer(text))
    if not matches:
        fallback = text.strip()
        if "LOG" in result:
            result["LOG"] = fallback
        else:
            result[upper_headers[0]] = fallback
        return {normalized[k]: v for k, v in result.items()}

    # Check if there's a prelude (text before first header)
    has_prelude = matches[0].start() > 0 and text[:matches[0].start()].strip()

    for idx, match in enumerate(matches):
        header = match.group(1).upper()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        value = text[start:end].strip()

        # For the last section, if there was a prelude, strip potential postlude
        if idx == len(matches) - 1 and has_prelude:
            # Find the last sentence that looks like content (ends with punctuation)
            lines = value.split('\n')
            content_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped:
                    content_lines.append(stripped)
                    # Stop after first complete content line for last section with prelude
                    if stripped.endswith(('.', '!', '?')):
                        break
            value = '\n'.join(content_lines) if content_lines else value

        if not result[header]:
            result[header] = value

    return {normalized[k]: v for k, v in result.items()}


def parse_agenda(text: str) -> str:
    if not text:
        logging.warning("AGENDA defaulted to SURVIVE (empty narration).")
        return "SURVIVE"
    match = re.search(r"(?im)^\s*AGENDA\s*:\s*([A-Z]+)\s*$", text)
    if not match:
        logging.warning("AGENDA defaulted to SURVIVE (missing token).")
        return "SURVIVE"
    token = match.group(1).strip().upper()
    if token in AGENDA_TOKENS:
        return token
    logging.warning("AGENDA defaulted to SURVIVE (invalid token: %s).", token)
    return "SURVIVE"


def parse_stance(text: str) -> str:
    if not text:
        logging.warning("STANCE defaulted to PRAGMATIC (empty narration).")
        return "PRAGMATIC"
    match = re.search(r"(?im)^\s*STANCE\s*:\s*([A-Z]+)\s*$", text)
    if not match:
        logging.warning("STANCE defaulted to PRAGMATIC (missing token).")
        return "PRAGMATIC"
    token = match.group(1).strip().upper()
    if token in STANCE_TOKENS:
        return token
    logging.warning("STANCE defaulted to PRAGMATIC (invalid token: %s).", token)
    return "PRAGMATIC"


def parse_news(text: str) -> str:
    if not text:
        logging.warning("NEWS defaulted (empty narration).")
        return "Quiet cycle; tensions persist."
    match = re.search(r"(?im)^\s*NEWS\s*:\s*(.+?)\s*$", text)
    if not match:
        logging.warning("NEWS defaulted (missing token).")
        return "Quiet cycle; tensions persist."
    return match.group(1).strip() or "Quiet cycle; tensions persist."


def strip_control_lines(text: str) -> str:
    if not text:
        return text
    cleaned = re.sub(r"(?im)^\s*AGENDA\s*:\s*[A-Z]+\s*$\n?", "", text)
    cleaned = re.sub(r"(?im)^\s*STANCE\s*:\s*[A-Z]+\s*$\n?", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*NEWS\s*:\s*.*\s*$\n?", "", cleaned)
    return cleaned.strip()


MASTER_HEADERS = ("TITLE", "SUMMARY", "WORLD", "NOTES")
FORBIDDEN_MARKDOWN = (
    "**",
    "```",
)


def validate_master_output(text: str) -> List[str]:
    reasons: List[str] = []
    if not text or not text.strip():
        return ["empty output"]
    stripped = text.lstrip()
    if not stripped.startswith("TITLE:"):
        reasons.append("output must start with TITLE:")
    upper = text.upper()
    positions = {}
    for header in MASTER_HEADERS:
        count = upper.count(f"{header}:")
        if count == 0:
            reasons.append(f"missing header {header}")
        elif count > 1:
            reasons.append(f"duplicate header {header}")
        idx = upper.find(f"{header}:")
        if idx != -1:
            positions[header] = idx
    order = [positions.get(h) for h in MASTER_HEADERS if h in positions]
    if order and order != sorted(order):
        reasons.append("headers out of order")
    for token in FORBIDDEN_MARKDOWN:
        if token in text:
            reasons.append(f"forbidden markdown token {token}")
    for line in text.splitlines():
        trimmed = line.lstrip()
        if trimmed.startswith("#"):
            reasons.append("markdown header detected")
            break
        if trimmed.startswith("- ") or trimmed.startswith("* ") or trimmed.startswith("> "):
            reasons.append("markdown list/quote detected")
            break
    return reasons
