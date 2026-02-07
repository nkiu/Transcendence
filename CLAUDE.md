# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Transcendence is a procedural civilization simulation with LLM narration. It's a rules-first engine (DND-like) that generates emergent stories in a mini-universe with planets, civilizations, and deterministic game mechanics. The LLM (Ollama) acts purely as a narrator/scribe—it does not make decisions.

## Commands

```bash
# Run the simulation
python Transcendence.py

# Run the standalone DB viewer
python db_viewer.py path/to/sim.db

# Run tests
python -m pytest tests/
python tests/test_narrative_parser.py  # direct execution also works
```

## Architecture

```
Transcendence.py → lib/app.py (startup UI) → lib/sim.py (orchestrator)
                                                    ↓
                                          lib/rules_engine.py (deterministic rules)
                                                    ↓
                                          lib/db.py (SQLite persistence)
                                                    ↓
                                          lib/llm.py (LLM client, optional)
                                            ├── OllamaBackend (Ollama API)
                                            └── LlamaCppBackend (llama.cpp server)
```

**Key separation**: UI runs in main thread, simulation runs in worker thread, communication via queue.
**LLM backends**: Ollama (default) or llama.cpp. The llama.cpp backend supports parallel civ narration via `ThreadPoolExecutor`.

### Core Modules

- **lib/sim.py**: Simulation orchestrator. `_run_single_cycle()` is the main loop entry point.
- **lib/rules_engine.py**: Deterministic rule resolver with seeded RNG. `roll_cycle()` applies all rules.
- **lib/db.py**: SQLite schema and persistence. All state lives in the database.
- **lib/ui.py**: Tkinter interface with galaxy map, event log, civ tabs, stats display.
- **lib/llm.py**: LLM client with backend abstraction (`OllamaBackend`, `LlamaCppBackend`). Supports streaming and parallel requests (llama.cpp). Falls back gracefully if unavailable.
- **lib/narrative_parser.py**: Parses LLM output (LOG/GOD/AGENDA/STANCE/NEWS format).

### Extension Points

- **rulesets/**: Add new simulation rulesets by inheriting from `BaseRuleset`
- **prompts/**: Add new LLM prompt sets (auto-discovered via glob)
- **lib/events_catalog.json**: Add new events with effects, preconditions, weights
- **lib/ui_tabs.py**: Add new UI tabs via `UITabsMixin`

### Data Flow (per cycle)

1. Create cycle row in DB
2. Load live civ states
3. `RulesEngine.roll_cycle()`: roll events, apply effects, check extinction/collapse
4. Persist stats, events, marks, delayed effects
5. Generate LLM narratives (if enabled; parallel via ThreadPoolExecutor with llama.cpp)
6. Save full JSON snapshot to `cycle_records`
7. Update UI via queue

## Key Concepts

- **Marks**: Named flags on civs or world (e.g., "CosmicInstability", "Phase:Industrial")
- **Delayed Effects**: Stat changes that apply N cycles in the future
- **Tech Stages**: Progression via marks (Proto → Industrial → EarlySpace → Spacefaring)
- **Collapse Table**: D&D-style 1-12 roll for catastrophic outcomes when collapse triggers

## Environment Variables

- `LLM_BACKEND`: Backend selection — `ollama` (default) or `llamacpp`
- `OLLAMA_URL`: Ollama server URL (default `http://localhost:11434`)
- `OLLAMA_MODEL`: Model name (default `mistral:7b`)
- `LLAMACPP_URL`: llama.cpp server URL (default `http://localhost:8080`)
- `LLAMACPP_PARALLEL`: Number of parallel slots for concurrent civ narration (default `4`)
- `LLAMACPP_N_PREDICT`: Max tokens per request (default `4096`)
- `LLAMACPP_REPEAT_PENALTY`: Repetition penalty (default `1.3`)
- `LLM_CALL_TIMEOUT` / `OLLAMA_CALL_TIMEOUT`: Max request duration in seconds (default `240` for Ollama, `600` for llama.cpp)

## Conventions

- Snake_case for functions/variables, CamelCase for classes
- Type hints throughout (dataclasses, Optional, List, Dict)
- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`
- No external linting configured
