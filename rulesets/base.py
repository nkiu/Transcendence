from dataclasses import dataclass
from typing import List

from lib.rules_engine import AppliedEvent, CivilizationState, UniverseState


@dataclass
class BaseRuleset:
    name: str = "base"
    description: str = "Base ruleset interface."

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
