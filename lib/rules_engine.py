import ast
import json
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


STAT_KEYS = (
    "eco_pressure",
    "inequality",
    "cohesion",
    "stability",
    "innovation",
    "food_security",
    "health",
    "elite_power",
    "legitimacy",
    "extraction_rate",
)

STAGE_ORDER = {
    "stone": 0,
    "bronze": 1,
    "iron": 2,
    "industrial": 3,
    "space": 4,
}

STAGE_THRESHOLDS = (
    (0.90, "space"),
    (0.70, "industrial"),
    (0.45, "iron"),
    (0.25, "bronze"),
    (0.00, "stone"),
)


@dataclass
class CivStats:
    eco_pressure: float
    inequality: float
    cohesion: float
    stability: float
    innovation: float
    food_security: float
    health: float
    elite_power: float
    legitimacy: float
    extraction_rate: float

    def as_dict(self) -> Dict[str, float]:
        return {
            "eco_pressure": self.eco_pressure,
            "inequality": self.inequality,
            "cohesion": self.cohesion,
            "stability": self.stability,
            "innovation": self.innovation,
            "food_security": self.food_security,
            "health": self.health,
            "elite_power": self.elite_power,
            "legitimacy": self.legitimacy,
            "extraction_rate": self.extraction_rate,
        }


@dataclass
class CivilizationState:
    id: str
    name: str
    color: str
    alive: bool
    extinct: bool
    extinct_cycle: Optional[int]
    home_system: str
    stats: CivStats
    progress: float = 0.0
    stage: str = "stone"
    agenda: str = "SURVIVE"
    stance: str = "PRAGMATIC"
    known_systems: List[str] = field(default_factory=list)
    reach: int = 0
    missions: List[Dict[str, object]] = field(default_factory=list)
    known_contacts: List[str] = field(default_factory=list)
    contact_intents: Dict[str, str] = field(default_factory=dict)
    established_routes: List[Dict[str, object]] = field(default_factory=list)
    marks: List[str] = field(default_factory=list)
    consecutive_extreme_eco: int = 0
    consecutive_extreme_unrest: int = 0
    consecutive_famine: int = 0
    consecutive_zero_stability: int = 0
    consecutive_good_cycles: int = 0


@dataclass
class DelayedEffect:
    cycle_delay: int
    target: str
    deltas: Dict[str, float]
    add_marks: List[str]
    remove_marks: List[str]


@dataclass
class UniverseState:
    cycle: int
    ended: bool
    end_reason: Optional[str]
    rng_seed: int
    global_marks: List[str]
    global_pending_effects: List[DelayedEffect]
    cooldowns: Dict[str, int] = field(default_factory=dict)
    beacons: List[Dict[str, object]] = field(default_factory=list)
    system_names: List[str] = field(default_factory=list)


@dataclass
class EventDefinition:
    id: str
    kind: str
    scope: str
    weight_base: float
    severity_range: Tuple[int, int]
    cooldown_cycles: int
    cannot_repeat_for: int
    preconditions: List[str]
    effects: Dict[str, object]
    notes: str
    min_stage: Optional[str] = None
    max_stage: Optional[str] = None


