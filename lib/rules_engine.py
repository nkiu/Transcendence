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

    def as_dict(self) -> Dict[str, float]:
        return {
            "eco_pressure": self.eco_pressure,
            "inequality": self.inequality,
            "cohesion": self.cohesion,
            "stability": self.stability,
            "innovation": self.innovation,
            "food_security": self.food_security,
            "health": self.health,
        }


@dataclass
class CivilizationState:
    id: str
    name: str
    color: str
    alive: bool
    extinct: bool
    extinct_cycle: Optional[int]
    stats: CivStats
    marks: List[str] = field(default_factory=list)
    consecutive_extreme_eco: int = 0
    consecutive_extreme_unrest: int = 0
    consecutive_famine: int = 0
    consecutive_zero_stability: int = 0


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
        raise ValueError(f"Unknown name {node.id}")

    def visit_Constant(self, node: ast.Constant):
        return node.value

    def visit_Call(self, node: ast.Call):
        if not isinstance(node.func, ast.Name) or len(node.args) != 1:
            raise ValueError("Unsupported function call")
        arg = self.visit(node.args[0])
        if not isinstance(arg, str):
            raise ValueError("Mark name must be string")
        if node.func.id == "has_mark":
            return arg in self.civ.marks
        if node.func.id == "has_global":
            return arg in self.universe.global_marks
        raise ValueError(f"Unsupported function {node.func.id}")

    def generic_visit(self, node: ast.AST):
        raise ValueError(f"Unsupported expression node: {type(node).__name__}")


