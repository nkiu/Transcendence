DEFAULT_EVENTS_PROMPT = (
    "You are an event engine for a living universe simulation. "
    "Cycle {cycle} context:\n{context}\n"
    "Rules: events must be feasible given the tech capability in context. "
    "Allow rare, plausible breakthroughs (e.g., first orbital mission) even if "
    "pre-space, but do NOT jump to interstellar travel or resource routes like "
    "helium-3 unless capability is explicitly interstellar. If spacefaring, "
    "stay within a system. Only allow breakthrough leaps when "
    "Innovation climate is propitious; include metadata.justification and "
    "metadata.rarity for any breakthrough event. "
    "Optional metadata fields: delayed_effects (list of {cycle_delay, civ, kind, delta}), "
    "world_marks (list of {civ, label, impact}). "
    "Return JSON list of 1-4 events. Each event must be an object with "
    "keys: kind, title, detail, metadata. Titles must be specific and "
    "reflect real effects (no generic labels). metadata must be a JSON object. "
    "If no valid events should happen, return an empty JSON list []."
)

DEFAULT_CIV_GEN_PROMPT = (
    "You are a science-fiction worldbuilder. Create unique civilizations "
    "for {count} planets. Planets (name, habitability 0-1):\n"
    "{planets_list}\n"
    "Return JSON list of objects with fields: name, color (hex), summary."
)

DEFAULT_CIV_THOUGHT_PROMPT = (
    "You are the mind of the civilization '{civ_name}'. "
    "It is cycle {cycle}. Context:\n{context}\n"
    "Return JSON only with keys: log, god, name, color, level, status. "
    "The 'log' must be 3-6 sentences describing real effects, not generic titles. "
    "The 'god' must be a short paragraph for the human observer. "
    "Only include name/color/level/status if you want to update them. "
    "Color must be hex (e.g. #ff8844). "
    "Do not mention or assume knowledge about other civilizations."
)

DEFAULT_MASTER_PROMPT = (
    "You are the Game Master AI observing a simulated universe. "
    "Cycle {cycle} summary context:\n{context}\n"
    "Return JSON only with keys: title, log, god, analysis. "
    "title must be a short, specific cycle name. "
    "log must be 4-6 sentences describing the real effects. "
    "analysis must explicitly analyze each civilization response. "
    "god is a short paragraph for the human observer."
)