@dataclass
class AppliedEvent:
    event_id: str
    kind: str
    scope: str
    severity: int
    target: str
    deltas: Dict[str, float]
    add_marks: List[str]
    remove_marks: List[str]
    delayed_effects: List[DelayedEffect]
    spawn_mission: Optional[Dict[str, object]] = None
    contact_with: Optional[str] = None
    contact_system: Optional[str] = None


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class _PreconditionEvaluator(ast.NodeVisitor):
    def __init__(self, civ: CivilizationState, universe: UniverseState) -> None:
        self.civ = civ
        self.universe = universe

    def visit_Expression(self, node: ast.Expression):  # pragma: no cover - ast entry
        return self.visit(node.body)

    def visit_BoolOp(self, node: ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(self.visit(value) for value in node.values)
        if isinstance(node.op, ast.Or):
            return any(self.visit(value) for value in node.values)
        raise ValueError("Unsupported boolean operator")

    def visit_UnaryOp(self, node: ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return not self.visit(node.operand)
        raise ValueError("Unsupported unary operator")

    def visit_Compare(self, node: ast.Compare):
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            if isinstance(op, ast.Gt) and not (left > right):
                return False
            if isinstance(op, ast.GtE) and not (left >= right):
                return False
            if isinstance(op, ast.Lt) and not (left < right):
                return False
            if isinstance(op, ast.LtE) and not (left <= right):
                return False
            if isinstance(op, ast.Eq) and not (left == right):
                return False
            left = right
        return True

    def visit_Name(self, node: ast.Name):
        if node.id in STAT_KEYS:
            return getattr(self.civ.stats, node.id)
        if node.id == "reach":
            return self.civ.reach
        if node.id == "missions_total":
            return len(self.civ.missions)
        if node.id == "has_any_beacon_in_unknown_system":
            return self._has_any_beacon_in_unknown_system()
        if node.id == "detects_foreign_beacon":
            return self._detects_foreign_beacon()
        if node.id == "shares_system_with_foreign_outpost":
            return self._shares_system_with_foreign_outpost()
        if node.id == "has_contact":
            return bool(self.civ.known_contacts)
        if node.id == "relation_intent":
            return self._relation_intent()
        raise ValueError(f"Unknown name {node.id}")

    def visit_Constant(self, node: ast.Constant):
        return node.value

    def visit_Call(self, node: ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Unsupported function call")
        if node.func.id in ("has_mark", "has_global"):
            if len(node.args) != 1:
                raise ValueError("Mark call requires one argument")
            arg = self.visit(node.args[0])
            if not isinstance(arg, str):
                raise ValueError("Mark name must be string")
            if node.func.id == "has_mark":
                return arg in self.civ.marks
            if node.func.id == "has_global":
                return arg in self.universe.global_marks
        if node.func.id == "missions_count":
            if node.args:
                raise ValueError("missions_count expects keyword args only")
            filters = {}
            for kw in node.keywords:
                if not isinstance(kw.arg, str):
                    continue
                filters[kw.arg] = self.visit(kw.value)
            return self._missions_count(filters)
        raise ValueError(f"Unsupported function {node.func.id}")

    def generic_visit(self, node: ast.AST):
        raise ValueError(f"Unsupported expression node: {type(node).__name__}")

    def _missions_count(self, filters: Dict[str, object]) -> int:
        count = 0
        for mission in self.civ.missions:
            if not isinstance(mission, dict):
                continue
            ok = True
            for key, value in filters.items():
                if mission.get(key) != value:
                    ok = False
                    break
            if ok:
                count += 1
        return count

    def _has_any_beacon_in_unknown_system(self) -> bool:
        for beacon in self.universe.beacons:
            if not isinstance(beacon, dict):
                continue
            if beacon.get("owner") != self.civ.id:
                continue
            system = beacon.get("system")
            if system and system != self.civ.home_system:
                return True
        return False

    def _detects_foreign_beacon(self) -> bool:
        for beacon in self.universe.beacons:
            if not isinstance(beacon, dict):
                continue
            if beacon.get("owner") == self.civ.id:
                continue
            strength = float(beacon.get("strength", 0.0))
            if strength <= 0.0:
                continue
            return True
        return False

    def _shares_system_with_foreign_outpost(self) -> bool:
        owned = {b.get("system") for b in self.universe.beacons if b.get("owner") == self.civ.id}
        for beacon in self.universe.beacons:
            if not isinstance(beacon, dict):
                continue
            if beacon.get("owner") == self.civ.id:
                continue
            system = beacon.get("system")
            if system and system in owned:
                return True
        return False

    def _relation_intent(self) -> str:
        intents = set(self.civ.contact_intents.values())
        if "RAID" in intents:
            return "RAID"
        if "TRADE" in intents:
            return "TRADE"
        if "AVOID" in intents:
            return "AVOID"
        return "TRADE"


class RulesEngine:
    def __init__(self, catalog_path: str, rng_seed: int, ruleset=None) -> None:
        from rulesets.harsh_realism import HarshRealismRuleset

        self.catalog_path = catalog_path
        self.rng = random.Random(rng_seed)
        self.events = self._load_catalog(catalog_path)
        self.ruleset = ruleset or HarshRealismRuleset()

    def _load_catalog(self, path: str) -> List[EventDefinition]:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        events = []
        for item in data:
            events.append(
                EventDefinition(
                    id=item["id"],
                    kind=item["kind"],
                    scope=item["scope"],
                    weight_base=float(item["weight_base"]),
                    severity_range=(int(item["severity_range"][0]), int(item["severity_range"][1])),
                    cooldown_cycles=int(item["cooldown_cycles"]),
                    cannot_repeat_for=int(item["cannot_repeat_for"]),
                    preconditions=item.get("preconditions", []),
                    effects=item["effects"],
                    notes=item.get("notes", ""),
                    min_stage=item.get("min_stage"),
                    max_stage=item.get("max_stage"),
                )
            )
        return events

    def eligible_events(
        self,
        civ: CivilizationState,
        universe: UniverseState,
        scope: str,
        severity_min: int,
        severity_max: int,
    ) -> List[EventDefinition]:
        eligible = []
        for event in self.events:
            if event.scope != scope:
                continue
            if scope == "civ" and not self._passes_stage_gate(event, civ.stage):
                continue
            if event.severity_range[1] < severity_min or event.severity_range[0] > severity_max:
                continue
            key = self._cooldown_key(event.id, civ.id if scope == "civ" else "global")
            last_cycle = universe.cooldowns.get(key)
            if last_cycle is not None:
                min_gap = max(event.cooldown_cycles, event.cannot_repeat_for)
                if universe.cycle - last_cycle <= min_gap:
                    continue
            if not self._passes_preconditions(event, civ, universe):
                continue
            eligible.append(event)
        return eligible

    def _passes_stage_gate(self, event: EventDefinition, stage: str) -> bool:
        if not event.min_stage and not event.max_stage:
            return True
        civ_idx = STAGE_ORDER.get(stage)
        if civ_idx is None:
            return True
        min_stage = event.min_stage
        if min_stage:
            min_idx = STAGE_ORDER.get(min_stage)
            if min_idx is not None and civ_idx < min_idx:
                return False
        max_stage = event.max_stage
        if max_stage:
            max_idx = STAGE_ORDER.get(max_stage)
            if max_idx is not None and civ_idx > max_idx:
                return False
        return True

    def roll_cycle(
        self, civs: List[CivilizationState], universe: UniverseState
    ) -> Tuple[List[AppliedEvent], List[AppliedEvent], List[DelayedEffect]]:
        civ_events: List[AppliedEvent] = []
        global_events: List[AppliedEvent] = []
        delayed_applied: List[DelayedEffect] = []

        delayed_applied.extend(self._apply_pending_effects(civs, universe))

        for civ in civs:
            if not civ.alive:
                continue
            if self.ruleset.is_stressed(civ, universe):
                minor_rolls = self.ruleset.minor_roll_count(civ, universe, self.rng)
                civ_events.extend(
                    self._roll_events_for_civ(civ, universe, 1, 2, minor_rolls)
                )
            if self.ruleset.is_in_crisis(civ, universe):
                major_rolls = self.ruleset.major_roll_count(civ, universe, self.rng)
                civ_events.extend(
                    self._roll_events_for_civ(civ, universe, 3, 5, major_rolls)
                )

        global_stage_bias = any(
            civ.alive and civ.stage in ("industrial", "space") for civ in civs
        )
        if self.ruleset.should_roll_global(universe, self.rng):
            global_events.extend(
                self._roll_events_for_global(universe, 1, 5, 1, global_stage_bias)
            )

        for event in civ_events:
            self._apply_event(event, civs, universe)
        for event in global_events:
            self._apply_event(event, civs, universe)

        delayed_applied.extend(self._apply_pending_effects(civs, universe))

        mission_events = self._update_missions(civs, universe)
        civ_events.extend(mission_events)
        for event in mission_events:
            self._apply_event(event, civs, universe)

        for civ in civs:
            if not civ.alive:
                continue
            if self.ruleset.hard_extinction(civ, universe):
                continue
            if self.ruleset.collapse_trigger(civ, universe):
                collapse_event = self.ruleset.collapse_outcome(
                    civ, universe, self.rng
                )
                civ_events.append(collapse_event)
                self._apply_event(collapse_event, civs, universe)

        self._apply_internal_drift(civs)
        civ_events.extend(self._update_legitimacy_crisis(civs, universe))
        civ_events.extend(self._update_progress_and_stage(civs, universe))

        return civ_events, global_events, delayed_applied

    def _update_legitimacy_crisis(
        self, civs: List[CivilizationState], universe: UniverseState
    ) -> List[AppliedEvent]:
        events: List[AppliedEvent] = []
        for civ in civs:
            if not civ.alive:
                continue
            crisis, _severe = self._legitimacy_crisis_levels(civ)
            has_mark = "LegitimacyCrisis" in civ.marks
            if crisis and not has_mark:
                onset = AppliedEvent(
                    event_id="EVT_LEGITIMACY_CRISIS_ONSET",
                    kind="politics",
                    scope="civ",
                    severity=2,
                    target=civ.id,
                    deltas={},
                    add_marks=["LegitimacyCrisis"],
                    remove_marks=[],
                    delayed_effects=[],
                )
                events.append(onset)
                self._apply_event(onset, civs, universe)
            if not crisis and has_mark and civ.stats.legitimacy > 0.08:
                recovery = AppliedEvent(
                    event_id="EVT_LEGITIMACY_CRISIS_RECOVERY",
                    kind="policy",
                    scope="civ",
                    severity=1,
                    target=civ.id,
                    deltas={},
                    add_marks=[],
                    remove_marks=["LegitimacyCrisis"],
                    delayed_effects=[],
                )
                events.append(recovery)
                self._apply_event(recovery, civs, universe)
        return events

    def _update_missions(
        self, civs: List[CivilizationState], universe: UniverseState
    ) -> List[AppliedEvent]:
        applied: List[AppliedEvent] = []
        for beacon in universe.beacons:
            if not isinstance(beacon, dict):
                continue
            strength = float(beacon.get("strength", 0.0))
            decay = float(beacon.get("decay", 0.0))
            beacon["strength"] = max(0.0, strength - decay)
        universe.beacons = [b for b in universe.beacons if b.get("strength", 0.0) > 0.0]

        for civ in civs:
            if not civ.alive:
                continue
            updated = []
            for mission in civ.missions:
                if not isinstance(mission, dict):
                    continue
                if mission.get("status") != "enroute":
                    updated.append(mission)
                    continue
                mission["eta"] = int(mission.get("eta", 0)) - 1
                if mission["eta"] > 0:
                    updated.append(mission)
                    continue
                outcome_event, status = self._resolve_mission(civ, mission, universe)
                mission["status"] = status
                mission["eta"] = 0
                updated.append(mission)
                applied.append(outcome_event)
            civ.missions = updated
        return applied

    def _resolve_mission(
        self,
        civ: CivilizationState,
        mission: Dict[str, object],
        universe: UniverseState,
    ) -> Tuple[AppliedEvent, str]:
        mission_type = mission.get("type")
        to_system = mission.get("to_system")
        from_system = mission.get("from_system")
        success = False
        if mission_type == "probe":
            base = 0.75
            mod = (civ.stats.innovation - 0.5) * 0.2
            mod += (civ.stats.stability - 0.5) * 0.1
            mod -= (civ.stats.eco_pressure - 0.5) * 0.1
            success = self.rng.random() < max(0.05, min(0.95, base + mod))
        elif mission_type == "colony":
            base = 0.65
            mod = (civ.stats.food_security - 0.5) * 0.2
            mod += (civ.stats.health - 0.5) * 0.15
            mod += (civ.stats.stability - 0.5) * 0.1
            mod -= (civ.stats.inequality - 0.5) * 0.1
            success = self.rng.random() < max(0.05, min(0.95, base + mod))

        if success:
            add_marks = []
            if to_system and to_system not in civ.known_systems:
                civ.known_systems.append(to_system)
            if to_system:
                universe.beacons.append(
                    {
                        "id": f"beacon_{civ.id}_{to_system}_{universe.cycle}",
                        "system": to_system,
                        "owner": civ.id,
                        "strength": 0.7,
                        "decay": 0.01,
                        "created_cycle": universe.cycle,
                    }
                )
                add_marks.append(f"Mapped_{to_system}")
                route = {
                    "owner": civ.id,
                    "from_system": from_system,
                    "to_system": to_system,
                    "type": mission_type,
                    "created_cycle": universe.cycle,
                }
                if route not in civ.established_routes:
                    civ.established_routes.append(route)
            event_id = f"MISSION_{mission_type.upper()}_SUCCESS"
            add_marks.append(f"{mission_type.title()}Success")
            if mission_type == "colony":
                add_marks.append("ExtrasolarOutpost")
            status = "success"
        else:
            event_id = f"MISSION_{mission_type.upper()}_FAILED"
            add_marks = ["LostProbe"] if mission_type == "probe" else ["FrontierDisaster"]
            status = "failed"
        deltas = {}
        if success:
            if mission_type == "probe":
                deltas = {"legitimacy": 0.03, "cohesion": 0.01}
            elif mission_type == "colony":
                deltas = {"legitimacy": 0.04, "stability": -0.01}
        return AppliedEvent(
            event_id=event_id,
            kind="cosmic",
            scope="civ",
            severity=2,
            target=civ.id,
            deltas=deltas,
            add_marks=add_marks,
            remove_marks=[],
            delayed_effects=[],
        ), status

    def _apply_internal_drift(self, civs: List[CivilizationState]) -> None:
        for civ in civs:
            if not civ.alive:
                continue
            stats = civ.stats.as_dict()
            if stats["inequality"] >= 0.60 or stats["stability"] <= 0.40:
                stats["elite_power"] = clamp(
                    stats["elite_power"] + 0.01 * stats["extraction_rate"]
                )
            if stats["cohesion"] <= 0.40:
                stats["legitimacy"] = clamp(stats["legitimacy"] - 0.02)
            if stats["food_security"] <= 0.35 or stats["health"] <= 0.35:
                stats["legitimacy"] = clamp(stats["legitimacy"] - 0.015)
            if stats["legitimacy"] <= 0.30:
                stats["cohesion"] = clamp(stats["cohesion"] - 0.01)
                stats["stability"] = clamp(stats["stability"] - 0.01)
            crisis, severe = self._legitimacy_crisis_levels(civ)
            if crisis:
                stats["eco_pressure"] = clamp(
                    stats["eco_pressure"] + (0.015 if severe else 0.01)
                )
                stats["extraction_rate"] = clamp(
                    stats["extraction_rate"] + (0.015 if severe else 0.01)
                )
                stats["innovation"] = clamp(
                    stats["innovation"] - (0.01 if severe else 0.005)
                )
            recovery = 0.0
            if (
                stats["food_security"] >= 0.65
                and stats["health"] >= 0.60
                and stats["stability"] >= 0.45
            ):
                recovery += 0.01
                if stats["inequality"] <= 0.45:
                    recovery += 0.005
            if crisis and recovery:
                recovery *= 0.5
            if recovery:
                stats["legitimacy"] = clamp(stats["legitimacy"] + recovery)
            if (
                stats["stability"] >= 0.55
                and stats["food_security"] >= 0.60
                and stats["health"] >= 0.55
            ):
                stats["innovation"] = clamp(stats["innovation"] + 0.005)
            if civ.stage in ("industrial", "space") and stats["stability"] >= 0.50:
                stats["innovation"] = clamp(stats["innovation"] + 0.005)
                stats["eco_pressure"] = clamp(stats["eco_pressure"] + 0.003)
            civ.stats = CivStats(**stats)

    def _passes_preconditions(
        self, event: EventDefinition, civ: CivilizationState, universe: UniverseState
    ) -> bool:
        if not event.preconditions:
            return True
        evaluator = _PreconditionEvaluator(civ, universe)
        for expr in event.preconditions:
            try:
                tree = ast.parse(expr, mode="eval")
                if not evaluator.visit(tree):
                    return False
            except Exception:
                return False
        return True

    def _roll_events_for_civ(
        self,
        civ: CivilizationState,
        universe: UniverseState,
        severity_min: int,
        severity_max: int,
        count: int,
    ) -> List[AppliedEvent]:
        selected: List[AppliedEvent] = []
        for _ in range(count):
            eligible = self.eligible_events(civ, universe, "civ", severity_min, severity_max)
            if not eligible:
                break
            event = self._weighted_pick(eligible, civ, universe, False)
            selected.append(self._make_applied_event(event, civ.id, civ, universe))
            universe.cooldowns[self._cooldown_key(event.id, civ.id)] = universe.cycle
        return selected

    def _roll_events_for_global(
        self,
        universe: UniverseState,
        severity_min: int,
        severity_max: int,
        count: int,
        global_stage_bias: bool,
    ) -> List[AppliedEvent]:
        selected: List[AppliedEvent] = []
        dummy_civ = CivilizationState(
            id="global",
            name="global",
            color="#000000",
            alive=True,
            extinct=False,
            extinct_cycle=None,
            home_system="",
            stats=CivStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            marks=[],
        )
        for _ in range(count):
            eligible = self.eligible_events(
                dummy_civ, universe, "global", severity_min, severity_max
            )
            if not eligible:
                break
            event = self._weighted_pick(eligible, None, universe, global_stage_bias)
            selected.append(self._make_applied_event(event, "global", None, universe))
            universe.cooldowns[self._cooldown_key(event.id, "global")] = universe.cycle
        return selected

    def _weighted_pick(
        self,
        events: List[EventDefinition],
        civ: Optional[CivilizationState],
        universe: Optional[UniverseState],
        global_stage_bias: bool,
    ) -> EventDefinition:
        weights = self.ruleset.modify_weights(
            civ=civ, universe=universe, eligible_events=events
        )
        adjusted = []
        for event, base in zip(events, weights):
            factor = self._agenda_weight_factor(event, civ)
            factor *= self._stance_weight_factor(event, civ)
            factor *= self._stage_weight_factor(event, civ, global_stage_bias)
            factor *= self._legitimacy_crisis_weight_factor(event, civ)
            weight = max(float(base) * factor, 0.01)
            adjusted.append(weight)
        weights = adjusted
        return self.rng.choices(events, weights=weights, k=1)[0]

    def _agenda_weight_factor(
        self, event: EventDefinition, civ: Optional[CivilizationState]
    ) -> float:
        if civ is None:
            return 1.0
        agenda = (civ.agenda or "SURVIVE").strip().upper()
        if agenda == "SURVIVE":
            return 1.0
        event_id = event.id.upper()
        if agenda == "EXPLORE":
            keywords = ("SCOUT", "EXPLORE", "OUTPOST", "NAV", "SKY")
            if event.kind in ("technology", "cosmic") or any(k in event_id for k in keywords):
                return 1.8
            return 1.0
        if agenda == "REFORM":
            return 1.6 if event.kind == "policy" else 1.0
        if agenda == "DOMINATE":
            return 1.6 if event.kind in ("conflict", "politics") else 1.0
        if agenda == "WITHDRAW":
            factor = 1.0
            if event.kind == "culture":
                factor *= 1.6
            if event.kind == "technology":
                factor *= 0.7
            return factor
        return 1.0

    def _stage_weight_factor(
        self,
        event: EventDefinition,
        civ: Optional[CivilizationState],
        global_stage_bias: bool,
    ) -> float:
        if event.scope == "global":
            return 1.15 if global_stage_bias and event.kind == "cosmic" else 1.0
        if civ is None:
            return 1.0
        if civ.stage == "stone" and event.kind == "technology":
            if any(tag in event.id.upper() for tag in ("BREAKTHROUGH", "ACCIDENT", "METAL_WORKING")):
                return 0.5
        return 1.0

    def _stance_weight_factor(
        self, event: EventDefinition, civ: Optional[CivilizationState]
    ) -> float:
        if civ is None:
            return 1.0
        stance = (civ.stance or "PRAGMATIC").strip().upper()
        event_id = event.id.upper()
        if stance == "PRAGMATIC":
            return 1.0
        if stance == "ZEALOUS":
            factor = 1.0
            if event.kind == "culture":
                factor *= 1.5
            if event.kind == "politics":
                factor *= 1.25
            if any(tag in event_id for tag in ("TABOO", "SCHISM")):
                factor *= 1.25
            return factor
        if stance == "CYNICAL":
            factor = 1.0
            if event.kind == "society" and any(tag in event_id for tag in ("RENT", "OLIGARCH", "BLACK_MARKET")):
                factor *= 1.6
            if any(tag in event_id for tag in ("COMMONS", "PUBLIC_WORKS")):
                factor *= 0.8
            return factor
        if stance == "COMPASSIONATE":
            factor = 1.0
            if event.kind == "policy":
                factor *= 1.6
            if "BACKLASH" in event_id:
                factor *= 1.3
            return factor
        if stance == "NIHILISTIC":
            factor = 1.0
            if event.kind == "culture":
                factor *= 1.4
            if event.kind == "conflict" and civ.stats.legitimacy <= 0.40:
                factor *= 1.3
            return factor
        return 1.0

    def _legitimacy_crisis_weight_factor(
        self, event: EventDefinition, civ: Optional[CivilizationState]
    ) -> float:
        if civ is None:
            return 1.0
        crisis, _severe = self._legitimacy_crisis_levels(civ)
        if not crisis:
            return 1.0
        crisis_ids = {
            "EVT_GENERAL_STRIKE",
            "EVT_MASS_UPRISING",
            "EVT_REPRESSION_CAMPAIGN",
            "EVT_SECESSION_ATTEMPT",
            "EVT_EMERGENCY_REFORM",
        }
        factor = 1.0
        if event.id in crisis_ids:
            factor *= 1.5
        if event.kind == "policy":
            factor *= 1.2
        if event.kind == "cosmic":
            factor *= 0.85
        return factor

    def _make_applied_event(
        self,
        event: EventDefinition,
        target: str,
        civ: Optional[CivilizationState],
        universe: Optional[UniverseState],
    ) -> AppliedEvent:
        severity = self.rng.randint(event.severity_range[0], event.severity_range[1])
        effects = event.effects
        spawn_mission = None
        contact_with = None
        contact_system = None
        if civ is not None and universe is not None:
            spawn_mission = self._build_spawn_mission(event, civ, universe)
            contact_with, contact_system = self._pick_contact_target(event, civ, universe)
        effects = self._adjust_event_effects(event, effects, civ)
        delayed_effects = self._build_delayed_effects(event, target, effects, civ)
        return AppliedEvent(
            event_id=event.id,
            kind=event.kind,
            scope=event.scope,
            severity=severity,
            target=target,
            deltas=effects.get("deltas", {}),
            add_marks=effects.get("add_marks", []),
            remove_marks=effects.get("remove_marks", []),
            delayed_effects=delayed_effects,
            spawn_mission=spawn_mission,
            contact_with=contact_with,
            contact_system=contact_system,
        )

    def _build_delayed_effects(
        self,
        event: EventDefinition,
        target: str,
        effects: Dict[str, object],
        civ: Optional[CivilizationState],
    ) -> List[DelayedEffect]:
        delayed: List[DelayedEffect] = []
        for item in effects.get("delayed_effects", []):
            if not isinstance(item, dict):
                continue
            cycle_delay = int(item.get("cycle_delay", 0))
            payload = item
            branch = item.get("branch")
            if isinstance(branch, dict):
                success = self.rng.random() < 0.5
                choice = branch.get("success") if success else branch.get("failure")
                if success and event.id == "EVT_FIRST_OUTPOST" and civ is not None:
                    choice = self._outpost_success_payload(civ)
                payload = choice if isinstance(choice, dict) else {}
            delayed.append(
                DelayedEffect(
                    cycle_delay=cycle_delay,
                    target=target if event.scope == "civ" else "global",
                    deltas=payload.get("deltas", {}) if isinstance(payload, dict) else {},
                    add_marks=payload.get("add_marks", []) if isinstance(payload, dict) else [],
                    remove_marks=payload.get("remove_marks", []) if isinstance(payload, dict) else [],
                )
            )
            if isinstance(payload, dict):
                for nested in payload.get("delayed_effects", []):
                    if not isinstance(nested, dict):
                        continue
                    nested_delay = int(nested.get("cycle_delay", 0))
                    delayed.append(
                        DelayedEffect(
                            cycle_delay=cycle_delay + nested_delay,
                            target=target if event.scope == "civ" else "global",
                            deltas=nested.get("deltas", {}),
                            add_marks=nested.get("add_marks", []),
                            remove_marks=nested.get("remove_marks", []),
                        )
                    )
        return delayed

    def _adjust_event_effects(
        self, event: EventDefinition, effects: Dict[str, object], civ: Optional[CivilizationState]
    ) -> Dict[str, object]:
        if civ is None:
            return effects
        if event.id == "EVT_CONTACT_SIGNAL":
            positive = self._contact_signal_positive(civ)
            if positive:
                return {
                    **effects,
                    "deltas": {
                        "innovation": 0.04,
                        "cohesion": 0.02,
                        "stability": 0.02,
                        "legitimacy": 0.02,
                    },
                }
            return {
                **effects,
                "deltas": {
                    "innovation": 0.03,
                    "cohesion": -0.01,
                    "stability": -0.02,
                    "legitimacy": -0.02,
                },
            }
        return effects

    def _contact_signal_positive(self, civ: CivilizationState) -> bool:
        agenda = (civ.agenda or "").upper()
        stance = (civ.stance or "").upper()
        if stance in ("COMPASSIONATE", "ZEALOUS"):
            return True
        if stance in ("NIHILISTIC", "CYNICAL"):
            return False
        if agenda in ("EXPLORE", "REFORM"):
            return True
        if agenda in ("DOMINATE", "WITHDRAW"):
            return False
        return civ.stats.legitimacy >= 0.50

    def _build_spawn_mission(
        self,
        event: EventDefinition,
        civ: CivilizationState,
        universe: UniverseState,
    ) -> Optional[Dict[str, object]]:
        spawn = event.effects.get("spawn_mission")
        if not isinstance(spawn, dict):
            return None
        mission_type = spawn.get("type")
        if mission_type not in ("probe", "colony"):
            return None
        system_names = [name for name in universe.system_names if name]
        if not system_names:
            return None
        target = None
        if mission_type == "probe":
            candidates = [s for s in system_names if s not in civ.known_systems]
            if not candidates:
                return None
            target = self.rng.choice(sorted(candidates))
        elif mission_type == "colony":
            candidates = [s for s in civ.known_systems if s != civ.home_system]
            if not candidates:
                return None
            target = self.rng.choice(sorted(candidates))
        eta_min = int(spawn.get("eta_min", 2))
        eta_max = int(spawn.get("eta_max", 5))
        eta = self.rng.randint(min(eta_min, eta_max), max(eta_min, eta_max))
        mission_id = f"{mission_type}_{civ.id}_{universe.cycle}_{self.rng.randint(100,999)}"
        return {
            "id": mission_id,
            "type": mission_type,
            "from_system": civ.home_system,
            "to_system": target,
            "eta": eta,
            "owner": civ.id,
            "status": "enroute",
        }

    def _pick_contact_target(
        self,
        event: EventDefinition,
        civ: CivilizationState,
        universe: UniverseState,
    ) -> Tuple[Optional[str], Optional[str]]:
        if event.id != "EVT_CONTACT_DIRECT":
            return None, None
        owned = {b.get("system") for b in universe.beacons if b.get("owner") == civ.id}
        candidates = []
        for beacon in universe.beacons:
            if not isinstance(beacon, dict):
                continue
            owner = beacon.get("owner")
            system = beacon.get("system")
            if owner == civ.id:
                continue
            if system in owned and system:
                candidates.append((str(owner), system))
        if not candidates:
            return None, None
        candidates = sorted(candidates)
        return candidates[0][0], candidates[0][1]

    def _outpost_success_payload(self, civ: CivilizationState) -> Dict[str, object]:
        inequality = civ.stats.inequality
        elite_power = civ.stats.elite_power
        stance = (civ.stance or "").strip().upper()
        extraction = inequality >= 0.60 or elite_power >= 0.60 or stance == "CYNICAL"
        if extraction:
            return {
                "deltas": {
                    "food_security": 0.06,
                    "innovation": 0.05,
                    "inequality": 0.05,
                    "eco_pressure": 0.04,
                },
                "add_marks": ["FrontierExtraction"],
                "remove_marks": [],
                "delayed_effects": [
                    {"cycle_delay": 2, "deltas": {"legitimacy": -0.04}, "add_marks": [], "remove_marks": []}
                ],
            }
        return {
            "deltas": {
                "food_security": 0.06,
                "innovation": 0.04,
                "inequality": -0.02,
                "cohesion": 0.02,
                "eco_pressure": 0.03,
            },
            "add_marks": ["FrontierCommons"],
            "remove_marks": [],
        }

    def _apply_event(
        self, event: AppliedEvent, civs: List[CivilizationState], universe: UniverseState
    ) -> None:
        targets = civs if event.scope == "global" else [c for c in civs if c.id == event.target]
        for civ in targets:
            if not civ.alive:
                continue
            stats = civ.stats.as_dict()
            for key, delta in event.deltas.items():
                if key in stats:
                    stats[key] = clamp(
                        stats[key] + self._adjust_crisis_delta(civ, key, float(delta))
                    )
            civ.stats = CivStats(**stats)
            for mark in event.add_marks:
                if mark not in civ.marks:
                    civ.marks.append(mark)
            for mark in event.remove_marks:
                if mark in civ.marks:
                    civ.marks.remove(mark)
            if event.spawn_mission and event.scope == "civ":
                civ.missions.append(event.spawn_mission)
        if event.scope == "global":
            for mark in event.add_marks:
                if mark not in universe.global_marks:
                    universe.global_marks.append(mark)
            for mark in event.remove_marks:
                if mark in universe.global_marks:
                    universe.global_marks.remove(mark)
        if event.contact_with and event.contact_with != event.target:
            self._register_contact(event, civs)
        for delayed in event.delayed_effects:
            universe.global_pending_effects.append(delayed)

    def _apply_pending_effects(
        self, civs: List[CivilizationState], universe: UniverseState
    ) -> List[DelayedEffect]:
        if not universe.global_pending_effects:
            return []
        remaining: List[DelayedEffect] = []
        applied: List[DelayedEffect] = []
        for effect in universe.global_pending_effects:
            effect.cycle_delay -= 1
            if effect.cycle_delay > 0:
                remaining.append(effect)
                continue
            targets = (
                civs
                if effect.target == "global"
                else [c for c in civs if c.id == effect.target]
            )
            for civ in targets:
                if not civ.alive:
                    continue
                stats = civ.stats.as_dict()
                for key, delta in effect.deltas.items():
                    if key in stats:
                        stats[key] = clamp(
                            stats[key] + self._adjust_crisis_delta(civ, key, float(delta))
                        )
                civ.stats = CivStats(**stats)
                for mark in effect.add_marks:
                    if effect.target == "global":
                        if mark not in universe.global_marks:
                            universe.global_marks.append(mark)
                    elif mark not in civ.marks:
                        civ.marks.append(mark)
                for mark in effect.remove_marks:
                    if effect.target == "global":
                        if mark in universe.global_marks:
                            universe.global_marks.remove(mark)
                    elif mark in civ.marks:
                        civ.marks.remove(mark)
            applied.append(effect)
        universe.global_pending_effects = remaining
        return applied

    def _cooldown_key(self, event_id: str, target: str) -> str:
        return f"{target}:{event_id}"

    def _adjust_crisis_delta(
        self, civ: CivilizationState, key: str, delta: float
    ) -> float:
        if delta >= 0:
            return delta
        if key not in ("stability", "cohesion", "health", "food_security"):
            return delta
        crisis, severe = self._legitimacy_crisis_levels(civ)
        if not crisis:
            return delta
        multiplier = 1.60 if severe else 1.35
        return delta * multiplier

    def _legitimacy_crisis_levels(self, civ: CivilizationState) -> Tuple[bool, bool]:
        crisis = civ.stats.legitimacy <= 0.05
        severe = civ.stats.legitimacy <= 0.02
        return crisis, severe

    def _register_contact(self, event: AppliedEvent, civs: List[CivilizationState]) -> None:
        civ = next((c for c in civs if c.id == event.target), None)
        other = next((c for c in civs if c.id == event.contact_with), None)
        if not civ or not other:
            return
        if not civ.alive or not other.alive:
            return
        for actor, counterpart in ((civ, other), (other, civ)):
            if counterpart.id not in actor.known_contacts:
                actor.known_contacts.append(counterpart.id)
            if counterpart.id not in actor.contact_intents:
                actor.contact_intents[counterpart.id] = self._relation_intent(actor)
            if "ContactEstablished" not in actor.marks:
                actor.marks.append("ContactEstablished")
            mark = f"ContactEstablished_{counterpart.id}"
            if mark not in actor.marks:
                actor.marks.append(mark)

    def _relation_intent(self, civ: CivilizationState) -> str:
        agenda = (civ.agenda or "").upper()
        stance = (civ.stance or "").upper()
        if agenda == "DOMINATE" or stance == "CYNICAL":
            return "RAID"
        if stance == "COMPASSIONATE" and civ.stats.legitimacy >= 0.55:
            return "TRADE"
        if agenda == "WITHDRAW" or stance == "NIHILISTIC":
            return "AVOID"
        return "TRADE"

    def _update_progress_and_stage(
        self, civs: List[CivilizationState], universe: UniverseState
    ) -> List[AppliedEvent]:
        stage_events: List[AppliedEvent] = []
        for civ in civs:
            if not civ.alive:
                continue
            progress = civ.progress
            stats = civ.stats
            progress += 0.02 * stats.food_security
            progress += 0.02 * stats.health
            progress += 0.015 * stats.stability
            progress += 0.02 * stats.innovation
            progress -= 0.02 * stats.eco_pressure
            progress -= 0.01 * stats.inequality
            if stats.cohesion <= 0.20:
                progress -= 0.02
            civ.progress = clamp(progress)

            upgraded = self._stage_from_progress(civ.progress, civ.stage)
            if upgraded != civ.stage:
                civ.stage = upgraded
                mark = f"Stage_{upgraded}"
                add_marks = [mark]
                if upgraded == "space":
                    civ.reach = max(civ.reach, 1)
                    add_marks.append("InterstellarAge")
                    if civ.home_system:
                        universe.beacons.append(
                            {
                                "id": f"beacon_{civ.id}_{civ.home_system}_{universe.cycle}",
                                "system": civ.home_system,
                                "owner": civ.id,
                                "strength": 0.6,
                                "decay": 0.01,
                                "created_cycle": universe.cycle,
                            }
                        )
                stage_event = AppliedEvent(
                    event_id=f"STAGE_{upgraded.upper()}",
                    kind="progress",
                    scope="civ",
                    severity=1,
                    target=civ.id,
                    deltas={},
                    add_marks=add_marks,
                    remove_marks=[],
                    delayed_effects=[],
                )
                stage_events.append(stage_event)
                self._apply_event(stage_event, civs, universe)
        return stage_events

    def _stage_from_progress(self, progress: float, current: str) -> str:
        current_idx = STAGE_ORDER.get(current)
        if current_idx is None:
            return current
        desired = current
        for threshold, stage in STAGE_THRESHOLDS:
            if progress >= threshold:
                desired = stage
                break
        desired_idx = STAGE_ORDER.get(desired, current_idx)
        if desired_idx > current_idx:
            return desired
        return current
