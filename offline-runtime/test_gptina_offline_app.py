"""Launcher profile validation without opening a Tk window or starting services."""

import importlib.machinery
import importlib.util
import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve().parent
loader = importlib.machinery.SourceFileLoader("gptina_offline_app", str(HERE / "gptina_offline_app.pyw"))
spec = importlib.util.spec_from_loader(loader.name, loader)
app = importlib.util.module_from_spec(spec)
loader.exec_module(app)


class LauncherProfileTests(unittest.TestCase):
    def test_legacy_local_config_keeps_safe_defaults(self):
        values = dict(app.DEFAULTS, threads="2", context="1024", predict="160")
        options = app.validated_engine_options(values)
        command = app.engine_command(pathlib.Path("model.gguf"), options)
        self.assertEqual(command[command.index("-tb") + 1], "2")
        self.assertEqual(command[command.index("-b") + 1], "256")
        self.assertEqual(command[command.index("-ub") + 1], "128")
        self.assertEqual(command[command.index("-np") + 1], "1")
        self.assertEqual(command[command.index("-ngl") + 1], "0")

    def test_profile_changes_prompt_threads_and_batch_independently(self):
        options = app.validated_engine_options(dict(app.DEFAULTS, threads_batch="4", batch="128", ubatch="64"))
        command = app.engine_command(pathlib.Path("model.gguf"), options)
        for flag, expected in (("-t", "2"), ("-tb", "4"), ("-b", "128"), ("-ub", "64")):
            self.assertEqual(command[command.index(flag) + 1], expected)

    def test_invalid_micro_batch_is_rejected_before_launch(self):
        with self.assertRaisesRegex(ValueError, "Micro-batch non può superare Batch"):
            app.validated_engine_options(dict(app.DEFAULTS, batch="64", ubatch="128"))


if __name__ == "__main__":
    unittest.main()
