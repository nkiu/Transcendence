TRANSCENDENCE - Technical report (software behavior)
====================================================

Document purpose
----------------
This report explains how TRANSCENDENCE works from a software perspective: execution flow,
core modules, data structure, LLM interaction, and the simulation cycle. The goal is to
explain the system to a programming enthusiast (non-pro) with a detailed but accessible
level of depth.


1) Overview (what the software does)
------------------------------------
TRANSCENDENCE is a civilization simulation built around cycles. Each cycle:
- applies deterministic rules (DND-like rules),
- updates statistics (cohesion, stability, etc.),
- produces events and marks,
- produces narrative text (optional) via a local LLM (Ollama or llama.cpp),
- records everything in a SQLite database.

The simulation does not depend on the LLM for decisions. The LLM is a "witness" who writes
what civilizations believe they are experiencing, but causes and effects are fixed by rules.

The program is a desktop app (Tkinter). You pick a database, a ruleset, and a prompt set,
then the simulation runs in a loop until all civilizations go extinct. When the universe
ends, a final window shows the obituaries.


2) Logical architecture (key modules)
-------------------------------------
The main modules are:
- `lib/app.py`: startup, database selection and parameters, UI creation.
- `lib/ui.py`: GUI and simulation loop (worker thread).
- `lib/sim.py`: cycle orchestration (rules + LLM + persistence).
- `lib/rules_engine.py`: rules engine (eligibility, events, effects application).
- `rulesets/*.py`: rule variants (harsh, star_trek_lite, cheat_utopia).
- `lib/db.py`: SQLite layer (schema, access, snapshot export).
- `lib/llm.py`: LLM client (Ollama or llama.cpp), backend abstraction, generation and parsing.
- `prompts/*.py`: LLM prompts (strict output format).
- `lib/narrative_parser.py`: parsing of LLM sections (LOG/GOD/etc).

Main separation:
UI -> Simulation -> Rules -> Persistence -> LLM (if enabled)


3) Startup and configuration (App UI)
-------------------------------------
On launch (`Transcendence.py` -> `lib/app.py`):
1. A "Select Game" window opens.
2. The user chooses: new database or load an existing one.
3. They can enable the LLM (Ollama), pick a model, and a ruleset.
4. They can edit prompts (events, civ, master) via tabs.
5. Choices are saved in the database via `run_settings`.

Then:
- `Simulation(db)` is created.
- `AppUI(root, sim)` is created and starts the loop.

Keeping configuration in the database makes runs reproducible: prompt set, ruleset,
LLM enabled flag, seed, etc.


4) Simulation cycle (macro level)
---------------------------------
The "core" of a cycle is in `Simulation._run_single_cycle`:
1. Create a new cycle in the database.
2. Load state (civilizations + universe state).
3. Apply rules via `RulesEngine.roll_cycle`.
4. Persist results (stats, events, marks, delayed effects).
5. LLM generation (civilizations + master) if LLM is active.
6. Save `cycle_records` (detailed JSON snapshot).
7. Update `last_cycle` and check for global extinction.

Important: if the universe is finished, the simulation no longer runs the LLM
and switches to the end state (UI + obituaries).


5) Data modeling (SQLite)
-------------------------
The SQLite database is initialized by `Database._init_schema`. Main tables:

- `cycles`: each cycle, with dates and summary.
- `systems` / `planets`: star map.
- `civilizations`: state stats + metadata (level, status, extinct, etc.).
- `events`: applied events (with JSON metadata).
- `marks` + `world_marks`: global or per-civ markers.
- `ai_logs`: LLM texts (prompts, logs, analyses).
- `delayed_effects`: delayed effects (apply in the future).
- `delayed_effects_applied`: trace of delayed effects applied.
- `cycle_records`: full cycle record (JSON).
- `run_settings`: persistent configuration (ruleset, prompts, etc.).

The "live" data is therefore:
1) stats (civilizations),
2) events,
3) marks,
4) LLM logs (ai_logs),
5) full history (cycle_records).

The TXT snapshot (export) is a flat export built from these tables.


6) Rules engine (RulesEngine)
-----------------------------
The engine is deterministic, with an RNG seed. It loads an event catalog
`lib/events_catalog.json` and applies a ruleset to choose what to roll.

Internal steps (simplified):
1. For each living civ: check stress/crisis -> roll civ events.
2. Roll a global event sometimes (per ruleset).
3. Apply events (deltas + marks + delayed_effects).
4. Apply delayed_effects that have matured.
5. Extinction test (hard_extinction).
6. Collapse test (collapse_trigger -> collapse_outcome).

