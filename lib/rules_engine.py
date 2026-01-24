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

        if self.ruleset.should_roll_global(universe, self.rng):
            global_events.extend(self._roll_events_for_global(universe, 1, 5, 1))

        for event in civ_events:
            self._apply_event(event, civs, universe)
        for event in global_events:
            self._apply_event(event, civs, universe)

        delayed_applied.extend(self._apply_pending_effects(civs, universe))

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
        weights = self.ruleset.modify_weights(
            civ=None, universe=None, eligible_events=events
        )
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

    def _cooldown_key(self, event_id: str, target: str) -> str:
        return f"{target}:{event_id}"
