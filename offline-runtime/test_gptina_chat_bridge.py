import importlib.util
import json
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

    def test_parse_stream_token(self):
        payload = {
            "choices": [{"delta": {"content": "ciao"}, "finish_reason": None}],
            "timings": {"predicted_per_second": 1.5},
        }
        evt = mod.parse_openai_sse_line("data: " + json.dumps(payload))
        self.assertEqual(evt["content"], "ciao")
        self.assertEqual(evt["timings"]["predicted_per_second"], 1.5)

    def test_parse_stream_done(self):
        self.assertEqual(mod.parse_openai_sse_line("data: [DONE]"), {"type": "done"})

    def test_generation_payload_disables_thinking(self):
        cfg = dict(mod.DEFAULT_CONFIG)
        payload = mod.generation_payload([{"role": "user", "content": "ciao"}], cfg, stream=True)
        self.assertTrue(payload["stream"])
        self.assertTrue(payload["cache_prompt"])
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertFalse(payload["chat_template_kwargs"]["enable_thinking"])

    def test_fit_context_drops_old_history_before_current_turn(self):
        cfg = dict(mod.DEFAULT_CONFIG)
        cfg["max_tokens"] = 80
        cfg["history_messages"] = 4
        cfg["history_chars"] = 2000

        history = [
            {"role": "user", "content": "vecchio " * 60},
            {"role": "assistant", "content": "risposta vecchia " * 60},
            {"role": "user", "content": "recente"},
            {"role": "assistant", "content": "risposta recente"},
        ]
        live = {"updated_at": "x", "latest_summary": "stato", "next_action": "next"}
        memories = [{"path": "m.md", "snippet": "memoria"}]

        original = mod._count_tokens_safe
        try:
            mod._count_tokens_safe = lambda messages, _cfg: (
                sum(len(x["content"]) for x in messages) // 4 + 20,
                False,
            )
            messages, _, meta = mod.fit_messages_to_context(
                "domanda corrente",
                history,
                live,
                memories,
                cfg,
                n_ctx=400,
            )
        finally:
            mod._count_tokens_safe = original

        self.assertEqual(messages[-1]["content"], "domanda corrente")
        self.assertIn("history_oldest_pair_removed", meta["adjustments"])
        self.assertLessEqual(meta["prompt_tokens"], meta["input_budget"])


if __name__ == "__main__":
    unittest.main()
