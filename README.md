# Transcendence

A tiny, living universe you can **watch**.  
Procedural star systems, emergent civilizations, and a Game Master AI narrating what unfolds.

This project is deliberately playful and exploratory: a sandbox where you observe, export, and study the stories your mini‑cosmos invents.

## What it does

- Generates a 10‑system universe with planets and physical traits
- Spawns multiple civilizations with evolving hidden stats + tech stages
- Uses a local LLM (Ollama) to drive events + narration
- Displays a sci‑fi control panel UI (Tkinter) with live logs and visuals
- Exports full simulation snapshots to `.txt`
- Supports player directives that influence the next cycle
- Includes a Chaotic AI layer that biases trajectories without “villains”

## LLM roles (who does what)

- **Civilization AI**: one instance per civ. Reacts from local context only (stats, memory, planet). Produces logs + optional updates (name/color/status). It does not know other civs unless the simulation gives that info.
- **Master AI**: the “vice‑god.” Builds the cycle title, narrates consequences, and analyzes the civ responses. It does not invent state directly; it reflects the simulation.
- **Chaotic AI**: a hidden personality disturbance. Rare, local, and ambiguous. It biases a single civ’s trajectory for a few cycles (stabilizing or destabilizing) without being named in the narrative. You can see it in the UI; the Master AI cannot.

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

- Events (simulation engine)
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
- **Stats tab**: cohesion, inequality, eco pressure, innovation, stability
- **World tab**: scars, delayed effects, run settings
- **Chaos tab**: chaotic profile logs (separate from Master view)
- **Player directive**: queued input applied at next cycle
- **Loading screen**: non‑blocking initialization for new runs

## Snapshot export

Click **Export** to write a full timeline snapshot next to the `.db`:

```
YYYYMMDD_HHMMSS_<game>_cycle<N>.txt
```

Includes cycles, systems, planets, civilizations, events, AI logs, world marks, delayed effects, chaos profiles, and run settings.

## Notes on simulation quality

LLMs are great at narrative flavor but can drift or invent state. This project keeps:

- Hidden stats and tech stages to stabilize continuity
- Strict JSON outputs for simulation steps
- Master narration that reflects simulation rather than rewriting it

## Design philosophy

- **Fun over perfection** — weirdness is a feature.
- **Exploration first** — observe, export, analyze.
- **Small, readable codebase** — tweak and iterate fast.

## Roadmap ideas

- Deeper simulation vs narration separation
- Better tech pacing + rare breakthroughs
- Optional player interventions (“oracle” mode)

## License

MIT (or your preferred license)
