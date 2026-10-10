"""Offline CKR4 benchmark guards: no credentials or network needed."""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[2] / "08_Tooling/ckr4-benchmark-harness/harness.py"
spec = importlib.util.spec_from_file_location("ckr4_harness", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HarnessTests(unittest.TestCase):
    def test_frozen_tasks(self):
        self.assertEqual(list(module.frozen_tasks()), [f"T{i}" for i in range(1, 11)])

    def test_bounded_selection(self):
        tasks = module.frozen_tasks()
        self.assertEqual(module.parse_tasks("T1,T2", tasks), ["T1", "T2"])
        for bad in ("T1,T1", "T11", "T1,T2,T3,T4", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                module.parse_tasks(bad, tasks)

    def test_no_not_needed_retrieval(self):
        self.assertFalse({"T2", "T5"} & module.TASKS_REQUIRING_SPECIALIZED)

    def test_null_not_zero(self):
        self.assertIsNone(module.reduction(None, 1))
        self.assertIsNone(module.reduction(0, 0))
        self.assertEqual(module.reduction(4, 6), -0.5)

    def test_prompt_preserves_authority(self):
        text = module.prompt("T1", "design", "C", "github", [])
        self.assertIn("Notion is non-authoritative", text)
        self.assertIn("github", text)

    def test_projection_does_not_copy_content(self):
        rows = [{"id": "abc", "secret": "never expose", "properties": {"Student": "private"}}]
        self.assertNotIn("never expose", str(module.safe_notion_projection(rows)))


if __name__ == "__main__":
    unittest.main()
