from dataclasses import dataclass
from typing import List

from lib.rules_engine import AppliedEvent, DelayedEffect, CivilizationState, UniverseState, clamp
from rulesets.harsh_realism import HarshRealismRuleset


PHASE_MARKS = (
    "Phase_0_Proto",
    "Phase_1_Industrial",
    "Phase_2_EarlySpace",
    "Phase_3_Spacefaring",
)
POST_SCARCITY_MARK = "PostScarcity"
GOOD_TOTAL_PREFIX = "GoodCycleTotal:"


@dataclass
class CheatUtopiaRuleset(HarshRealismRuleset):
    name: str = "cheat_utopia"
    description: str = (
        "Utopian cheat mode: strong stabilizing attractor; civilizations almost "
        "always reach high phases."
    )

    def _ensure_phase(self, civ: CivilizationState) -> None:
        if any(mark in civ.marks for mark in PHASE_MARKS):
            return
        civ.marks.append(PHASE_MARKS[0])

    def _get_phase(self, civ: CivilizationState) -> int:
        self._ensure_phase(civ)
        for idx, mark in enumerate(PHASE_MARKS):
            if mark in civ.marks:
                return idx
        return 0

    def _set_phase(self, civ: CivilizationState, phase: int) -> None:
        for mark in PHASE_MARKS:
            if mark in civ.marks:
                civ.marks.remove(mark)
        civ.marks.append(PHASE_MARKS[phase])

    def _get_good_cycle_total(self, civ: CivilizationState) -> int:
        for mark in civ.marks:
            if mark.startswith(GOOD_TOTAL_PREFIX):
                raw = mark[len(GOOD_TOTAL_PREFIX):]
                try:
                    return int(raw)
                except ValueError:
                    return 0
        return 0

    def _set_good_cycle_total(self, civ: CivilizationState, total: int) -> None:
        for mark in list(civ.marks):
            if mark.startswith(GOOD_TOTAL_PREFIX):
                civ.marks.remove(mark)
        civ.marks.append(f"{GOOD_TOTAL_PREFIX}{total}")

    def _apply_deltas(self, civ: CivilizationState, deltas: dict) -> None:
        stats = civ.stats.as_dict()
        for key, delta in deltas.items():
            if key in stats:
                stats[key] = clamp(stats[key] + float(delta))
        civ.stats = type(civ.stats)(**stats)

    def global_event_chance(self, universe: UniverseState) -> float:
        return 0.08 if "CosmicInstability" in universe.global_marks else 0.03

    def should_roll_global(self, universe: UniverseState, rng) -> bool:
        if rng.random() < self.global_event_chance(universe):
            return rng.randint(0, 1) == 1
        return False

    def hard_extinction(self, civ: CivilizationState, universe: UniverseState) -> bool:
        self._ensure_phase(civ)

        # Phase progression: fast ascension with a small sustainability downside.
        good_cycle = (
            civ.stats.stability >= 0.55
            and civ.stats.cohesion >= 0.55
            and civ.stats.health >= 0.55
        )
        if good_cycle:
            civ.consecutive_good_cycles += 1
            total_good = self._get_good_cycle_total(civ) + 1
            self._set_good_cycle_total(civ, total_good)
        else:
            civ.consecutive_good_cycles = 0
            total_good = self._get_good_cycle_total(civ)

        phase = self._get_phase(civ)
        if civ.consecutive_good_cycles >= 2 and phase < 3:
            self._set_phase(civ, phase + 1)
            civ.consecutive_good_cycles = 0
            self._apply_deltas(
                civ,
                {
                    "stability": 0.06,
                    "cohesion": 0.06,
                    "innovation": 0.08,
                    "health": 0.05,
                    "food_security": 0.05,
                    "eco_pressure": 0.04,
                    "inequality": 0.02,
                },
            )
            if "AscensionStep" not in civ.marks:
                civ.marks.append("AscensionStep")

        # Guardian stabilizer: explicit cheat safety net + delayed moral hazard.
        if (
            civ.stats.stability < 0.20
            or civ.stats.cohesion < 0.20
            or civ.stats.health < 0.20
            or civ.stats.food_security < 0.20
        ):
            self._apply_deltas(
                civ,
                {
                    "stability": 0.25,
                    "cohesion": 0.25,
                    "health": 0.20,
                    "food_security": 0.20,
                    "inequality": -0.12,
                    "eco_pressure": -0.12,
                    "innovation": -0.12,
                },
            )
            if "GuardianIntervention" not in civ.marks:
                civ.marks.append("GuardianIntervention")
            universe.global_pending_effects.append(
                DelayedEffect(
                    cycle_delay=2,
                    target=civ.id,
                    deltas={"inequality": 0.10, "eco_pressure": 0.10},
                    add_marks=[],
                    remove_marks=[],
                )
            )

        # Post-scarcity attractor once phase 3 proves sustained success.
        if phase == 3 and total_good >= 5:
            if POST_SCARCITY_MARK not in civ.marks:
                civ.marks.append(POST_SCARCITY_MARK)

        if POST_SCARCITY_MARK in civ.marks:
            civ.stats.eco_pressure = min(civ.stats.eco_pressure, 0.30)
            civ.stats.food_security = max(civ.stats.food_security, 0.75)
            civ.stats.health = max(civ.stats.health, 0.75)
            civ.stats.stability = max(civ.stats.stability, 0.65)
            civ.stats.cohesion = max(civ.stats.cohesion, 0.65)

        if (
            "CosmicAnnihilation" in universe.global_marks
            and civ.stats.health == 0.0
            and civ.stats.food_security == 0.0
        ):
            civ.alive = False
            civ.extinct = True
            civ.extinct_cycle = universe.cycle
            if "Extinct" not in civ.marks:
                civ.marks.append("Extinct")
            return True

        civ.alive = True
        civ.extinct = False
        civ.extinct_cycle = None
        return False

    def collapse_trigger(self, civ: CivilizationState, universe: UniverseState) -> bool:
        eco_extreme = civ.stats.eco_pressure > 0.98 and civ.stats.stability < 0.10
        unrest_extreme = civ.stats.cohesion < 0.10 and civ.stats.inequality > 0.95
        famine_extreme = civ.stats.food_security < 0.08

        civ.consecutive_extreme_eco = (
            civ.consecutive_extreme_eco + 1 if eco_extreme else 0
        )
        civ.consecutive_extreme_unrest = (
            civ.consecutive_extreme_unrest + 1 if unrest_extreme else 0
        )
        civ.consecutive_famine = civ.consecutive_famine + 1 if famine_extreme else 0

        if (
            civ.consecutive_extreme_eco < 4
            and civ.consecutive_extreme_unrest < 4
            and civ.consecutive_famine < 4
        ):
            return False

        civ.consecutive_extreme_eco = 0
        civ.consecutive_extreme_unrest = 0
        civ.consecutive_famine = 0
        return True

    def collapse_outcome(
        self, civ: CivilizationState, universe: UniverseState, rng
    ) -> AppliedEvent:
        return AppliedEvent(
            event_id="CHEAT_REORGANIZATION",
            kind="reorganization",
            scope="civ",
            severity=3,
            target=civ.id,
            deltas={
                "stability": -0.08,
                "cohesion": -0.08,
                "inequality": 0.12,
                "innovation": -0.05,
            },
            add_marks=["InstitutionalReset"],
            remove_marks=[],
            delayed_effects=[
                DelayedEffect(
                    cycle_delay=1,
                    target=civ.id,
                    deltas={"stability": 0.10, "cohesion": 0.08},
                    add_marks=[],
                    remove_marks=[],
                )
            ],
        )

    def modify_weights(
        self,
        civ: CivilizationState,
        universe: UniverseState,
        eligible_events: List,
    ) -> List[float]:
        destructive = {"war", "plague", "famine", "disaster", "shock", "collapse", "extinction"}
        constructive = {
            "reform",
            "infrastructure",
            "education",
            "health",
            "trade",
            "diplomacy",
        }
        crisis = self.is_in_crisis(civ, universe) if civ and universe else False
        weights = []
        for event in eligible_events:
            weight = float(event.weight_base)
            if event.kind in destructive:
                factor = 0.5 if crisis else 0.25
                weight *= factor
                if crisis and weight > 1.0:
                    weight = 1.0
            elif event.kind in constructive:
                weight *= 2.0
            weight = max(weight, 0.05)
            weights.append(weight)
        return weights
