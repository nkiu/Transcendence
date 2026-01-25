import unittest

from lib.narrative_parser import parse_sections


class NarrativeParserTests(unittest.TestCase):
    def test_missing_headers_defaults_to_log(self) -> None:
        text = "People are hungry. The sky is red."
        sections = parse_sections(text, ["LOG", "GOD"])
        self.assertEqual(sections["LOG"], text)
        self.assertEqual(sections["GOD"], "")

    def test_inline_headers(self) -> None:
        text = "LOG: We march. GOD: The omens fade."
        sections = parse_sections(text, ["LOG", "GOD"])
        self.assertEqual(sections["LOG"], "We march.")
        self.assertEqual(sections["GOD"], "The omens fade.")

    def test_multiline_headers(self) -> None:
        text = "TITLE:\nCycle 3\nLOG:\nA storm.\nANALYSIS:\nRisk grows."
        sections = parse_sections(text, ["TITLE", "LOG", "ANALYSIS", "GOD"])
        self.assertEqual(sections["TITLE"], "Cycle 3")
        self.assertEqual(sections["LOG"], "A storm.")
        self.assertEqual(sections["ANALYSIS"], "Risk grows.")
        self.assertEqual(sections["GOD"], "")

    def test_ignores_unknown_headers(self) -> None:
        text = "META:\nIgnore\nLOG:\nWe survive."
        sections = parse_sections(text, ["LOG", "GOD"])
        self.assertEqual(sections["LOG"], "We survive.")
        self.assertEqual(sections["GOD"], "")

    def test_shuffled_sections(self) -> None:
        text = "GOD:\nThe omens fade.\nLOG:\nWe march."
        sections = parse_sections(text, ["LOG", "GOD"])
        self.assertEqual(sections["LOG"], "We march.")
        self.assertEqual(sections["GOD"], "The omens fade.")

    def test_extra_text_before_after(self) -> None:
        text = "Prelude line.\nLOG:\nWe march.\nGOD:\nThe omens fade.\nPostlude."
        sections = parse_sections(text, ["LOG", "GOD"])
        self.assertEqual(sections["LOG"], "We march.")
        self.assertEqual(sections["GOD"], "The omens fade.")


if __name__ == "__main__":
    unittest.main()