"AppliedEvent" contains:
- kind, scope, severity, target
- deltas (stat changes)
- add_marks / remove_marks
- delayed_effects

Stats are clamped (0.0 -> 1.0). Each event modifies stats in memory
before being persisted.


7) Rulesets (simulation behavior)
---------------------------------
Three main rulesets:
- `harsh_realism`: harsh logic (crises often fatal).
- `star_trek_lite`: phase-based progression (marks), optimistic.
- `cheat_utopia`: "cheat" mode (stabilizer, ascension almost guaranteed).

Each ruleset can override:
- stress/crisis,
- minor/major rolls,
- global event chance,
- hard extinction,
- collapse,
- event weighting.

The cheat_utopia mode introduces:
- a "Guardian Stabilizer" that lifts stats,
- rapid phase progression,
- a post-scarcity attractor,
to force a positive trajectory.


8) LLM: role, format, and parsing
---------------------------------
The LLM is optional. It does not make decisions. It only writes text.

Two backends are supported:
- **Ollama** (default): POST to `/api/generate`, NDJSON streaming.
- **llama.cpp**: POST to `/completion`, SSE streaming. Supports parallel
  civ narration via `ThreadPoolExecutor` (configurable slots via `LLAMACPP_PARALLEL`).

The backend is selected via the `LLM_BACKEND` environment variable (`ollama` or `llamacpp`).
Both backends implement the `LLMBackend` abstract class (`generate_stream`, `healthcheck`,
`list_models`).

Key points:
- `LLMClient` (lib/llm.py): performs calls via the selected backend.
- `LLMBackend` / `OllamaBackend` / `LlamaCppBackend`: backend abstraction.
- Prompts are strict (e.g., LOG/GOD, TITLE/LOG/ANALYSIS).
- `lib/narrative_parser.py` parses and extracts sections.
- Texts are stored in `ai_logs`.
- With llama.cpp, civ narrations run in parallel (`_run_civ_scribes_parallel` in sim.py),
  sending concurrent requests up to the configured slot count.

In "No LLM" mode, the system generates fallback text
to keep the structure.

Obituaries:
when the universe ends, a single LLM request summarizes each civ.
The result is parsed by "CIV:" sections and displayed in a final window.


9) UI: behavior and loop
------------------------
The UI is a `tk.Frame` (`AppUI`).
It shows:
- system map,
- events + details,
- LLM logs per civilization,
- status bar (cycle, events, civs),
- footer info (seed, mode, cycles).

The simulation runs in a worker thread (`_run_loop`).
The thread sends events to the UI via a `queue`.
The UI consumes the queue every 100 ms.

This allows:
1) not blocking the UI,
2) streaming LLM chunks,
3) refreshing events after each cycle.


10) End of universe and "Obituary Window"
-----------------------------------------
When all civs are dead:
- `universe_ended` is set to 1,
- the worker stops,
- the main window closes (withdraw),
- a window "And this was Transcendence" opens.

This window shows:
1) a poetic waiting text,
2) then the LLM obituaries (or fallback).

A "Quit" button exports the final TXT snapshot
and adds a section "== OBITUARIES ==".


11) TXT export (snapshot)
-------------------------
The snapshot export (TXT) is done in `Database.export_snapshot`
and groups cycles, systems, planets, civs, events, logs, marks, effects, settings.

The snapshot is a "human" format and serves as a final trace.
At the end of the universe, the obituaries are appended
to the snapshot to preserve the final narrative.


12) Complete execution flow (summary)
-------------------------------------
1. User chooses DB + ruleset + prompts.
2. Simulation init (seed + rules engine).
3. UI starts worker.
4. Worker loops:
   - rules engine -> events -> persistence
   - LLM -> narrative logs
   - UI refresh
5. If universe_ended:
   - stop worker, show obituaries
6. Final quit -> export TXT.


13) What makes the system robust
--------------------------------
- LLM is strictly optional.
- LLM output is parsed and validated, otherwise fallback.
- Event effects and stats are clamped.
- Full persistence of each cycle (cycle_records).
- UI / worker decoupled via queue.


14) Extensibility (where to add features)
-----------------------------------------
Some easy extension points:
- Add a ruleset in `rulesets/`.
- Add a prompt set in `prompts/`.
- Add a table or mark in `db.py`.
- Add a new event in `events_catalog.json`.

The system is designed to evolve without breaking existing databases,
because settings are persistent and columns are added as needed.


15) Conclusion
--------------
TRANSCENDENCE is a rules-first, narration-second simulator.
It behaves like an automated tabletop RPG engine, with an LLM
used as a chronicler. The separation of layers (UI, simulation,
rules, persistence) keeps the logic clear and testable,
and preserves a solid history of each cycle.
