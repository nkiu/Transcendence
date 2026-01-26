# Transcendence

A tiny, living universe you can **watch**.  
Procedural star systems, emergent civilizations, and a Game Master AI narrating what unfolds.

This project is deliberately playful and exploratory: a sandbox where you observe, export, and study the stories your mini‑cosmos invents.  
It is closer to an **LLM experiment** than a traditional simulator or game — the point is to see how models improvise world dynamics they were never trained to simulate.

## What it does

- Generates a 10‑system universe with planets and physical traits
- Spawns multiple civilizations with evolving hidden stats + tech stages
- Tracks stage progression with a continuous progress meter
- Adds internal dynamics (elite_power, legitimacy, extraction_rate)
- Uses a deterministic rules engine to drive events + consequences
- Uses a local LLM (Ollama) only as a narrator/scribe (plain text, no JSON)
- Supports a fully deterministic No‑LLM mode with fallback narration
- Adds constrained intent tokens (AGENDA/STANCE/NEWS) that only bias weights
- Models exploration missions, beacons, and first contact events
- Includes legitimacy crisis regimes with specific unrest events
- Displays a sci‑fi control panel UI (Tkinter) with live logs and visuals
- Exports full simulation snapshots to `.txt`
- Supports player directives that influence the next cycle
- Includes a rules layer with dice/thresholds and extinction logic

## Roles (who does what)

- **Rules Engine (DND-like)**: the absolute supervisor of reality. It rolls events, applies consequences, tracks delayed effects, and handles extinction. It is deterministic with a seed.
- **Civilization AI**: one instance per civ. Reacts only to mechanical outcomes. Produces plain‑text logs and constrained intent tokens.
- **Master AI**: the “vice‑god.” Summarizes the cycle using only mechanical context. It never invents outcomes.

## Requirements

- Python 3.10+
- Ollama running locally (recommended)

## Quick start

```bash
python Transcendence.py
```

The start screen lets you enable Ollama and pick a model without any exports.
If Ollama is off (No LLM), the sim runs with deterministic fallback narration and intent proxies.

You can also open the standalone DB viewer:

```bash
python db_viewer.py path/to/sim.db
```

## Prompts (editable per save)

All key prompts are editable from the **Prompts** tab on the start screen:

- Flavor (optional, currently unused)
- Civ seed (naming)
- Civ narrator
- Master observer

These prompts are stored per save in SQLite and reloaded automatically when you **Load Game**.
Defaults live in `prompts/prompts_design.py`, with alternate versions (e.g. `prompts/prompt_design_v4.py`).
You can choose the prompt set at start, or keep the saved prompts from the DB.

## Player directives

You can inject a one‑off directive into the next cycle:

- Type your instruction (e.g., “The people doubt their gods and abandon ritual”)
- Choose a target civilization (or all)
- The directive is enforced as a hard constraint in the next civ log


## What you can see

- **Galaxy map**: systems, links, pulses, and events
- **Map overlay**: missions (dashed), routes (solid), beacons (rings)
- **System panel**: orbiting planets + hover details
- **Civ tabs**: live LLM streams per civilization + Master AI (plain text)
- **Stats tab**: core stats + stage/progress + internal dynamics + agenda/stance/news
- **World tab**: scars, delayed effects, run settings
- **Rules tab**: rules engine status (seed, cooldowns, marks, pending effects, recent rules events)
- **Missions tab**: active missions and outcomes
- **Player directive**: queued input applied at next cycle
- **Loading screen**: non‑blocking initialization for new runs

## Snapshot export

Click **Export** to write a full timeline snapshot next to the `.db`:

```
YYYYMMDD_HHMMSS_<game>_cycle<N>.txt
```

Includes cycles, systems, planets, civilizations, events, AI logs, world marks, delayed effects (queued + applied), cycle records, rules state, and run settings.

## Notes on simulation quality

LLMs are great at narrative flavor but can drift or invent state. This project keeps:

- A deterministic rules engine that owns reality
- Hidden stats to stabilize continuity
- Strict plain‑text headers for LLM narration (LOG/GOD/NEWS/AGENDA/STANCE)
- Strict master output format (TITLE/SUMMARY/WORLD/NOTES) with auto‑repair
- Silence on extinction (no LLM output)

## DB viewer

Browse snapshots and narratives without opening the UI:

```bash
python db_viewer.py path/to/sim.db
```

The viewer includes cycle summaries, mission markers, narrative tabs, and a plot view.

## Design philosophy

- **Fun over perfection** — weirdness is a feature.
- **Exploration first** — observe, export, analyze.
- **Experiment, not simulation** — this is about LLM behavior, not realism.
- **Small, readable codebase** — tweak and iterate fast.

## Roadmap ideas

- Deeper simulation vs narration separation
- Better tech pacing + rare breakthroughs
- Optional non‑LLM “classic” AI systems (later, maybe)
- Optional player interventions (“oracle” mode)

## License

MIT License, (c) 2026 Denis Prim
