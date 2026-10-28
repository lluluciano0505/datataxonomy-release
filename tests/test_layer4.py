import unittest
from pathlib import Path

from core.layer4 import layer4_trust


class Layer4ReviewPriorityTests(unittest.TestCase):
    def setUp(self):
        self.file_path = Path("brief.txt")
        self.meta = {
            "filename": "brief.txt",
            "extraction_coverage": "text",
            "extraction_method": "text",
            "content_sample": "A clear project brief with readable text.",
            "year_confidence": "unknown",
            "drawing_mode": "",
        }
        self.project = {"year_range": [2020, 2030]}

    def layer2(self, **overrides):
        values = {
            "domain": "Architecture & Buildings",
            "lifecycle": "Unknown",
            "governance": "Internal",
            "certainty": "High",
            "certainty_reason": "clear classification signals",
            "asset_type": "Document",
            "information_type": "Narrative / Textual",
            "confidentiality": "Not Confidential",
            "confidentiality_reason": "",
            "llm": "ok",
        }
        values.update(overrides)
        return values

    def test_unknown_lifecycle_alone_does_not_require_review(self):
        result = layer4_trust(
            self.file_path, self.meta, self.layer2(), self.project
        )

        self.assertEqual(result["review_priority"], "Low")
        self.assertEqual(result["action"], "Auto-process")
        self.assertNotIn("unknown lifecycle", result["review_reasons"])

    def test_unknown_domain_still_requires_review(self):
        result = layer4_trust(
            self.file_path,
            self.meta,
            self.layer2(domain="Unknown"),
            self.project,
        )

        self.assertEqual(result["review_priority"], "High")
        self.assertIn("Manual classification", result["action"])


if __name__ == "__main__":
    unittest.main()
