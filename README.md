# Transcendence

A tiny, living universe you can **watch**.  
Procedural star systems, emergent civilizations, and a Game Master AI narrating what unfolds.

This project is deliberately playful and exploratory: a sandbox where you observe, export, and study the stories your mini‑cosmos invents.  
It is closer to an **LLM experiment** than a traditional simulator or game — the point is to see how models improvise world dynamics they were never trained to simulate.

## What it does

- Generates a 10‑system universe with planets and physical traits
- Spawns multiple civilizations with evolving hidden stats + tech stages
- Uses a deterministic rules engine to drive events + consequences
- Uses a local LLM (Ollama) only as a narrator/scribe
- Displays a sci‑fi control panel UI (Tkinter) with live logs and visuals
- Exports full simulation snapshots to `.txt`
- Supports player directives that influence the next cycle
- Includes a rules layer with dice/thresholds and extinction logic

## Roles (who does what)

- **Rules Engine (DND-like)**: the absolute supervisor of reality. It rolls events, applies consequences, tracks delayed effects, and handles extinction. It is deterministic with a seed.
- **Civilization AI**: one instance per civ. Reacts only to the mechanical outcomes from the rules engine. Produces logs + optional updates (name/color/status).
- **Master AI**: the “vice‑god.” Summarizes the cycle using only the provided mechanical context. It never invents outcomes.

## Requirements

- Python 3.10+
- Ollama running locally (recommended)

## Quick start

```bash
python app.py
```

The start screen lets you enable Ollama and pick a model without any exports.
If Ollama is off, the sim runs but produces minimal AI output.

## Prompts (editable per save)

All key prompts are editable from the **Prompts** tab on the start screen:

- Flavor (optional, currently unused)
- Civ generation
- Civ thoughts
- Master narration

These prompts are stored per save in SQLite and reloaded automatically when you **Load Game**.
Defaults live in `prompts_design.py`, with alternate versions (e.g. `prompt_design_v2.py`).
You can choose the prompt set at start, or keep the saved prompts from the DB.

## Player directives

You can inject a one‑off directive into the next cycle:

- Type your instruction (e.g., “The people doubt their gods and abandon ritual”)
- Choose a target civilization (or all)
- The directive is enforced as a hard constraint in the next civ log


## What you can see

- **Galaxy map**: systems, links, pulses, and events
- **System panel**: orbiting planets + hover details
- **Civ tabs**: live LLM streams per civilization + Master AI
- **Stats tab**: cohesion, inequality, eco pressure, innovation, stability, food, health
- **World tab**: scars, delayed effects, run settings
- **Rules tab**: rules engine status (seed, cooldowns, marks, pending effects, recent rules events)
- **Player directive**: queued input applied at next cycle
- **Loading screen**: non‑blocking initialization for new runs

## Snapshot export

Click **Export** to write a full timeline snapshot next to the `.db`:

```
YYYYMMDD_HHMMSS_<game>_cycle<N>.txt
```

Includes cycles, systems, planets, civilizations, events, AI logs, world marks, delayed effects (queued + applied), rules state, and run settings.

## Notes on simulation quality

LLMs are great at narrative flavor but can drift or invent state. This project keeps:

- A deterministic rules engine that owns reality
- Hidden stats to stabilize continuity
- Strict JSON outputs for LLM narration only
- Silence on extinction (no LLM output)

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

MIT (or your preferred license)