class RulesEngine:
    def __init__(self, catalog_path: str, rng_seed: int) -> None:
        self.catalog_path = catalog_path
        self.rng = random.Random(rng_seed)
        self.events = self._load_catalog(catalog_path)

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
            stressed = (
                civ.stats.eco_pressure > 0.55
                or civ.stats.stability < 0.55
                or civ.stats.food_security < 0.55
            )
            crisis = (
                civ.stats.eco_pressure > 0.75
                or civ.stats.stability < 0.35
                or civ.stats.cohesion < 0.35
                or civ.stats.food_security < 0.35
            )
            if stressed:
                minor_rolls = self.rng.randint(0, 2)
                civ_events.extend(
                    self._roll_events_for_civ(civ, universe, 1, 2, minor_rolls)
                )
            if crisis:
                major_rolls = self.rng.randint(0, 1)
                civ_events.extend(
                    self._roll_events_for_civ(civ, universe, 3, 5, major_rolls)
                )

        global_chance = 0.30 if "CosmicInstability" in universe.global_marks else 0.15
        if self.rng.random() < global_chance:
            if self.rng.randint(0, 1) == 1:
                global_events.extend(
                    self._roll_events_for_global(universe, 1, 5, 1)
                )

        for event in civ_events:
            self._apply_event(event, civs, universe)
        for event in global_events:
            self._apply_event(event, civs, universe)

        delayed_applied.extend(self._apply_pending_effects(civs, universe))

        for civ in civs:
            if not civ.alive:
                continue
            if self._apply_hard_extinction(civ, universe):
                continue
            collapse_event = self._check_collapse(civ, universe)
            if collapse_event:
                civ_events.append(collapse_event)
                self._apply_event(collapse_event, civs, universe)

        return civ_events, global_events, delayed_applied

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
            event = self._weighted_pick(eligible)
            selected.append(self._make_applied_event(event, civ.id))
            universe.cooldowns[self._cooldown_key(event.id, civ.id)] = universe.cycle
        return selected

    def _roll_events_for_global(
        self,
        universe: UniverseState,
        severity_min: int,
        severity_max: int,
        count: int,
    ) -> List[AppliedEvent]:
        selected: List[AppliedEvent] = []
        dummy_civ = CivilizationState(
            id="global",
            name="global",
            color="#000000",
            alive=True,
            extinct=False,
            extinct_cycle=None,
            stats=CivStats(0, 0, 0, 0, 0, 0, 0),
            marks=[],
        )
        for _ in range(count):
            eligible = self.eligible_events(
                dummy_civ, universe, "global", severity_min, severity_max
            )
            if not eligible:
                break
            event = self._weighted_pick(eligible)
            selected.append(self._make_applied_event(event, "global"))
            universe.cooldowns[self._cooldown_key(event.id, "global")] = universe.cycle
        return selected

    def _weighted_pick(self, events: List[EventDefinition]) -> EventDefinition:
        weights = [event.weight_base for event in events]
        return self.rng.choices(events, weights=weights, k=1)[0]

    def _make_applied_event(self, event: EventDefinition, target: str) -> AppliedEvent:
        severity = self.rng.randint(event.severity_range[0], event.severity_range[1])
        effects = event.effects
        return AppliedEvent(
            event_id=event.id,
            kind=event.kind,
            scope=event.scope,
            severity=severity,
            target=target,
            deltas=effects.get("deltas", {}),
            add_marks=effects.get("add_marks", []),
            remove_marks=effects.get("remove_marks", []),
            delayed_effects=[
                DelayedEffect(
                    cycle_delay=int(item.get("cycle_delay", 0)),
                    target=target if event.scope == "civ" else "global",
                    deltas=item.get("deltas", {}),
                    add_marks=item.get("add_marks", []),
                    remove_marks=item.get("remove_marks", []),
                )
                for item in effects.get("delayed_effects", [])
            ],
        )

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
                    stats[key] = clamp(stats[key] + float(delta))
            civ.stats = CivStats(**stats)
            for mark in event.add_marks:
                if mark not in civ.marks:
                    civ.marks.append(mark)
            for mark in event.remove_marks:
                if mark in civ.marks:
                    civ.marks.remove(mark)
        if event.scope == "global":
            for mark in event.add_marks:
                if mark not in universe.global_marks:
                    universe.global_marks.append(mark)
            for mark in event.remove_marks:
                if mark in universe.global_marks:
                    universe.global_marks.remove(mark)
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
                        stats[key] = clamp(stats[key] + float(delta))
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

    def _check_collapse(
        self, civ: CivilizationState, universe: UniverseState
    ) -> Optional[AppliedEvent]:
        eco_extreme = civ.stats.eco_pressure > 0.95 and civ.stats.stability < 0.10
        unrest_extreme = civ.stats.cohesion < 0.10 and civ.stats.inequality > 0.90
        famine_extreme = civ.stats.food_security < 0.10

        civ.consecutive_extreme_eco = (
            civ.consecutive_extreme_eco + 1 if eco_extreme else 0
        )
        civ.consecutive_extreme_unrest = (
            civ.consecutive_extreme_unrest + 1 if unrest_extreme else 0
        )
        civ.consecutive_famine = civ.consecutive_famine + 1 if famine_extreme else 0

        if (
            civ.consecutive_extreme_eco < 2
            and civ.consecutive_extreme_unrest < 2
            and civ.consecutive_famine < 2
        ):
            return None

        civ.consecutive_extreme_eco = 0
        civ.consecutive_extreme_unrest = 0
        civ.consecutive_famine = 0
        outcome = self.roll_collapse_table(civ, universe)
        return outcome

    def _apply_hard_extinction(
        self, civ: CivilizationState, universe: UniverseState
    ) -> bool:
        if civ.stats.stability == 0.0:
            civ.consecutive_zero_stability += 1
        else:
            civ.consecutive_zero_stability = 0
        if (
            (civ.stats.cohesion == 0.0 and civ.stats.stability <= 0.05)
            or (civ.stats.food_security == 0.0 and civ.stats.health <= 0.05)
            or (civ.stats.health <= 0.05 and civ.stats.food_security <= 0.10)
            or (civ.stats.cohesion == 0.0 and civ.stats.food_security == 0.0)
            or (civ.consecutive_zero_stability >= 2)
        ):
            civ.alive = False
            civ.extinct = True
            civ.extinct_cycle = universe.cycle
            if "Extinct" not in civ.marks:
                civ.marks.append("Extinct")
            return True
        return False

    def roll_collapse_table(
        self, civ: CivilizationState, universe: UniverseState
    ) -> AppliedEvent:
        roll = self.rng.randint(1, 12)
        deltas: Dict[str, float] = {}
        add_marks: List[str] = []
        remove_marks: List[str] = []
        delayed: List[DelayedEffect] = []
        outcome_kind = "shock"
        if roll in (1, 2, 12):
            civ.alive = False
            civ.extinct = True
            civ.extinct_cycle = universe.cycle
            add_marks.append("Extinct")
            outcome_kind = "extinction"
        elif roll == 3:
            deltas = {"stability": -0.30, "cohesion": -0.25, "innovation": -0.20}
            add_marks.append("CollapsedInstitutions")
            outcome_kind = "collapse"
        elif roll == 4:
            deltas = {"health": -0.35, "food_security": -0.30}
            add_marks.append("MassGraves")
            delayed.append(
                DelayedEffect(
                    cycle_delay=2,
                    target=civ.id,
                    deltas={"cohesion": -0.15},
                    add_marks=[],
                    remove_marks=[],
                )
            )
            outcome_kind = "collapse"
        elif roll == 5:
            deltas = {"cohesion": -0.40}
            add_marks.append("FragmentedFactions")
            remove_marks.append("UnifiedFaith")
            outcome_kind = "fragmentation"
        elif roll == 6:
            deltas = {"inequality": 0.20, "stability": -0.20}
            add_marks.append("WarlordEra")
            outcome_kind = "fragmentation"
        elif roll == 7:
            deltas = {"stability": 0.10, "inequality": 0.25, "innovation": -0.15}
            add_marks.append("AuthoritarianLock")
            outcome_kind = "authoritarian_lock"
        elif roll == 8:
            deltas = {"cohesion": -0.20, "food_security": 0.05}
            add_marks.append("Diaspora")
            delayed.append(
                DelayedEffect(
                    cycle_delay=1,
                    target=civ.id,
                    deltas={"inequality": 0.10},
                    add_marks=[],
                    remove_marks=[],
                )
            )
            outcome_kind = "mass_migration"
        elif roll == 9:
            deltas = {"eco_pressure": 0.10, "health": -0.15}
            add_marks.append("TraumaCycle")
            delayed.append(
                DelayedEffect(
                    cycle_delay=2,
                    target=civ.id,
                    deltas={"cohesion": -0.10},
                    add_marks=[],
                    remove_marks=[],
                )
            )
            outcome_kind = "shock"
        elif roll == 10:
            deltas = {"innovation": -0.25, "stability": -0.10}
            add_marks.append("LostGeneration")
            outcome_kind = "shock"
        elif roll == 11:
            deltas = {"eco_pressure": 0.10, "food_security": -0.15}
            add_marks.append("AgriculturalFailure")
            outcome_kind = "collapse"

        return AppliedEvent(
            event_id=f"COLLAPSE_TABLE_{roll}",
            kind=outcome_kind,
            scope="civ",
            severity=5,
            target=civ.id,
            deltas=deltas,
            add_marks=add_marks,
            remove_marks=remove_marks,
            delayed_effects=delayed,
        )

    def _cooldown_key(self, event_id: str, target: str) -> str:
        return f"{target}:{event_id}"
