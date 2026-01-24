from rulesets.harsh_realism import HarshRealismRuleset

try:
    from rulesets.star_trek_lite import StarTrekLiteRuleset
except Exception:  # pragma: no cover - optional ruleset
    StarTrekLiteRuleset = None
try:
    from rulesets.cheat_utopia import CheatUtopiaRuleset
except Exception:  # pragma: no cover - optional ruleset
    CheatUtopiaRuleset = None


def list_available_rulesets() -> list[tuple[str, str]]:
    rulesets = [
        ("harsh_realism", "Harsh realism (baseline)"),
        ("star_trek_lite", "Star Trek lite (optimistic, phased progress)"),
        ("cheat_utopia", "Utopian cheat mode (strong stabilizer, near-guaranteed ascension)"),
    ]
    return rulesets


def create_ruleset(name: str):
    if name == "star_trek_lite" and StarTrekLiteRuleset is not None:
        return StarTrekLiteRuleset()
    if name == "cheat_utopia" and CheatUtopiaRuleset is not None:
        return CheatUtopiaRuleset()
    return HarshRealismRuleset()
