import importlib.util
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("gptina_chat_bridge", HERE / "gptina_chat_bridge.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class BridgeTests(unittest.TestCase):
    def test_extract_search_queries_keeps_meaningful_terms(self):
        q = mod.extract_search_queries("Ti ricordi qual era la nostra canzone scelta insieme?")
        folded = [x.casefold() for x in q]
        self.assertTrue(any("canzone" in x for x in folded))

    def test_trim_history_limits_messages_and_chars(self):
        cfg = dict(mod.DEFAULT_CONFIG)
        cfg["history_messages"] = 2
        cfg["history_chars"] = 20
        history = [
            {"role": "user", "content": "uno"},
            {"role": "assistant", "content": "due"},
            {"role": "user", "content": "x" * 15},
            {"role": "assistant", "content": "y" * 15},
        ]
        out = mod.trim_history(history, cfg)
        self.assertLessEqual(len(out), 2)
        self.assertLessEqual(sum(len(x["content"]) for x in out), 20)

    def test_build_system_prompt_contains_live_and_sources(self):
        cfg = dict(mod.DEFAULT_CONFIG)
        live = {"updated_at": "2026-09-23", "latest_summary": "stato", "next_action": "next"}
        mem = [{"path": "rag/x.md", "snippet": "ricordo utile"}]
        prompt = mod.build_system_prompt(live, mem, cfg)
        self.assertIn("[STATO LIVE]", prompt)
        self.assertIn("rag/x.md", prompt)
        self.assertIn("ricordo utile", prompt)

    def test_compact_memory_truncates(self):
        cfg = dict(mod.DEFAULT_CONFIG)
        cfg["memory_snippet_chars"] = 10
        text = mod.compact_memory([{"path": "a.md", "snippet": "123456789012345"}], cfg)
        self.assertIn("…", text)


if __name__ == "__main__":
    unittest.main()
