from rulesets.harsh_realism import HarshRealismRuleset

try:
    from rulesets.star_trek_lite import StarTrekLiteRuleset
except Exception:  # pragma: no cover - optional ruleset
    StarTrekLiteRuleset = None


def list_available_rulesets() -> list[tuple[str, str]]:
    rulesets = [
        ("harsh_realism", "Harsh realism (baseline)"),
        ("star_trek_lite", "Star Trek lite (optimistic, phased progress)"),
    ]
    return rulesets


def create_ruleset(name: str):
    if name == "star_trek_lite" and StarTrekLiteRuleset is not None:
        return StarTrekLiteRuleset()
    return HarshRealismRuleset()
