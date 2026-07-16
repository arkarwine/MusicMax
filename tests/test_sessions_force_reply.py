import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class SessionForceReplyTests(unittest.TestCase):
    def test_private_add_prompts_use_non_selective_force_reply(self):
        source = (ROOT / "anony/plugins/sessions.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "ForceReply"
        ]

        self.assertEqual(len(calls), 2)
        for call in calls:
            keywords = {keyword.arg for keyword in call.keywords}
            self.assertIn("placeholder", keywords)
            self.assertNotIn("selective", keywords)


if __name__ == "__main__":
    unittest.main()
