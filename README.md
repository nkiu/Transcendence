# Transcendence

A tiny, living universe you can **watch**. 
Procedural star systems, emergent civilizations, and a Game Master AI narrating what unfolds.

This project is deliberately playful and exploratory: a sandbox where you observe, export, and study the stories your mini‑cosmos invents.

## What it does

- Generates a 10‑system universe with planets and physical traits
- Spawns multiple civilizations with evolving stats and tech stages
- Uses a local LLM (Ollama) to drive events + narration
- Displays a sci‑fi control panel UI (Tkinter) with live logs and visuals
- Exports full simulation snapshots to `.txt`

## Requirements

- Python 3.10+
- Ollama running locally (recommended)

## Quick start

```bash
python app.py
```

The start screen lets you enable Ollama and pick a model without any exports.
If Ollama is off, the sim runs but produces minimal AI output.

## Choosing a model

When you launch the app, the **Start Screen** lets you:

- Create or load a game
- Check Ollama status
- Pick a model from your local Ollama list

You can use smaller/quantized models for speed (e.g. `mistral:7b-instruct-q4_0` or `mistral:3b`).

## What you can see

- **Galaxy map**: systems, links, pulses, and events
- **System panel**: orbiting planets + hover details
- **Civ tabs**: live LLM streams per civilization + Master AI
- **Stats tab**: hidden variables (cohesion, inequality, eco pressure, innovation, stability)
- **World tab**: long‑term scars + delayed effects

## Export snapshots

Click **Export** to write a full timeline snapshot next to the `.db`:

```
YYYYMMDD_HHMMSS_<game>_cycle<N>.txt
```

Includes cycles, systems, planets, civilizations, events, AI logs, world marks, and delayed effects.

## Design philosophy

- **Fun over perfection** — weirdness is a feature.
- **Exploration first** — observe, export, analyze.
- **Small, readable codebase** — tweak and iterate fast.

## Tips

- If the UI feels busy, pause, inspect a system, then resume.
- Use smaller models to keep the live stream responsive.
- Export snapshots to compare narrative arcs between runs.

## Roadmap ideas

- Deeper simulation vs narration separation
- Better tech pacing + rare breakthroughs
- Optional player interventions (“oracle” mode)

## License

MIT (or your preferred license)
