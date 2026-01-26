from dataclasses import dataclass, field

from lib.rules_engine import AppliedEvent, CivilizationState, DelayedEffect, UniverseState, clamp
from rulesets.base import RulesetConfig
from rulesets.harsh_realism import HarshRealismRuleset


PHASE_MARKS = (
    "Phase_0_Proto",
    "Phase_1_Industrial",
    "Phase_2_EarlySpace",
    "Phase_3_Spacefaring",
)


@dataclass
class StarTrekLiteRuleset(HarshRealismRuleset):
    name: str = "star_trek_lite"
    description: str = "Star Trek lite (optimistic, phased progress)"
    config: RulesetConfig = field(
        default_factory=lambda: RulesetConfig(
            good_cycle_thresholds={
                "stability": 0.60,
                "cohesion": 0.60,
                "health": 0.60,
                "food_security": 0.60,
            },
            good_cycle_streak_for_phase=4,
            collapse_thresholds={
                "eco_pressure": 0.95,
                "stability": 0.10,
                "cohesion": 0.10,
                "inequality": 0.90,
                "food_security": 0.10,
                "consecutive_limit": 3,
            },
            extinction_thresholds={
                "stability_low": 0.05,
                "food_low": 0.05,
                "health_low": 0.05,
                "dual_low": 0.02,
                "consecutive_zero_stability": 3,
                "extreme_unrest_limit": 2,
            },
            max_event_rolls_base=1,
            additional_rolls_when_strained=1,
        )
    )

    def _get_phase(self, civ: CivilizationState) -> int:
        # Phase is tracked via marks to avoid schema changes.
        for idx, mark in enumerate(PHASE_MARKS):
            if mark in civ.marks:
                return idx
        self._set_phase(civ, 0)
        return 0

    def _set_phase(self, civ: CivilizationState, phase: int) -> None:
        for mark in PHASE_MARKS:
            if mark in civ.marks:
                civ.marks.remove(mark)
        civ.marks.append(PHASE_MARKS[phase])

    def minor_roll_count(self, civ: CivilizationState, universe: UniverseState, rng) -> int:
        base = self.config.max_event_rolls_base
        extra = self.config.additional_rolls_when_strained
        if not self.is_stressed(civ, universe):
            return rng.randint(0, max(0, base))
        return rng.randint(0, max(0, base + extra))

    def major_roll_count(self, civ: CivilizationState, universe: UniverseState, rng) -> int:
        if not self.is_in_crisis(civ, universe):
            return 0
        return 1 if rng.random() < 0.60 else 0

    def global_event_chance(self, universe: UniverseState) -> float:
        return 0.20 if "CosmicInstability" in universe.global_marks else 0.10

    def should_roll_global(self, universe: UniverseState, rng) -> bool:
        if rng.random() < self.global_event_chance(universe):
            return rng.randint(0, 1) == 1
        return False

    def hard_extinction(self, civ: CivilizationState, universe: UniverseState) -> bool:
        phase = self._get_phase(civ)
        good_thresholds = self.config.good_cycle_thresholds
        streak_limit = self.config.good_cycle_streak_for_phase
        good_cycle = (
            civ.stats.stability >= good_thresholds.get("stability", 0.60)
            and civ.stats.cohesion >= good_thresholds.get("cohesion", 0.60)
            and civ.stats.health >= good_thresholds.get("health", 0.60)
            and civ.stats.food_security >= good_thresholds.get("food_security", 0.60)
        )
        if good_cycle:
            civ.consecutive_good_cycles += 1
        else:
            civ.consecutive_good_cycles = 0
        if civ.consecutive_good_cycles >= streak_limit and phase < 3:
            self._set_phase(civ, phase + 1)
            civ.consecutive_good_cycles = 0
            civ.stats.stability = clamp(civ.stats.stability + 0.04)
            civ.stats.innovation = clamp(civ.stats.innovation + 0.05)
            civ.stats.health = clamp(civ.stats.health + 0.03)
            civ.stats.eco_pressure = clamp(civ.stats.eco_pressure + 0.04)
            civ.stats.inequality = clamp(civ.stats.inequality + 0.02)
            if "InstitutionalMomentum" not in civ.marks:
                civ.marks.append("InstitutionalMomentum")

        thresholds = self.config.extinction_thresholds
        stability_low = thresholds.get("stability_low", 0.05)
        health_low = thresholds.get("health_low", 0.05)
        food_low = thresholds.get("food_low", 0.05)
        dual_low = thresholds.get("dual_low", 0.02)
        zero_stability_limit = thresholds.get("consecutive_zero_stability", 3)
        extreme_unrest_limit = thresholds.get("extreme_unrest_limit", 2)
        if civ.stats.stability == 0.0:
            civ.consecutive_zero_stability += 1
        else:
            civ.consecutive_zero_stability = 0
        if civ.stats.cohesion == 0.0 and civ.stats.stability <= stability_low:
            civ.consecutive_extreme_unrest += 1
        else:
            civ.consecutive_extreme_unrest = 0

        if (
            (civ.stats.food_security == 0.0 and civ.stats.health <= health_low)
            or (civ.stats.health == 0.0 and civ.stats.food_security <= food_low)
            or (civ.stats.health <= dual_low and civ.stats.food_security <= dual_low)
            or (civ.consecutive_zero_stability >= zero_stability_limit)
            or (civ.consecutive_extreme_unrest >= extreme_unrest_limit)
        ):
            civ.alive = False
            civ.extinct = True
            civ.extinct_cycle = universe.cycle
            if "Extinct" not in civ.marks:
                civ.marks.append("Extinct")
            return True
        return False

    def collapse_trigger(self, civ: CivilizationState, universe: UniverseState) -> bool:
        thresholds = self.config.collapse_thresholds
        eco_extreme = (
            civ.stats.eco_pressure > thresholds.get("eco_pressure", 0.95)
            and civ.stats.stability < thresholds.get("stability", 0.10)
        )
        unrest_extreme = (
            civ.stats.cohesion < thresholds.get("cohesion", 0.10)
            and civ.stats.inequality > thresholds.get("inequality", 0.90)
        )
        famine_extreme = civ.stats.food_security < thresholds.get("food_security", 0.10)
        limit = thresholds.get("consecutive_limit", 3)

        civ.consecutive_extreme_eco = (
            civ.consecutive_extreme_eco + 1 if eco_extreme else 0
        )
        civ.consecutive_extreme_unrest = (
            civ.consecutive_extreme_unrest + 1 if unrest_extreme else 0
        )
        civ.consecutive_famine = civ.consecutive_famine + 1 if famine_extreme else 0

        if (
            civ.consecutive_extreme_eco < limit
            and civ.consecutive_extreme_unrest < limit
            and civ.consecutive_famine < limit
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
        if roll in (1, 12):
            civ.alive = False
            civ.extinct = True
            civ.extinct_cycle = universe.cycle
            add_marks.append("Extinct")
            outcome_kind = "extinction"
        elif roll == 2:
            deltas = {"cohesion": -0.25, "stability": -0.10, "food_security": -0.05}
            add_marks.append("Diaspora")
            delayed.append(
                DelayedEffect(
                    cycle_delay=2,
                    target=civ.id,
                    deltas={"inequality": 0.10},
                    add_marks=[],
                    remove_marks=[],
                )
            )
            outcome_kind = "mass_migration"
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

    def modify_weights(self, civ: CivilizationState, universe: UniverseState, eligible_events):
        weights = [event.weight_base for event in eligible_events]
        if civ is None:
            stable = False
            crisis = False
        else:
            stable = civ.stats.stability >= 0.60 and civ.stats.cohesion >= 0.60
            crisis = self.is_in_crisis(civ, universe)
        destructive = {"war", "plague", "famine", "disaster", "collapse", "shock"}
        constructive = {"reform", "infrastructure", "education", "health", "trade", "diplomacy"}
        for idx, event in enumerate(eligible_events):
            if stable and event.kind in destructive:
                weights[idx] *= 0.70
            if stable and event.kind in constructive:
                weights[idx] *= 1.30
            if crisis and event.kind in destructive:
                weights[idx] *= 1.15
        return weights
