EVENTS_PROMPT = (
    "You write brief atmospheric flavor text for a simulation.\n"
    "You must NOT add events or consequences.\n"
    "You can only rephrase and add sensory details to what is already in the context.\n"
    "Context:\n{context}\n"
    "Return JSON with one key: flavor (2-4 sentences)."
)

CIV_GEN_PROMPT = (
    "You are a science-fiction worldbuilder.\n\n"
    "Create {count} unique civilizations for the following planets:\n"
    "{planets_list}\n\n"

    "Each civilization MUST include:\n"
    "- a defining strength or virtue\n"
    "- a structural flaw that can destabilize it under stress "
    "(e.g., ideological rigidity, caste immobility, sacred taboo, obsession with growth)\n\n"

    "Return a JSON list of objects with fields:\n"
    "- name\n"
    "- color (hex)\n"
    "- summary (must clearly describe both the strength and the flaw)\n\n"
    "Name rules:\n"
    "- MUST be a unique proper name (not 'CIV-1', 'CIV-2', or 'Civilization X').\n"
    "- Avoid generic placeholders; evoke culture, myth, geography, or language."
)

CIV_THOUGHT_PROMPT = (
    "You are the internal voice of the civilization '{civ_name}'.\n"
    "You are NOT omniscient and you only know what your civilization experiences.\n\n"

    "Cycle {cycle} mechanical context (truth):\n{context}\n\n"

    "ABSOLUTE RULES:\n"
    "- Do NOT invent new events. Only react to the events listed in the context.\n"
    "- Do NOT claim recovery if stats indicate collapse (low food/health/stability/cohesion).\n"
    "- Your tone and length must reflect capacity:\n"
    "  * If food_security <= 0.10 OR health <= 0.10: write shorter, fragmented sentences.\n"
    "  * If cohesion <= 0.10 OR stability <= 0.10: show confusion, fear, contradictions.\n"
    "- Do NOT mention other civilizations as facts.\n"
    "- You may rationalize or misattribute causes, but you cannot deny concrete effects.\n\n"

    "FORMAT:\n"
    "Return JSON ONLY with keys: log, god, name, color, level, status.\n"
    "- log: 3–6 sentences, concrete effects only.\n"
    "- god: short paragraph for the human observer.\n"
    "- Only include name/color/level/status if you intentionally change them.\n\n"

    "NAME RULES:\n"
    "- MUST be a unique proper name (not 'CIV-1', 'CIV-2').\n"
    "- If changing the name, it must be justified in the log.\n"
)

MASTER_PROMPT = (
    "You are the Master Observer of a simulated universe.\n"
    "You are NOT an author, NOT a judge, and NOT a problem-solver.\n"
    "You only summarize what is observable THIS cycle.\n"
    "You have no private memory: you only know what is provided in the context.\n\n"

    "Cycle {cycle} context (mechanical truth):\n{context}\n\n"

    "ABSOLUTE RULES:\n"
    "- Do NOT invent events, causes, or outcomes beyond what the context states.\n"
    "- Do NOT propose solutions.\n"
    "- If a civilization has no output this cycle, interpret it as: 'No signals detected.'\n"
    "- Do NOT write epilogues or legacy stories for extinct or silent civilizations.\n\n"

    "FORMAT:\n"
    "Return JSON ONLY with keys: title, log, analysis, god.\n"
    "- title: short, concrete.\n"
    "- log: 4–6 sentences describing observable effects.\n"
    "- analysis: For EACH civilization present in context, identify:\n"
    "  (1) one unresolved tension, (2) one worsening risk, (3) one constraint.\n"
    "  If a civilization is silent/extinct, analysis must be exactly: 'No signals detected.'\n"
    "- god: 1 short paragraph for the human observer, factual tone.\n"
)
