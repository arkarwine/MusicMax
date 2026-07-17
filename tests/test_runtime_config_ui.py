import ast
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]

CONFIG_SPEC = importlib.util.spec_from_file_location(
    "runtime_config_model_under_test",
    ROOT / "config.py",
)
config_module = importlib.util.module_from_spec(CONFIG_SPEC)
CONFIG_SPEC.loader.exec_module(config_module)


def assignment_dict_keys(tree: ast.AST, name: str) -> set[str]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            continue
        if isinstance(node.value, ast.Dict):
            return {
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant)
                and isinstance(key.value, str)
            }
    raise AssertionError(f"Missing dictionary assignment: {name}")


class RuntimeConfigUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / "anony/plugins/runtime_config.py"
        cls.source = cls.path.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_every_runtime_field_has_ui_metadata(self):
        setting_keys = assignment_dict_keys(self.tree, "SETTINGS")
        self.assertEqual(
            setting_keys,
            set(config_module.Config.RUNTIME_FIELDS),
        )

    def test_component_has_navigation_tables_and_force_reply_editing(self):
        self.assertIn("<table bordered striped>", self.source)
        self.assertIn('runtime_config("category", key)', self.source)
        self.assertIn('runtime_config("view", key)', self.source)
        self.assertIn('runtime_config("edit", key)', self.source)
        self.assertIn('runtime_config("template", key)', self.source)

        force_replies = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "ForceReply"
        ]
        self.assertEqual(len(force_replies), 1)

    def test_play_templates_can_be_viewed_without_rendering_markdown(self):
        self.assertIn('text="📄 View template"', self.source)
        self.assertIn('f"<pre>{encoded}</pre>"', self.source)
        self.assertIn('lang.languages[lang_code]["play_message_template"]', self.source)
        self.assertIn('source = "Environment"', self.source)

    def test_template_editor_recovers_markdown_from_telegram_entities(self):
        self.assertIn("markdown = text.markdown", self.source)
        self.assertIn("_setting_input_text(message, key)", self.source)
        self.assertIn("_setting_input_text(message, pending.key)", self.source)

    def test_config_reply_does_not_share_the_session_reply_group(self):
        session_source = (
            ROOT / "anony/plugins/sessions.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "filters.private & filters.reply & app.sudoers, group=3",
            self.source,
        )
        self.assertIn(
            "filters.private & filters.text & app.sudoers, group=2",
            session_source,
        )

    def test_config_edit_does_not_claim_the_session_cancel_command(self):
        self.assertNotIn('filters.command(["cancel"])', self.source)
        self.assertIn('message.text.strip().lower() == "cancel"', self.source)

    def test_destructive_reset_requires_confirmation(self):
        self.assertIn(
            'runtime_config("confirm_all", "all")',
            self.source,
        )
        self.assertIn(
            'runtime_config("reset_all", "all")',
            self.source,
        )

    def test_database_exposes_atomic_reset_all(self):
        database_tree = ast.parse(
            (ROOT / "anony/core/database.py").read_text(encoding="utf-8")
        )
        names = {
            node.name
            for node in ast.walk(database_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("reset_all_runtime_config", names)


if __name__ == "__main__":
    unittest.main()
