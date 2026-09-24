"""Launcher profile validation without opening a Tk window or starting services."""

import importlib.machinery
import importlib.util
import pathlib
import json
import tempfile
import unittest


HERE = pathlib.Path(__file__).resolve().parent
loader = importlib.machinery.SourceFileLoader("gptina_offline_app", str(HERE / "gptina_offline_app.pyw"))
spec = importlib.util.spec_from_loader(loader.name, loader)
app = importlib.util.module_from_spec(spec)
loader.exec_module(app)


class LauncherProfileTests(unittest.TestCase):
    def test_native_chat_uses_bridge_stream_and_preserves_history(self):
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def __iter__(self):
                return iter([
                    b'{"type":"meta","memory_route":"relationship"}\n',
                    b'{"type":"token","text":"Ciao"}\n',
                    b'{"type":"done","finish_reason":"stop"}\n',
                ])

        original = app.urlopen
        try:
            def fake_open(req, timeout):
                captured["url"] = req.full_url
                captured["payload"] = json.loads(req.data.decode("utf-8"))
                captured["timeout"] = timeout
                return Response()
            app.urlopen = fake_open
            events = list(app.chat_stream_events(
                "Come stai?", [{"role": "user", "content": "Ciao"}]))
        finally:
            app.urlopen = original

        self.assertEqual(captured["url"], "http://127.0.0.1:8766/chat/stream")
        self.assertEqual(captured["payload"]["history"][0]["content"], "Ciao")
        self.assertEqual([event["type"] for event in events], ["meta", "token", "done"])
        self.assertEqual(events[1]["text"], "Ciao")

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

    def test_verified_profile_is_published_for_current_parameter_questions(self):
        options = app.validated_engine_options(dict(app.DEFAULTS, threads_batch="4"))
        original = app.RUNTIME_CONFIG
        try:
            with tempfile.TemporaryDirectory() as directory:
                app.RUNTIME_CONFIG = pathlib.Path(directory) / "runtime.json"
                app.write_runtime_cfg(options["context"], options["predict"],
                                      options, pathlib.Path("model.gguf"))
                active = json.loads(app.RUNTIME_CONFIG.read_text())["engine_options"]
        finally:
            app.RUNTIME_CONFIG = original
        self.assertEqual(active["threads_batch"], 4)
        self.assertEqual(active["threads"], 2)
        self.assertEqual(active["model"], "model.gguf")

    def test_semantic_trial_flag_is_written_to_runtime_config(self):
        original = app.RUNTIME_CONFIG
        try:
            with tempfile.TemporaryDirectory() as directory:
                app.RUNTIME_CONFIG = pathlib.Path(directory) / "runtime.json"
                app.write_runtime_cfg(1024, 160, semantic_retrieval=True)
                payload = json.loads(app.RUNTIME_CONFIG.read_text())
        finally:
            app.RUNTIME_CONFIG = original
        self.assertIs(payload["semantic_retrieval"], True)


if __name__ == "__main__":
    unittest.main()
