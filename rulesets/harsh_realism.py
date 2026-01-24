from dataclasses import dataclass

from lib.rules_engine import AppliedEvent, DelayedEffect
from lib.rules_engine import CivilizationState, UniverseState
from rulesets.base import BaseRuleset


@dataclass
class HarshRealismRuleset(BaseRuleset):
    name: str = "harsh_realism"
    description: str = "Default DND-like ruleset (current behavior)."

    def is_stressed(self, civ: CivilizationState, universe: UniverseState) -> bool:
        return (
            civ.stats.eco_pressure > 0.55
            or civ.stats.stability < 0.55
            or civ.stats.food_security < 0.55
        )

    def is_in_crisis(self, civ: CivilizationState, universe: UniverseState) -> bool:
        return (
            civ.stats.eco_pressure > 0.75
            or civ.stats.stability < 0.35
            or civ.stats.cohesion < 0.35
            or civ.stats.food_security < 0.35
        )

    def minor_roll_count(self, civ: CivilizationState, universe: UniverseState, rng) -> int:
        return rng.randint(0, 2)

    def major_roll_count(self, civ: CivilizationState, universe: UniverseState, rng) -> int:
        return rng.randint(0, 1)

    def global_event_chance(self, universe: UniverseState) -> float:
        return 0.30 if "CosmicInstability" in universe.global_marks else 0.15

    def should_roll_global(self, universe: UniverseState, rng) -> bool:
        if rng.random() < self.global_event_chance(universe):
            return rng.randint(0, 1) == 1
        return False

    def hard_extinction(self, civ: CivilizationState, universe: UniverseState) -> bool:
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

    def collapse_trigger(self, civ: CivilizationState, universe: UniverseState) -> bool:
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
            return False

        civ.consecutive_extreme_eco = 0
        civ.consecutive_extreme_unrest = 0
        civ.consecutive_famine = 0
        return True

    def collapse_outcome(
        self, civ: CivilizationState, universe: UniverseState, rng
    ) -> AppliedEvent:
        roll = rng.randint(1, 12)
        deltas = {}
        add_marks = []
        remove_marks = []
        delayed = []
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
