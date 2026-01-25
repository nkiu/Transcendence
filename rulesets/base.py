from dataclasses import dataclass, field
from typing import Dict, List

from lib.rules_engine import AppliedEvent, CivilizationState, UniverseState


@dataclass
class RulesetConfig:
    stress_thresholds: Dict[str, float] = field(
        default_factory=lambda: {
            "eco_pressure": 0.55,
            "stability": 0.55,
            "food_security": 0.55,
        }
    )
    crisis_thresholds: Dict[str, float] = field(
        default_factory=lambda: {
            "eco_pressure": 0.75,
            "stability": 0.35,
            "cohesion": 0.35,
            "food_security": 0.35,
        }
    )
    collapse_thresholds: Dict[str, float] = field(
        default_factory=lambda: {
            "eco_pressure": 0.95,
            "stability": 0.10,
            "cohesion": 0.10,
            "inequality": 0.90,
            "food_security": 0.10,
            "consecutive_limit": 2,
        }
    )
    extinction_thresholds: Dict[str, float] = field(
        default_factory=lambda: {
            "stability_low": 0.05,
            "food_low": 0.10,
            "health_low": 0.05,
            "consecutive_zero_stability": 2,
        }
    )
    good_cycle_thresholds: Dict[str, float] = field(
        default_factory=lambda: {
            "stability": 0.60,
            "cohesion": 0.60,
            "health": 0.60,
            "food_security": 0.60,
        }
    )
    good_cycle_streak_for_phase: int = 4
    max_event_rolls_base: int = 2
    additional_rolls_when_strained: int = 0
    additional_rolls_when_crisis: int = 1


@dataclass
class BaseRuleset:
    name: str = "base"
    description: str = "Base ruleset interface."
    config: RulesetConfig = field(default_factory=RulesetConfig)

    def is_stressed(self, civ: CivilizationState, universe: UniverseState) -> bool:
        return False

    def is_in_crisis(self, civ: CivilizationState, universe: UniverseState) -> bool:
        return False

    def minor_roll_count(
        self, civ: CivilizationState, universe: UniverseState, rng
    ) -> int:
        return 0

    def major_roll_count(
        self, civ: CivilizationState, universe: UniverseState, rng
    ) -> int:
        return 0

    def global_event_chance(self, universe: UniverseState) -> float:
        return 0.0

    def should_roll_global(self, universe: UniverseState, rng) -> bool:
        return False

    def hard_extinction(self, civ: CivilizationState, universe: UniverseState) -> bool:
        return False

    def collapse_trigger(self, civ: CivilizationState, universe: UniverseState) -> bool:
        return False

    def collapse_outcome(
        self, civ: CivilizationState, universe: UniverseState, rng
    ) -> AppliedEvent:
        raise NotImplementedError

    def modify_weights(
        self,
        civ: CivilizationState,
        universe: UniverseState,
        eligible_events: List,
    ) -> List[float]:
        return [event.weight_base for event in eligible_events]
