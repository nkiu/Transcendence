import datetime as dt
import json
import os
import random
from typing import Callable, Dict, List, Optional, Tuple

from lib.db import Database, Planet, StarSystem
from lib.llm import LLMClient
from lib.narrative_parser import parse_sections
from lib.rules_engine import (
    AppliedEvent,
    CivilizationState,
    CivStats,
    DelayedEffect,
    RulesEngine,
    UniverseState,
)
from rulesets import create_ruleset, list_available_rulesets
from prompts.prompts_design import (
    DEFAULT_CIV_GEN_PROMPT,
    DEFAULT_CIV_THOUGHT_PROMPT,
    DEFAULT_EVENTS_PROMPT,
    DEFAULT_MASTER_PROMPT,
)


class Simulation:
    """Orchestrates cycle progression, persistence, and LLM-driven narration."""
    def __init__(self, db: Database) -> None:
        self.db = db
        mode = "ollama" if os.environ.get("OLLAMA_ON", "0") == "1" else "stub"
        self.llm = LLMClient(mode=mode)
        self.prompt_seeds = self._load_prompt_seeds()
        self.prompt_templates = self._load_prompt_templates()
        self.seed = self._init_seed()
        available_rulesets = {name for name, _ in list_available_rulesets()}
        stored_ruleset = self.db.get_setting("ruleset_name") or "harsh_realism"
        if stored_ruleset not in available_rulesets:
            stored_ruleset = "harsh_realism"
            self.db.set_setting("ruleset_name", stored_ruleset)
        self.ruleset_name = stored_ruleset
        catalog_path = os.path.join(os.path.dirname(__file__), "events_catalog.json")
        self.rules_engine = RulesEngine(
            catalog_path, self.seed, create_ruleset(self.ruleset_name)
        )
        self._ensure_universe()
        self.LEGACY_JSON_MODE = False

    def run_cycles(self, count: int = 1) -> int:
        """Run N full cycles without streaming callbacks."""
        if count < 1:
            return 0
        cycles_completed = 0
        for _ in range(count):
            self._run_single_cycle()
            cycles_completed += 1
        return cycles_completed

    def run_cycle_stream(
        self, stream_callback: Optional[Callable[[Dict[str, str]], None]] = None
    ) -> int:
        """Run a single cycle and stream chunks to the UI."""
        return self._run_single_cycle(stream_callback)

    def is_ended(self) -> bool:
        return self._universe_ended()

    def _run_single_cycle(
        self, stream_callback: Optional[Callable[[Dict[str, str]], None]] = None
    ) -> int:
        """Cycle flow: rules engine → LLM scribes (if alive) → master report."""
        if self._universe_ended():
            return self.db.get_latest_cycle_id()
        cycle_id = self._create_cycle()
        if self._apply_player_commands(cycle_id):
            self.db.set_setting("last_cycle", str(cycle_id))
            return cycle_id

        civ_states = self._load_civ_states()
        universe_state = self._load_universe_state(cycle_id)
        civ_events, global_events, delayed_applied = self.rules_engine.roll_cycle(
            civ_states, universe_state
        )
        self._persist_rules_results(
            cycle_id,
            civ_states,
            universe_state,
            civ_events,
            global_events,
            delayed_applied,
        )
        if self._check_universe_extinction(cycle_id, civ_states):
            self.db.set_setting("last_cycle", str(cycle_id))
            return cycle_id

        civ_reports = self._run_civ_scribes(
            cycle_id, civ_states, civ_events, stream_callback
        )
        master_report = self._run_master_scribe(
            cycle_id, civ_states, global_events, civ_reports, stream_callback
        )
        self._store_cycle_record(
            cycle_id,
            civ_states,
            universe_state,
            civ_events,
            global_events,
            civ_reports,
            master_report,
            delayed_applied,
        )
        self.db.set_setting("last_cycle", str(cycle_id))
        return cycle_id

    def _create_cycle(self) -> int:
        now = dt.datetime.utcnow().isoformat() + "Z"
        return self.db.add_cycle(now, now, "Cycle completed")

    def _universe_ended(self) -> bool:
        return self.db.get_setting("universe_ended") == "1"

    def _load_universe_state(self, cycle_id: int) -> UniverseState:
        end_reason = self.db.get_setting("universe_end_reason")
        ended = self.db.get_setting("universe_ended") == "1"
        marks = self.db.list_marks(None)
        pending = []
        for effect in self.db.list_all_delayed_effects():
            remaining = max(0, effect.cycle_due - cycle_id + 1)
            target = str(effect.civ_id) if effect.civ_id is not None else "global"
            payload = effect.payload if isinstance(effect.payload, dict) else {}
            deltas = payload.get("deltas", payload)
            add_marks = payload.get("add_marks", [])
            remove_marks = payload.get("remove_marks", [])
            pending.append(
                DelayedEffect(
                    cycle_delay=remaining,
                    target=target,
                    deltas=deltas if isinstance(deltas, dict) else {},
                    add_marks=add_marks if isinstance(add_marks, list) else [],
                    remove_marks=remove_marks if isinstance(remove_marks, list) else [],
                )
            )
        cooldowns = {}
        raw = self.db.get_setting("event_cooldowns")
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    cooldowns = {str(k): int(v) for k, v in data.items()}
            except json.JSONDecodeError:
                cooldowns = {}
        return UniverseState(
            cycle=cycle_id,
            ended=ended,
            end_reason=end_reason,
            rng_seed=self.seed,
            global_marks=marks,
            global_pending_effects=pending,
            cooldowns=cooldowns,
        )

    def _load_civ_states(self) -> List[CivilizationState]:
        civ_states = []
        for civ in self.db.list_civilizations():
            stats = CivStats(
                eco_pressure=civ.eco_pressure,
                inequality=civ.inequality,
                cohesion=civ.cohesion,
                stability=civ.stability,
                innovation=civ.innovation,
                food_security=civ.food_security,
                health=civ.health,
            )
            civ_states.append(
                CivilizationState(
                    id=str(civ.id),
                    name=civ.name,
                    color=civ.color,
                    alive=bool(civ.extinct == 0),
                    extinct=bool(civ.extinct == 1),
                    extinct_cycle=civ.extinct_cycle,
                    stats=stats,
                    marks=self.db.list_marks(civ.id),
                    consecutive_extreme_eco=civ.consecutive_extreme_eco,
                    consecutive_extreme_unrest=civ.consecutive_extreme_unrest,
                    consecutive_famine=civ.consecutive_famine,
                    consecutive_zero_stability=civ.consecutive_zero_stability,
                )
            )
        return civ_states

    def _persist_rules_results(
        self,
        cycle_id: int,
        civ_states: List[CivilizationState],
        universe: UniverseState,
        civ_events: List[AppliedEvent],
        global_events: List[AppliedEvent],
        delayed_applied: List[DelayedEffect],
    ) -> None:
        for civ in civ_states:
            self.db.update_civilization(
                int(civ.id),
                extinct=1 if civ.extinct or not civ.alive else 0,
                extinct_cycle=civ.extinct_cycle,
                status=self._derive_status(civ),
                cohesion=civ.stats.cohesion,
                inequality=civ.stats.inequality,
                eco_pressure=civ.stats.eco_pressure,
                innovation=civ.stats.innovation,
                stability=civ.stats.stability,
                food_security=civ.stats.food_security,
                health=civ.stats.health,
                consecutive_extreme_eco=civ.consecutive_extreme_eco,
                consecutive_extreme_unrest=civ.consecutive_extreme_unrest,
                consecutive_famine=civ.consecutive_famine,
                consecutive_zero_stability=civ.consecutive_zero_stability,
            )
            if not civ.alive:
                if "Extinct" not in self.db.list_marks(int(civ.id)):
                    self.db.add_mark(cycle_id, int(civ.id), "Extinct")

        for event in civ_events + global_events:
            title = self._format_event_title(event)
            detail = self._format_event_detail(event)
            metadata = {
                "event_id": event.event_id,
                "scope": event.scope,
                "target": event.target,
                "severity": event.severity,
                "deltas": event.deltas,
                "add_marks": event.add_marks,
                "remove_marks": event.remove_marks,
            }
            self.db.add_event(cycle_id, event.kind, title, detail, metadata)
            if event.scope == "global":
                for mark in event.add_marks:
                    self.db.add_mark(cycle_id, None, mark)
                for mark in event.remove_marks:
                    self.db.remove_mark(cycle_id, None, mark)
            else:
                civ_id = int(event.target)
                for mark in event.add_marks:
                    self.db.add_mark(cycle_id, civ_id, mark)
                for mark in event.remove_marks:
                    self.db.remove_mark(cycle_id, civ_id, mark)

        for effect in delayed_applied:
            civ_id = None if effect.target == "global" else int(effect.target)
            if effect.target == "global":
                for mark in effect.add_marks:
                    self.db.add_mark(cycle_id, None, mark)
                for mark in effect.remove_marks:
                    self.db.remove_mark(cycle_id, None, mark)
            else:
                for mark in effect.add_marks:
                    self.db.add_mark(cycle_id, civ_id, mark)
                for mark in effect.remove_marks:
                    self.db.remove_mark(cycle_id, civ_id, mark)

        self.db.clear_delayed_effects()
        for effect in universe.global_pending_effects:
            cycle_due = cycle_id + max(1, effect.cycle_delay)
            civ_id = None if effect.target == "global" else int(effect.target)
            payload = {
                "deltas": effect.deltas,
                "add_marks": effect.add_marks,
                "remove_marks": effect.remove_marks,
            }
            self.db.add_delayed_effect(cycle_due, civ_id, "delayed", payload)

        for effect in delayed_applied:
            self.db.add_applied_effect(
                cycle_id,
                None if effect.target == "global" else int(effect.target),
                "delayed_applied",
                {
                    "deltas": effect.deltas,
                    "add_marks": effect.add_marks,
                    "remove_marks": effect.remove_marks,
                },
                None,
                self._now(),
            )

        self.db.set_setting("event_cooldowns", json.dumps(universe.cooldowns))

    def _check_universe_extinction(
        self, cycle_id: int, civ_states: List[CivilizationState]
    ) -> bool:
        if any(civ.alive for civ in civ_states):
            return False
        self.db.set_setting("universe_ended", "1")
        self.db.set_setting("universe_end_reason", "No signals detected")
        self.db.update_cycle_summary(cycle_id, "Universe ended: No signals detected")
        return True

    def _run_civ_scribes(
        self,
        cycle_id: int,
        civ_states: List[CivilizationState],
        civ_events: List[AppliedEvent],
        stream_callback: Optional[Callable[[Dict[str, str]], None]],
    ) -> Dict[str, Dict[str, str]]:
        reports: Dict[str, Dict[str, str]] = {}
        for civ in civ_states:
            if not civ.alive or civ.extinct:
                continue
            events = [e for e in civ_events if e.target == civ.id]
            context = self._build_civ_context(cycle_id, civ, events)
            if self.llm.mode == "stub":
                reports[civ.id] = {
                    "log_text": "LLM disabled.",
                    "god_text": "",
                    "model": "",
                    "latency_ms": "0",
                }
                continue
            if civ.extinct or not civ.alive:
                raise RuntimeError(
                    f"LLM call blocked for extinct civ {civ.id} at cycle {cycle_id}"
                )
            if stream_callback:
                stream_callback(
                    {
                        "type": "log_start",
                        "scope": "civ",
                        "civ_id": civ.id,
                        "cycle": cycle_id,
                        "role": "assistant",
                    }
                )
            result = self.llm.generate_civ_thought(
                civ.name,
                cycle_id,
                context,
                on_chunk=(lambda chunk: stream_callback(
                    {
                        "type": "log_chunk",
                        "scope": "civ",
                        "civ_id": civ.id,
                        "cycle": cycle_id,
                        "role": "assistant",
                        "chunk": chunk,
                    }
                )) if stream_callback else None,
                prompt_seed="",
                template=self.prompt_templates["civ_thought"],
            )
            if result:
                sections = parse_sections(result.response, ["LOG", "GOD"])
                log_text = sections.get("LOG", "").strip()
                god_text = sections.get("GOD", "").strip()
                self._log_llm_format_issue(
                    "civ",
                    int(civ.id),
                    cycle_id,
                    result.response,
                    required_headers=["LOG"],
                )
                if log_text:
                    reports[civ.id] = {
                        "log_text": log_text,
                        "god_text": god_text,
                        "model": result.model,
                        "latency_ms": str(result.latency_ms),
                    }
                    self.db.add_ai_log("civ", int(civ.id), cycle_id, "assistant", log_text)
                    if god_text:
                        self.db.add_ai_log("civ", int(civ.id), cycle_id, "god", god_text)
                self.db.add_ai_log("civ", int(civ.id), cycle_id, "prompt", result.prompt)
            if stream_callback:
                stream_callback(
                    {
                        "type": "log_end",
                        "scope": "civ",
                        "civ_id": civ.id,
                        "cycle": cycle_id,
                        "role": "assistant",
                        "message": reports.get(civ.id, {}).get("log_text", ""),
                    }
                )
        for civ in civ_states:
            if (civ.extinct or not civ.alive) and civ.id in reports:
                raise RuntimeError(
                    f"Extinct civ {civ.id} generated output at cycle {cycle_id}"
                )
        return reports

    def _run_master_scribe(
        self,
        cycle_id: int,
        civ_states: List[CivilizationState],
        global_events: List[AppliedEvent],
        civ_reports: Dict[str, Dict[str, str]],
        stream_callback: Optional[Callable[[Dict[str, str]], None]],
    ) -> Dict[str, str]:
        if self._universe_ended():
            raise RuntimeError(f"Master LLM called after universe ended at C{cycle_id}")
        if self.llm.mode == "stub":
            return {"title": "", "log_text": "", "analysis_text": "", "god_text": ""}
        context = self._build_master_context_v2(
            cycle_id, civ_states, global_events, civ_reports
        )
        if stream_callback:
            stream_callback(
                {
                    "type": "log_start",
                    "scope": "master",
                    "civ_id": None,
                    "cycle": cycle_id,
                    "role": "assistant",
                }
            )
        result = self.llm.generate_master_log(
            cycle_id,
            context,
            on_chunk=(lambda chunk: stream_callback(
                {
                    "type": "log_chunk",
                    "scope": "master",
                    "civ_id": None,
                    "cycle": cycle_id,
                    "role": "assistant",
                    "chunk": chunk,
                }
            )) if stream_callback else None,
            prompt_seed="",
            template=self.prompt_templates["master"],
        )
        if result:
            sections = parse_sections(
                result.response, ["TITLE", "LOG", "ANALYSIS", "GOD"]
            )
            title = sections.get("TITLE", "").strip() or f"Cycle {cycle_id}"
            log_text = sections.get("LOG", "").strip()
            analysis_text = sections.get("ANALYSIS", "").strip()
            god_text = sections.get("GOD", "").strip()
            self._log_llm_format_issue(
                "master",
                None,
                cycle_id,
                result.response,
                required_headers=["TITLE", "LOG", "ANALYSIS"],
            )
            if log_text:
                self.db.add_ai_log("master", None, cycle_id, "assistant", log_text)
            if analysis_text:
                self.db.add_ai_log("master", None, cycle_id, "analysis", analysis_text)
            if god_text:
                self.db.add_ai_log("master", None, cycle_id, "god", god_text)
            self.db.add_ai_log("master", None, cycle_id, "prompt", result.prompt)
            self.db.update_cycle_summary(cycle_id, title)
            if stream_callback:
                stream_callback(
                    {
                        "type": "log_end",
                        "scope": "master",
                        "civ_id": None,
                        "cycle": cycle_id,
                        "role": "assistant",
                        "message": log_text,
                    }
                )
            return {
                "title": title,
                "log_text": log_text,
                "analysis_text": analysis_text,
                "god_text": god_text,
                "model": result.model,
                "latency_ms": str(result.latency_ms),
            }
        if stream_callback:
            stream_callback(
                {
                    "type": "log_end",
                    "scope": "master",
                    "civ_id": None,
                    "cycle": cycle_id,
                    "role": "assistant",
                    "message": "",
                }
            )
        return {"title": "", "log_text": "", "analysis_text": "", "god_text": ""}
        if stream_callback:
            stream_callback(
                {
                    "type": "log_end",
                    "scope": "master",
                    "civ_id": None,
                    "cycle": cycle_id,
                    "role": "assistant",
                    "message": result.log if result else "",
                }
            )

    def _apply_player_commands(self, cycle_id: int) -> bool:
        raw = self.db.get_setting("player_command_json")
        if not raw:
            return False
        try:
            command = json.loads(raw)
        except json.JSONDecodeError:
            self.db.set_setting("player_command_json", "")
            return False
        self.db.set_setting("player_command_json", "")
        if not isinstance(command, dict):
            return False
        kind = command.get("type")
        if kind == "END_UNIVERSE":
            reason = command.get("reason") or "Unknown"
            self.db.set_setting("universe_ended", "1")
            self.db.set_setting("universe_end_reason", str(reason))
            self.db.update_cycle_summary(cycle_id, f"Universe ended: {reason}")
            self.db.add_ai_log("master", None, cycle_id, "command", f"END_UNIVERSE: {reason}")
            return True
        if kind == "KILL_CIV":
            civ_id = command.get("civ_id")
            if civ_id is None:
                return False
            self.db.update_civilization(int(civ_id), extinct=1, extinct_cycle=cycle_id)
            self.db.add_mark(cycle_id, int(civ_id), "Extinct")
            self.db.add_ai_log("master", None, cycle_id, "command", f"KILL_CIV {civ_id}")
            return False
        if kind == "SET_GLOBAL_MARK":
            mark = command.get("mark")
            if mark:
                self.db.add_mark(cycle_id, None, str(mark))
                self.db.add_ai_log("master", None, cycle_id, "command", f"SET_GLOBAL_MARK {mark}")
            return False
        if kind == "FORCE_EVENT":
            event_id = command.get("event_id")
            target = command.get("target", "global")
            if event_id:
                self._force_event(cycle_id, str(event_id), target)
                self.db.add_ai_log(
                    "master", None, cycle_id, "command", f"FORCE_EVENT {event_id} -> {target}"
                )
            return False
        return False

    def _ensure_universe(self) -> None:
        """Create a fresh universe if the DB is empty."""
        if self.db.universe_exists():
            return
        self._seed_universe()

    def _seed_universe(self) -> None:
        """Initial universe seeding: systems, planets, and first civilizations."""
        random.seed()
        systems: List[StarSystem] = []
        for i in range(10):
            name = f"SYS-{i + 1:02d}"
            x = random.uniform(0.1, 0.9)
            y = random.uniform(0.1, 0.9)
            system_id = self.db.add_system(name, x, y)
            systems.append(StarSystem(system_id, name, x, y))

        planet_pool: List[Planet] = []
        for system in systems:
            planet_count = random.randint(3, 8)
            for p in range(planet_count):
                orbit = round(0.3 + p * random.uniform(0.4, 0.9), 2)
                size = round(random.uniform(0.6, 2.4), 2)
                habitability = round(random.uniform(0.0, 1.0), 2)
                kind = random.choice(
                    ["rocky", "ocean", "ice", "desert", "gas", "jungle", "metallic"]
                )
                richness = round(random.uniform(0.0, 1.0), 2)
                science = round(random.uniform(0.0, 1.0), 2)
                name = f"{system.name}-P{p + 1}"
                planet_id = self.db.add_planet(
                    system.id,
                    name,
                    orbit,
                    size,
                    habitability,
                    kind,
                    richness,
                    science,
                )
                planet_pool.append(
                    Planet(
                        planet_id,
                        system.id,
                        name,
                        orbit,
                        size,
                        habitability,
                        kind,
                        richness,
                        science,
                    )
                )

        habitable = sorted(
            planet_pool, key=lambda p: p.habitability, reverse=True
        )[: random.randint(3, 4)]
        prompt_planets = [(p.name, p.habitability) for p in habitable]
        civs, llm_meta = self.llm.generate_civilizations(
            prompt_planets,
            len(habitable),
            template=self.prompt_templates["civ_gen"],
        )
        civs = self._dedupe_civ_seeds(civs)
        if llm_meta:
            self.db.add_ai_log(
                "master",
                None,
                0,
                "prompt",
                llm_meta.prompt,
            )
            self.db.add_ai_log(
                "master",
                None,
                0,
                "assistant",
                llm_meta.response or "LLM unavailable; fallback civs used.",
            )
        for planet, civ in zip(habitable, civs):
            cohesion = round(random.uniform(0.4, 0.8), 2)
            inequality = round(random.uniform(0.2, 0.7), 2)
            eco_pressure = round(random.uniform(0.2, 0.7), 2)
            innovation = round(random.uniform(0.2, 0.7), 2)
            stability = round(random.uniform(0.3, 0.8), 2)
            food_security = round(random.uniform(0.3, 0.9), 2)
            health = round(random.uniform(0.3, 0.9), 2)
            tech_stage = "stone"
            civ_id = self.db.add_civilization(
                civ.name,
                civ.color,
                planet.id,
                "emerging",
                "active",
                0,
                None,
                cohesion,
                inequality,
                eco_pressure,
                innovation,
                stability,
                food_security,
                health,
                tech_stage,
                "",
                0,
                0,
                0,
                0,
            )
            self.db.add_ai_log(
                "civ",
                civ_id,
                0,
                "assistant",
                f"Birth summary: {civ.summary}",
            )

    def _run_civ_turns(
        self,
        cycle_id: int,
        stream_callback: Optional[Callable[[Dict[str, str]], None]],
    ) -> tuple[str, list]:
        """Advance civ state and collect their narrative responses."""
        if not self.LEGACY_JSON_MODE:
            raise RuntimeError("Legacy JSON mode disabled in V3_DND.")
        if self.llm.mode == "stub":
            return "LLM disabled.", []
        player_directive = self._consume_player_directive(cycle_id)
        civs = self.db.list_civilizations()
        systems = {s.id: s for s in self.db.list_systems()}
        planets = {p.id: p for p in self.db.list_planets()}
        civ_summaries = []
        for civ in civs:
            stats = self._advance_civ_stats(civ)
            stats = self._apply_breakthroughs(civ, stats)
            self.db.update_civilization(
                civ.id,
                cohesion=stats["cohesion"],
                inequality=stats["inequality"],
                eco_pressure=stats["eco_pressure"],
                innovation=stats["innovation"],
                stability=stats["stability"],
                tech_stage=stats["tech_stage"],
                memory_long=stats["memory_long"],
            )
            planet = planets.get(civ.home_planet_id)
            system = systems.get(planet.system_id) if planet else None
            recent_logs = self.db.list_ai_logs("civ", civ.id, limit=2)
            context_lines = [
                f"Status: {civ.status}. Tech level: {civ.level}.",
                f"Tech stage: {stats['tech_stage']}.",
                (
                    "Stats: cohesion={coh:.2f}, inequality={ineq:.2f}, "
                    "eco_pressure={eco:.2f}, innovation={inn:.2f}, stability={stab:.2f}."
                ).format(
                    coh=stats["cohesion"],
                    ineq=stats["inequality"],
                    eco=stats["eco_pressure"],
                    inn=stats["innovation"],
                    stab=stats["stability"],
                ),
                f"Long memory: {stats['memory_long']}",
            ]
            if system:
                context_lines.append(
                    f"Home system: {system.name} at ({system.x:.2f}, {system.y:.2f})."
                )
            if planet:
                context_lines.append(
                    f"Home planet: {planet.name}, orbit {planet.orbit_au:.2f} AU, "
                    f"size {planet.size:.2f}, habitability {planet.habitability:.2f}."
                )
            if recent_logs:
                short = " | ".join(log.message for log in reversed(recent_logs))
                context_lines.append(f"Recent memory: {short}")
            if player_directive and self._directive_applies(player_directive, civ):
                context_lines.append(
                    "Player directive (must be obeyed; include verbatim in log): "
                    f"{player_directive['text']}"
                )
            context = "\n".join(context_lines)
            self._emit_stream(
                stream_callback,
                {
                    "type": "log_start",
                    "scope": "civ",
                    "civ_id": str(civ.id),
                    "cycle": str(cycle_id),
                    "role": "assistant",
                },
            )
            result = self.llm.generate_civ_thought(
                civ.name,
                cycle_id,
                context,
                on_chunk=lambda chunk, civ_id=civ.id: self._emit_stream(
                    stream_callback,
                    {
                        "type": "log_chunk",
                        "scope": "civ",
                        "civ_id": str(civ_id),
                        "cycle": str(cycle_id),
                        "role": "assistant",
                        "chunk": chunk,
                    },
                ),
                prompt_seed=self.prompt_seeds.get("civ", ""),
                template=self.prompt_templates["civ_thought"],
            )
            if player_directive and self._directive_applies(player_directive, civ):
                result = self._enforce_player_directive(
                    civ,
                    cycle_id,
                    context,
                    result,
                    player_directive["text"],
                    stream_callback,
                )
            if not result:
                self._emit_stream(
                    stream_callback,
                    {
                        "type": "log_chunk",
                        "scope": "civ",
                        "civ_id": str(civ.id),
                        "cycle": str(cycle_id),
                        "role": "assistant",
                        "chunk": "LLM unavailable.",
                    },
                )
                self._emit_stream(
                    stream_callback,
                    {
                        "type": "log_end",
                        "scope": "civ",
                        "civ_id": str(civ.id),
                        "cycle": str(cycle_id),
                        "role": "assistant",
                        "message": "LLM unavailable.",
                    },
                )
                continue
            updates = result.updates
            if updates:
                name = updates.get("name")
                color = updates.get("color")
                level = updates.get("level")
                status = updates.get("status")
                if color and not self._valid_hex_color(color):
                    color = None
                self.db.update_civilization(
                    civ.id,
                    name=name,
                    color=color,
                    level=level,
                    status=status,
                )
            new_memory = self._build_long_memory(civ, stats, result.log)
            self.db.update_civilization(civ.id, memory_long=new_memory)
            civ_name = updates.get("name") if updates else None
            if not civ_name:
                civ_name = civ.name
            self.db.add_ai_log("civ", civ.id, cycle_id, "prompt", result.prompt)
            self.db.add_ai_log(
                "civ", civ.id, cycle_id, "assistant", result.log
            )
            if result.god:
                self.db.add_ai_log("civ", civ.id, cycle_id, "god", result.god)
            civ_summaries.append(
                {
                    "civ": civ_name,
                    "log": result.log,
                    "god": result.god,
                    "updates": updates,
                }
            )
            self._emit_stream(
                stream_callback,
                {
                    "type": "log_end",
                    "scope": "civ",
                    "civ_id": str(civ.id),
                    "cycle": str(cycle_id),
                    "role": "assistant",
                    "message": result.log,
                },
            )
        civ_context = f"Total civilizations: {len(civs)}."
        return civ_context, civ_summaries

    def _run_master_narration(
        self,
        cycle_id: int,
        master_context: str,
        stream_callback: Optional[Callable[[Dict[str, str]], None]],
    ) -> None:
        """Stream the Master AI narrative and persist its outputs."""
        if not self.LEGACY_JSON_MODE:
            raise RuntimeError("Legacy JSON mode disabled in V3_DND.")
        self._emit_stream(
            stream_callback,
            {
                "type": "status",
                "scope": "master",
                "civ_id": "",
                "cycle": str(cycle_id),
                "role": "system",
                "message": "Master AI is working...",
            },
        )
        self._emit_stream(
            stream_callback,
            {
                "type": "log_start",
                "scope": "master",
                "civ_id": "",
                "cycle": str(cycle_id),
                "role": "assistant",
            },
        )
        master = self.llm.generate_master_log(
            cycle_id,
            master_context,
            on_chunk=lambda chunk: self._emit_stream(
                stream_callback,
                {
                    "type": "log_chunk",
                    "scope": "master",
                    "civ_id": "",
                    "cycle": str(cycle_id),
                    "role": "assistant",
                    "chunk": chunk,
                },
            ),
            prompt_seed=self.prompt_seeds.get("master", ""),
            template=self.prompt_templates["master"],
        )
        if master:
            self.db.add_ai_log("master", None, cycle_id, "prompt", master.prompt)
            self.db.add_ai_log("master", None, cycle_id, "assistant", master.log)
            self.db.add_ai_log("master", None, cycle_id, "analysis", master.analysis)
            if master.god:
                self.db.add_ai_log("master", None, cycle_id, "god", master.god)
            self.db.update_cycle_summary(cycle_id, master.title)
            self.db.add_event(
                cycle_id,
                "cycle",
                master.title,
                master.log,
                {"analysis": master.analysis, "god": master.god},
            )
            self._emit_stream(
                stream_callback,
                {
                    "type": "log_end",
                    "scope": "master",
                    "civ_id": "",
                    "cycle": str(cycle_id),
                    "role": "assistant",
                    "message": master.log,
                },
            )
        else:
            self._emit_stream(
                stream_callback,
                {
                    "type": "log_chunk",
                    "scope": "master",
                    "civ_id": "",
                    "cycle": str(cycle_id),
                    "role": "assistant",
                    "chunk": "LLM unavailable.",
                },
            )
            self._emit_stream(
                stream_callback,
                {
                    "type": "log_end",
                    "scope": "master",
                    "civ_id": "",
                    "cycle": str(cycle_id),
                    "role": "assistant",
                    "message": "LLM unavailable.",
                },
            )
            self.db.update_cycle_summary(cycle_id, f"Cycle {cycle_id}")
            self.db.add_event(
                cycle_id,
                "cycle",
                f"Cycle {cycle_id}",
                "No master response available.",
                {},
            )

    def _build_civ_context(
        self, cycle_id: int, civ: CivilizationState, events: List[AppliedEvent]
    ) -> str:
        lines = [
            f"Civilization: {civ.name}",
            f"Cycle: {cycle_id}",
            "",
            "Applied events:",
        ]
        if events:
            for event in events:
                lines.append(f"- {self._format_event_title(event)}")
                lines.append(f"  {self._format_event_detail(event)}")
        else:
            lines.append("- None")
        lines.append("")
        lines.append("Stats after effects:")
        lines.append(
            "  "
            f"eco_pressure={civ.stats.eco_pressure:.2f}, "
            f"inequality={civ.stats.inequality:.2f}, "
            f"cohesion={civ.stats.cohesion:.2f}, "
            f"stability={civ.stats.stability:.2f}, "
            f"innovation={civ.stats.innovation:.2f}, "
            f"food_security={civ.stats.food_security:.2f}, "
            f"health={civ.stats.health:.2f}"
        )
        lines.append("Marks: " + (", ".join(civ.marks) if civ.marks else "none"))
        recent = list(reversed(self.db.list_ai_logs("civ", int(civ.id), limit=3)))
        if recent:
            lines.append("")
            lines.append("Recent memory:")
            for log in recent:
                if log.role == "assistant":
                    lines.append(f"- {log.message}")
        return "\n".join(lines)

    def _build_master_context_v2(
        self,
        cycle_id: int,
        civ_states: List[CivilizationState],
        global_events: List[AppliedEvent],
        civ_reports: Dict[str, Dict[str, str]],
    ) -> str:
        lines = [f"Cycle {cycle_id} summary:"]
        if global_events:
            lines.append("Global events:")
            for event in global_events:
                lines.append(f"- {self._format_event_title(event)}")
                lines.append(f"  {self._format_event_detail(event)}")
        else:
            lines.append("Global events: none.")
        lines.append("")
        lines.append("Civilization reports:")
        extinct = []
        for civ in civ_states:
            if civ.alive and civ.id in civ_reports:
                log = civ_reports.get(civ.id, {}).get("log_text") or "No report."
                lines.append(f"- {civ.name}: {log}")
            else:
                extinct.append(civ.id)
        if extinct:
            lines.append("")
            for civ_id in extinct:
                civ_name = next((c.name for c in civ_states if c.id == civ_id), civ_id)
                lines.append(f"No signals detected from {civ_name}.")
        return "\n".join(lines)

    def _store_simulation_artifacts(self, cycle_id: int, events: list) -> None:
        """Persist events and store any attached metadata effects."""
        for event in events:
            self.db.add_event(
                cycle_id,
                event.kind,
                event.title,
                event.detail,
                event.metadata,
            )
            self._handle_event_metadata(cycle_id, event.metadata)

    def _handle_event_metadata(self, cycle_id: int, metadata: dict) -> None:
        if not isinstance(metadata, dict):
            return
        delayed = metadata.get("delayed_effects", [])
        if not isinstance(delayed, list):
            delayed = []
        for item in delayed:
            if not isinstance(item, dict):
                continue
            delay = int(item.get("cycle_delay", 0) or 0)
            due = cycle_id + max(1, delay)
            civ_id = self._resolve_civ(item.get("civ"))
            kind = str(item.get("kind", "effect"))
            payload = item.get("delta", {})
            if not isinstance(payload, dict):
                payload = {}
            self.db.add_delayed_effect(due, civ_id, kind, payload)
        marks = metadata.get("world_marks", [])
        if not isinstance(marks, list):
            marks = []
        for item in marks:
            if not isinstance(item, dict):
                continue
            civ_id = self._resolve_civ(item.get("civ"))
            label = str(item.get("label", "mark"))
            impact = str(item.get("impact", ""))
            self.db.add_world_mark(cycle_id, civ_id, label, impact)

    def _resolve_civ(self, value) -> Optional[int]:
        if value is None:
            return None
        civs = self.db.list_civilizations()
        if isinstance(value, int):
            for civ in civs:
                if civ.id == value:
                    return civ.id
        name = str(value).strip()
        for civ in civs:
            if civ.name == name:
                return civ.id
        return None

    def _format_event_title(self, event: AppliedEvent) -> str:
        if event.event_id.startswith("COLLAPSE_TABLE"):
            return f"Collapse outcome ({event.kind})"
        label = event.event_id.replace("EVT_", "").replace("_", " ").title()
        return label

    def _format_event_detail(self, event: AppliedEvent) -> str:
        parts = []
        if event.deltas:
            deltas = ", ".join(f"{k}={v:+.2f}" for k, v in event.deltas.items())
            parts.append(f"deltas: {deltas}")
        if event.add_marks:
            parts.append("add_marks: " + ", ".join(event.add_marks))
        if event.remove_marks:
            parts.append("remove_marks: " + ", ".join(event.remove_marks))
        return "; ".join(parts) if parts else "no direct effects"

    def _derive_status(self, civ: CivilizationState) -> str:
        if not civ.alive or civ.extinct:
            return "dead"
        stats = civ.stats
        if stats.food_security <= 0.20 or stats.health <= 0.20:
            return "famine"
        if stats.stability <= 0.20 or stats.cohesion <= 0.20:
            return "crisis"
        if stats.eco_pressure >= 0.80 or stats.inequality >= 0.80:
            return "unstable"
        if stats.stability >= 0.70 and stats.cohesion >= 0.70:
            return "stable"
        return "strained"

    def _dedupe_civ_seeds(self, civs) -> list:
        seen = set()
        deduped = []
        for idx, civ in enumerate(civs, start=1):
            name = civ.name.strip() if civ.name else ""
            if not name or name in seen:
                name = f"CIV-{idx}"
            seen.add(name)
            deduped.append(
                type(civ)(name=name, color=civ.color, summary=civ.summary)
            )
        return deduped

    def _event_to_dict(self, event: AppliedEvent) -> Dict[str, object]:
        return {
            "event_id": event.event_id,
            "kind": event.kind,
            "scope": event.scope,
            "severity": event.severity,
            "target": event.target,
            "deltas": event.deltas,
            "add_marks": event.add_marks,
            "remove_marks": event.remove_marks,
        }

    def _delayed_to_dict(self, effect: DelayedEffect) -> Dict[str, object]:
        return {
            "cycle_delay": effect.cycle_delay,
            "target": effect.target,
            "deltas": effect.deltas,
            "add_marks": effect.add_marks,
            "remove_marks": effect.remove_marks,
        }

    def _store_cycle_record(
        self,
        cycle_id: int,
        civ_states: List[CivilizationState],
        universe_state: UniverseState,
        civ_events: List[AppliedEvent],
        global_events: List[AppliedEvent],
        civ_reports: Dict[str, Dict[str, str]],
        master_report: Dict[str, str],
        delayed_applied: List[DelayedEffect],
    ) -> None:
        record = {
            "cycle": cycle_id,
            "rng_seed": universe_state.rng_seed,
            "global": {
                "global_marks": list(universe_state.global_marks),
                "global_events_applied": [self._event_to_dict(e) for e in global_events],
            },
            "delayed_effects": {
                "queued": [
                    self._delayed_to_dict(effect)
                    for effect in universe_state.global_pending_effects
                ],
                "applied": [self._delayed_to_dict(effect) for effect in delayed_applied],
            },
            "civilizations": [],
            "master": {
                "title": master_report.get("title", ""),
                "log_text": master_report.get("log_text", ""),
                "analysis_text": master_report.get("analysis_text", ""),
                "god_text": master_report.get("god_text", ""),
                "meta": {
                    "llm_model": master_report.get("model", ""),
                    "latency_ms": master_report.get("latency_ms", ""),
                },
            },
        }
        for civ in civ_states:
            applied = [self._event_to_dict(e) for e in civ_events if e.target == civ.id]
            narrative = civ_reports.get(civ.id, {})
            record["civilizations"].append(
                {
                    "civ_id": civ.id,
                    "name": civ.name,
                    "color": civ.color,
                    "alive": civ.alive and not civ.extinct,
                    "extinct": civ.extinct,
                    "extinct_cycle": civ.extinct_cycle,
                    "stats": civ.stats.as_dict(),
                    "world_marks": list(civ.marks),
                    "applied_events": applied,
                    "narrative": {
                        "log_text": narrative.get("log_text", ""),
                        "god_text": narrative.get("god_text", ""),
                    },
                    "meta": {
                        "llm_model": narrative.get("model", ""),
                        "latency_ms": narrative.get("latency_ms", ""),
                    },
                }
            )
        self.db.add_cycle_record(cycle_id, record)

    def _force_event(self, cycle_id: int, event_id: str, target: str) -> None:
        event = None
        for item in self.rules_engine.events:
            if item.id == event_id:
                event = item
                break
        if not event:
            return
        applied = self.rules_engine._make_applied_event(event, str(target))
        civ_states = self._load_civ_states()
        universe = self._load_universe_state(cycle_id)
        if applied.scope == "global":
            self.rules_engine._apply_event(applied, civ_states, universe)
        else:
            self.rules_engine._apply_event(applied, civ_states, universe)
        self._persist_rules_results(
            cycle_id,
            civ_states,
            universe,
            [applied] if applied.scope == "civ" else [],
            [applied] if applied.scope == "global" else [],
            [],
        )

    def _log_llm_format_issue(
        self,
        scope: str,
        civ_id: Optional[int],
        cycle_id: int,
        response: Optional[str],
        required_headers: List[str],
    ) -> None:
        if not response:
            return
        missing = []
        upper = response.upper()
        for header in required_headers:
            if f"{header}:" not in upper:
                missing.append(header)
        contains_json = "{" in response and "}" in response
        if not missing and not contains_json:
            return
        snippet = response.replace("\n", " ")[:400]
        parts = []
        if missing:
            parts.append(f"missing headers: {', '.join(missing)}")
        if contains_json:
            parts.append("json_detected")
        detail = " | ".join(parts) if parts else "format issue"
        self.db.add_ai_log(
            "error",
            civ_id,
            cycle_id,
            "format",
            f"{scope} {detail} | {snippet}",
        )

    def _now(self) -> str:
        return dt.datetime.utcnow().isoformat() + "Z"

    def _apply_delayed_effects(self, cycle_id: int) -> str:
        """Apply queued effects that mature this cycle."""
        effects = self.db.list_due_effects(cycle_id)
        if not effects:
            return "Delayed effects: none."
        summaries = []
        for effect in effects:
            self._apply_effect(effect)
            self.db.add_applied_effect(
                cycle_id,
                effect.civ_id,
                effect.kind,
                effect.payload,
                effect.id,
                self._now(),
            )
            self.db.delete_delayed_effect(effect.id)
            target = f"CIV{effect.civ_id}" if effect.civ_id else "global"
            summaries.append(f"{target}:{effect.kind}")
        return "Delayed effects applied: " + ", ".join(summaries)

    def _apply_effect(self, effect) -> None:
        delta = effect.payload if isinstance(effect.payload, dict) else {}
        civ_id = effect.civ_id
        if civ_id is None:
            return
        civs = {civ.id: civ for civ in self.db.list_civilizations()}
        civ = civs.get(civ_id)
        if not civ:
            return
        def clamp(value: float) -> float:
            return max(0.0, min(1.0, value))
        cohesion = clamp(civ.cohesion + float(delta.get("cohesion", 0.0)))
        inequality = clamp(civ.inequality + float(delta.get("inequality", 0.0)))
        eco = clamp(civ.eco_pressure + float(delta.get("eco_pressure", 0.0)))
        innovation = clamp(civ.innovation + float(delta.get("innovation", 0.0)))
        stability = clamp(civ.stability + float(delta.get("stability", 0.0)))
        self.db.update_civilization(
            civ_id,
            cohesion=cohesion,
            inequality=inequality,
            eco_pressure=eco,
            innovation=innovation,
            stability=stability,
        )

    def _apply_chaos(self, cycle_id: int) -> str:
        """Apply rare, temporary bias profiles to create discontinuities."""
        if self.llm.mode == "stub":
            return ""
        if random.random() < 0.25:
            self._spawn_chaos_profile(cycle_id)
        active = self.db.list_active_chaos(cycle_id)
        if not active:
            self.db.add_ai_log(
                "chaos",
                None,
                cycle_id,
                "status",
                f"Cycle {cycle_id}: No chaotic events.",
            )
            return "Chaos: none."
        summaries = []
        for profile in active:
            self._apply_chaos_bias(profile)
            self.db.add_ai_log(
                "chaos",
                profile.civ_id,
                cycle_id,
                "profile",
                (
                    f"{profile.archetype} | {profile.polarity} | "
                    f"intensity={profile.intensity:.2f} | "
                    f"C{profile.cycle_start}-{profile.cycle_end} | "
                    f"bias={profile.bias_json}"
                ),
            )
            target = f"CIV{profile.civ_id}" if profile.civ_id else "global"
            summaries.append(f"{target}:{profile.archetype}:{profile.polarity}")
        return "Chaos active: " + ", ".join(summaries)

    def _spawn_chaos_profile(self, cycle_id: int) -> None:
        civs = self.db.list_civilizations()
        target_global = random.random() < 0.5
        civ = None if target_global else (random.choice(civs) if civs else None)
        archetypes = ["Disruptor", "Pacifier", "Fanatic", "Deconstructor", "Symbolic"]
        archetype = random.choice(archetypes)
        polarity = self._pick_chaos_polarity()
        intensity = round(random.uniform(0.2, 0.6), 2)
        duration = random.randint(2, 4)
        bias = self._build_bias_vector(polarity)
        civ_id = civ.id if civ else None
        self.db.add_chaos_profile(
            cycle_id,
            cycle_id + duration,
            civ_id,
            archetype,
            polarity,
            bias,
            intensity,
        )
        self.db.add_world_mark(
            cycle_id,
            civ_id,
            "Ideological distortion",
            f"Subtle divergence ({polarity})",
        )
        self.db.add_ai_log(
            "chaos",
            civ_id,
            cycle_id,
            "spawn",
            (
                f"Cycle {cycle_id}: chaos profile spawned. "
                f"target={'global' if civ_id is None else f'CIV{civ_id}'} "
                f"archetype={archetype} polarity={polarity} "
                f"duration={duration} intensity={intensity:.2f} bias={bias}"
            ),
        )
        if random.random() < 0.5:
            self._spawn_cosmic_event(cycle_id, civ_id)

    def _build_bias_vector(self, polarity: str) -> str:
        if polarity == "stabilizing":
            bias = {"stability": 0.05, "cohesion": 0.04, "inequality": -0.03}
        elif polarity == "destabilizing":
            bias = {"stability": -0.06, "inequality": 0.05, "eco_pressure": 0.03}
        else:
            bias = {"innovation": 0.05, "stability": -0.02, "cohesion": 0.02}
        return json.dumps(bias)

    def _pick_chaos_polarity(self) -> str:
        seed = self.prompt_seeds.get("chaos", "").lower()
        if "stabil" in seed or "calm" in seed or "pacif" in seed:
            choices = ["stabilizing", "ambiguous", "stabilizing"]
        elif "disrupt" in seed or "chaos" in seed or "radical" in seed:
            choices = ["destabilizing", "ambiguous", "destabilizing"]
        else:
            choices = ["stabilizing", "destabilizing", "ambiguous"]
        return random.choice(choices)

    def _apply_chaos_bias(self, profile) -> None:
        if profile.civ_id is None:
            return
        civs = {civ.id: civ for civ in self.db.list_civilizations()}
        civ = civs.get(profile.civ_id)
        if not civ:
            return
        try:
            bias = json.loads(profile.bias_json)
        except json.JSONDecodeError:
            return
        intensity = profile.intensity
        def clamp(value: float) -> float:
            return max(0.0, min(1.0, value))
        cohesion = clamp(civ.cohesion + float(bias.get("cohesion", 0.0)) * intensity)
        inequality = clamp(civ.inequality + float(bias.get("inequality", 0.0)) * intensity)
        eco = clamp(civ.eco_pressure + float(bias.get("eco_pressure", 0.0)) * intensity)
        innovation = clamp(civ.innovation + float(bias.get("innovation", 0.0)) * intensity)
        stability = clamp(civ.stability + float(bias.get("stability", 0.0)) * intensity)
        self.db.update_civilization(
            civ.id,
            cohesion=cohesion,
            inequality=inequality,
            eco_pressure=eco,
            innovation=innovation,
            stability=stability,
        )

    def _spawn_cosmic_event(self, cycle_id: int, civ_id: Optional[int]) -> None:
        options = [
            ("comet", "A luminous comet seeds rare minerals across the system."),
            ("supernova", "A distant supernova shakes belief systems and myths."),
            ("impact", "A rogue impact fractures a moon, exposing new resources."),
            ("aurora", "Planetary auroras ignite a new scientific obsession."),
            ("ruins", "Ancient debris field hints at forgotten civilizations."),
        ]
        kind, detail = random.choice(options)
        title = f"Cosmic anomaly: {kind}"
        metadata = {}
        if kind in ("comet", "impact"):
            metadata["delayed_effects"] = [
                {
                    "cycle_delay": 2,
                    "civ": civ_id,
                    "kind": "resource_boom",
                    "delta": {"innovation": 0.05, "eco_pressure": 0.04},
                }
            ]
            metadata["world_marks"] = [
                {"civ": civ_id, "label": "New mineral frontier", "impact": detail}
            ]
        elif kind == "supernova":
            metadata["delayed_effects"] = [
                {
                    "cycle_delay": 1,
                    "civ": civ_id,
                    "kind": "doubt_wave",
                    "delta": {"stability": -0.05, "cohesion": -0.03},
                }
            ]
            metadata["world_marks"] = [
                {"civ": civ_id, "label": "Mythic doubt", "impact": detail}
            ]
        elif kind == "aurora":
            metadata["delayed_effects"] = [
                {
                    "cycle_delay": 1,
                    "civ": civ_id,
                    "kind": "research_surge",
                    "delta": {"innovation": 0.06},
                }
            ]
        self.db.add_event(cycle_id, "cosmic", title, detail, metadata)
        self.db.add_ai_log(
            "chaos",
            civ_id,
            cycle_id,
            "cosmic",
            f"{title} | {detail} | metadata={metadata}",
        )
    def _init_seed(self) -> int:
        existing = self.db.get_setting("seed")
        if existing:
            seed = int(existing)
            random.seed(seed)
            return seed
        seed = random.randint(100000, 999999)
        self.db.set_setting("seed", str(seed))
        random.seed(seed)
        return seed

    def _load_prompt_seeds(self) -> dict:
        return {
            "master": self.db.get_setting("prompt_master") or "",
            "civ": self.db.get_setting("prompt_civ") or "",
            "chaos": self.db.get_setting("prompt_chaos") or "",
        }

    def _consume_player_directive(self, cycle_id: int) -> Optional[dict]:
        text = self.db.get_setting("player_directive_text") or ""
        target = self.db.get_setting("player_directive_target") or ""
        if not text.strip():
            return None
        self.db.set_setting("player_directive_text", "")
        self.db.set_setting("player_directive_target", "")
        self.db.add_ai_log(
            "player",
            None,
            cycle_id,
            "directive",
            f"target={target} | {text.strip()}",
        )
        return {"text": text.strip(), "target": target.strip()}

    def _directive_applies(self, directive: dict, civ) -> bool:
        target = directive.get("target", "").strip().lower()
        if target in ("", "all"):
            return True
        return target == civ.name.lower()

    def _enforce_player_directive(
        self,
        civ,
        cycle_id: int,
        context: str,
        result,
        directive_text: str,
        stream_callback: Optional[Callable[[Dict[str, str]], None]],
    ):
        if result and directive_text in result.log:
            return result
        enforced_context = (
            f"{context}\n\nSTRICT RULE: You MUST include the directive text verbatim "
            "inside the log and follow it."
        )
        retry = self.llm.generate_civ_thought(
            civ.name,
            cycle_id,
            enforced_context,
            on_chunk=lambda chunk, civ_id=civ.id: self._emit_stream(
                stream_callback,
                {
                    "type": "log_chunk",
                    "scope": "civ",
                    "civ_id": str(civ_id),
                    "cycle": str(cycle_id),
                    "role": "assistant",
                    "chunk": chunk,
                },
            ),
            prompt_seed=self.prompt_seeds.get("civ", ""),
            template=self.prompt_templates["civ_thought"],
        )
        if retry and directive_text in retry.log:
            return retry
        return result

    def _load_prompt_templates(self) -> dict:
        return {
            "events": self.db.get_setting("prompt_events") or DEFAULT_EVENTS_PROMPT,
            "civ_gen": self.db.get_setting("prompt_civ_gen") or DEFAULT_CIV_GEN_PROMPT,
            "civ_thought": self.db.get_setting("prompt_civ_thought")
            or DEFAULT_CIV_THOUGHT_PROMPT,
            "master": self.db.get_setting("prompt_master_template")
            or DEFAULT_MASTER_PROMPT,
        }

    def _advance_civ_stats(self, civ) -> dict:
        def clamp(value: float) -> float:
            return max(0.0, min(1.0, value))

        drift = random.uniform(-0.03, 0.03)
        cohesion = clamp(civ.cohesion + drift - civ.inequality * 0.02)
        inequality = clamp(civ.inequality + random.uniform(-0.02, 0.04))
        eco_pressure = clamp(civ.eco_pressure + random.uniform(-0.02, 0.05))
        innovation = clamp(civ.innovation + random.uniform(-0.02, 0.04))
        stability = clamp(civ.stability + (cohesion - inequality) * 0.02)

        tech_stage = self._maybe_advance_stage(
            civ.tech_stage, innovation, stability
        )
        memory_long = civ.memory_long or "Seeded culture, early myths forming."
        return {
            "cohesion": cohesion,
            "inequality": inequality,
            "eco_pressure": eco_pressure,
            "innovation": innovation,
            "stability": stability,
            "tech_stage": tech_stage,
            "memory_long": memory_long,
        }

    def _maybe_advance_stage(
        self, stage: str, innovation: float, stability: float
    ) -> str:
        stages = [
            "stone",
            "bronze",
            "iron",
            "classical",
            "industrial",
            "atomic",
            "space",
            "interstellar",
        ]
        if stage not in stages:
            return stage
        idx = stages.index(stage)
        if idx >= len(stages) - 1:
            return stage
        chance = 0.01 + innovation * 0.06 + stability * 0.03
        if random.random() < chance:
            return stages[idx + 1]
        return stage

    def _apply_breakthroughs(self, civ, stats: dict) -> dict:
        if stats["tech_stage"] == civ.tech_stage:
            return stats
        if stats["tech_stage"] == "space" and civ.tech_stage in (
            "stone",
            "bronze",
            "iron",
            "classical",
        ):
            if random.random() > 0.02:
                stats["tech_stage"] = civ.tech_stage
        return stats

    def _build_long_memory(self, civ, stats: dict, log: str) -> str:
        core = (
            f"Traits: coh={stats['cohesion']:.2f}, ineq={stats['inequality']:.2f}, "
            f"eco={stats['eco_pressure']:.2f}, inn={stats['innovation']:.2f}, "
            f"stab={stats['stability']:.2f}, stage={stats['tech_stage']}."
        )
        log_trim = log.replace("\n", " ")
        if len(log_trim) > 180:
            log_trim = log_trim[:177] + "..."
        return f"{core} Canon: {log_trim}"

    def _innovation_climate(self, civs) -> str:
        if not civs:
            return "dormant"
        good_status = ("stable", "prosper", "golden", "unified", "calm")
        for civ in civs:
            if any(k in str(civ.status).lower() for k in good_status):
                return "propitious"
            last = self.db.list_ai_logs("civ", civ.id, limit=1)
            if last and any(
                k in last[0].message.lower()
                for k in ("research", "science", "education", "infrastructure")
            ):
                return "propitious"
        return "volatile"

    def _valid_hex_color(self, value: str) -> bool:
        if not value.startswith("#") or len(value) != 7:
            return False
        try:
            int(value[1:], 16)
        except ValueError:
            return False
        return True

    def _emit_stream(
        self,
        stream_callback: Optional[Callable[[Dict[str, str]], None]],
        payload: Dict[str, str],
    ) -> None:
        if stream_callback:
            stream_callback(payload)
