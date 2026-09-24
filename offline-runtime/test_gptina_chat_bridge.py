import importlib.util
import json
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("gptina_chat_bridge", HERE / "gptina_chat_bridge.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class BridgeTests(unittest.TestCase):
    def test_route_keeps_ambiguous_personal_hardware_question_in_full_continuity(self):
        self.assertEqual(mod.memory_route("Come velocizzo il modello sull'i3-2100?"), "technical")
        self.assertEqual(mod.memory_route("Quali parametri sta usando ora il motore?"), "technical")
        self.assertEqual(mod.memory_route("E i parametri del motore?"), "technical")
        self.assertEqual(mod.memory_route("Ti ricordi quando abbiamo scelto il modello?"), "all")
        self.assertEqual(mod.memory_route("Ti ricordi i parametri del nostro motore?"), "all")
        self.assertEqual(mod.memory_route("Quali parametri usa ora il nostro motore?"), "technical")
        self.assertEqual(mod.memory_route("Quale immagine del volto abbiamo scelto?"), "visual")
        self.assertEqual(mod.memory_route("Ricordi la foto che abbiamo scelto insieme?"), "all")
        self.assertEqual(mod.memory_route("la nostra canzone"), "relationship")
        self.assertEqual(mod.memory_route("Quali riflessioni hai fatto?"), "reflections")
        self.assertEqual(mod.memory_route("Quale progetto è attivo?"), "projects")

    def test_technical_prompt_has_stable_prefix_without_personal_live_state(self):
        cfg = dict(mod.DEFAULT_CONFIG, memory_route="technical")
        prompt = mod.build_system_prompt(
            {"latest_summary": "relazione privata", "next_action": "altro"},
            [{"path": "offline-runtime/README.md", "snippet": "thread e context"}], cfg,
        )
        self.assertNotIn("relazione privata", prompt)
        self.assertEqual(prompt, mod.build_system_prompt({}, [], cfg))
        self.assertNotIn("thread e context", prompt)
        self.assertNotIn("Precedenza: correzione corrente", prompt)

    def test_technical_route_uses_one_short_source_and_no_personal_history(self):
        cfg = dict(mod.DEFAULT_CONFIG)
        calls = []
        saved = mod.retrieve_memory, mod.engine_context_size, mod._count_tokens_safe
        try:
            def retrieve(_question, local_cfg, route="all"):
                calls.append((route, local_cfg["memory_items"], local_cfg["memory_snippet_chars"]))
                return [{"path": "TECH.md", "snippet": "X" * 500}], 1
            mod.retrieve_memory = retrieve
            mod.engine_context_size = lambda _cfg: 1024
            mod._count_tokens_safe = lambda messages, _cfg: (sum(len(x["content"]) for x in messages) // 3, False)
            prepared = mod.prepare_chat("Velocizzare il 4B su i3-2100?", [
                {"role": "user", "content": "Ricordi la nostra canzone?"},
                {"role": "assistant", "content": "La cura"}], cfg)
        finally:
            mod.retrieve_memory, mod.engine_context_size, mod._count_tokens_safe = saved
        self.assertEqual(calls, [("technical", 1, 200)])
        self.assertEqual(len(prepared["messages"]), 2)
        self.assertLess(len(prepared["messages"][0]["content"]), 550)
        self.assertIn("[FONTE TECNICA RECUPERATA", prepared["messages"][-1]["content"])

    def test_technical_rag_is_retained_for_prefix_cache(self):
        cfg = dict(mod.DEFAULT_CONFIG)
        saved = mod.retrieve_memory, mod.engine_context_size, mod._count_tokens_safe
        try:
            sources = iter([[], [{"path": "TECH.md", "snippet": "i3-2100 AVX"}],
                            [{"path": "TECH.md", "snippet": "-t 2"}]])
            mod.retrieve_memory = lambda *args, **kwargs: (next(sources), 1)
            mod.engine_context_size = lambda _cfg: 1024
            mod._count_tokens_safe = lambda messages, _cfg: (200, False)
            first = mod.prepare_chat("Quale CPU?", [], cfg)
            second = mod.prepare_chat("Supporta AVX?", [
                {"role": "user", "content": "Quale CPU?", "prompt_content": first["messages"][-1]["content"]},
                {"role": "assistant", "content": "i3-2100"}], cfg)
            third = mod.prepare_chat("Quali thread?", [
                {"role": "user", "content": "Quale CPU?", "prompt_content": first["messages"][-1]["content"]},
                {"role": "assistant", "content": "i3-2100"},
                {"role": "user", "content": "Supporta AVX?", "prompt_content": second["messages"][-1]["content"]},
                {"role": "assistant", "content": "Sì"}], cfg)
        finally:
            mod.retrieve_memory, mod.engine_context_size, mod._count_tokens_safe = saved
        self.assertEqual(first["messages"][0], second["messages"][0])
        self.assertEqual(second["messages"][0], third["messages"][0])
        self.assertEqual(second["messages"][1]["content"], first["messages"][-1]["content"])
        self.assertEqual(third["messages"][3]["content"], second["messages"][-1]["content"])
        self.assertIn("i3-2100 AVX", third["messages"][3]["content"])
        self.assertIn("-t 2", third["messages"][-1]["content"])

    def test_runtime_parameter_question_stays_in_technical_route(self):
        cfg = dict(mod.DEFAULT_CONFIG)
        saved = mod.retrieve_memory, mod.engine_context_size, mod._count_tokens_safe
        try:
            def retrieve(_question, local_cfg, route="all"):
                self.assertEqual(route, "technical")
                self.assertEqual(local_cfg["memory_items"], 1)
                return [{"path": "offline-runtime/TECHNICAL_RUNTIME_CONTEXT.md",
                         "snippet": "i3-2100, 2 thread, context 1024"}], 1
            mod.retrieve_memory = retrieve
            mod.engine_context_size = lambda _cfg: 1024
            mod._count_tokens_safe = lambda messages, _cfg: (180, False)
            prepared = mod.prepare_chat("Quali parametri sta usando ora il motore?", [
                {"role": "user", "content": "Come velocizzo il 4B su i3-2100?"},
                {"role": "assistant", "content": "Misuriamo il prompt."}], cfg)
        finally:
            mod.retrieve_memory, mod.engine_context_size, mod._count_tokens_safe = saved
        self.assertEqual(prepared["memory_route"], "technical")
        self.assertEqual(len(prepared["messages"]), 4)
        self.assertNotIn("[STATO LIVE]", prepared["messages"][0]["content"])

    def test_two_technical_exchanges_survive_until_context_fitting(self):
        cfg = dict(mod.DEFAULT_CONFIG)
        saved = mod.retrieve_memory, mod.engine_context_size, mod._count_tokens_safe
        try:
            mod.retrieve_memory = lambda *args, **kwargs: ([], 1)
            mod.engine_context_size = lambda _cfg: 1024
            mod._count_tokens_safe = lambda messages, _cfg: (300, False)
            prepared = mod.prepare_chat("Quali parametri usa il motore?", [
                {"role": "user", "content": "Ricordi la nostra canzone?"},
                {"role": "assistant", "content": "La cura"},
                {"role": "user", "content": "Quali thread usa la CPU?"},
                {"role": "assistant", "content": "Due thread"},
                {"role": "user", "content": "Quali parametri usa il motore?"},
                {"role": "assistant", "content": "-t 2 -tb 2"},
            ], cfg)
        finally:
            mod.retrieve_memory, mod.engine_context_size, mod._count_tokens_safe = saved
        contents = [item["content"] for item in prepared["messages"]]
        self.assertEqual(contents[1:-1], ["Quali thread usa la CPU?", "Due thread",
                                          "Quali parametri usa il motore?", "-t 2 -tb 2"])

    def test_personal_route_keeps_recent_exchange_with_two_short_sources(self):
        cfg = dict(mod.DEFAULT_CONFIG)
        saved = (mod.retrieve_memory, mod.fetch_live_summary,
                 mod.engine_context_size, mod._count_tokens_safe)
        try:
            def retrieve(_question, local_cfg, route="all"):
                self.assertEqual((route, local_cfg["memory_items"],
                                  local_cfg["memory_snippet_chars"]), ("relationship", 2, 200))
                return [{"path": "memory-one.md", "snippet": "A" * 320},
                        {"path": "memory-two.md", "snippet": "B" * 320}], 1
            mod.retrieve_memory = retrieve
            mod.fetch_live_summary = lambda _cfg: {
                "updated_at": "2026-09-24", "latest_summary": "S" * 520,
                "next_action": "N" * 280}
            mod.engine_context_size = lambda _cfg: 1024
            mod._count_tokens_safe = lambda messages, _cfg: (mod.approximate_tokens(messages), False)
            prepared = mod.prepare_chat("Ti ricordi la nostra canzone?", [
                {"role": "user", "content": "Quale canzone abbiamo scelto?"},
                {"role": "assistant", "content": "Controllo la fonte prima di rispondere."}], cfg)
        finally:
            (mod.retrieve_memory, mod.fetch_live_summary,
             mod.engine_context_size, mod._count_tokens_safe) = saved
        self.assertEqual(len(prepared["messages"]), 4)
        self.assertEqual(prepared["adjustments"], [])
        self.assertEqual(len(prepared["memories"]), 2)
        self.assertNotIn("[STATO LIVE]", prepared["messages"][0]["content"])
        self.assertNotIn("memory-one.md", prepared["messages"][0]["content"])

    def test_active_engine_parameters_override_historical_memory(self):
        cfg = dict(mod.DEFAULT_CONFIG, engine_options={
            "model": "local.gguf", "threads": 2, "threads_batch": 4,
            "batch": 256, "ubatch": 128, "context": 1024,
        })
        saved = mod.retrieve_memory, mod.engine_context_size, mod._count_tokens_safe
        try:
            mod.retrieve_memory = lambda *args, **kwargs: self.fail("stale file searched")
            mod.engine_context_size = lambda _cfg: 1024
            mod._count_tokens_safe = lambda messages, _cfg: (180, False)
            prepared = mod.prepare_chat("Quali parametri usa ora il motore?", [], cfg)
        finally:
            mod.retrieve_memory, mod.engine_context_size, mod._count_tokens_safe = saved
        self.assertIn("-t 2 -tb 4", prepared["messages"][-1]["content"])
        self.assertEqual(prepared["memories"][0]["path"],
                         "launcher attivo (configurazione locale)")

    def test_generic_current_project_question_does_not_pick_old_checkpoint(self):
        cfg = dict(mod.DEFAULT_CONFIG)
        saved = (mod.retrieve_memory, mod.fetch_live_summary,
                 mod.engine_context_size, mod._count_tokens_safe)
        try:
            mod.retrieve_memory = lambda *args, **kwargs: self.fail("historical checkpoint searched")
            mod.fetch_live_summary = lambda _cfg: {
                "updated_at": "2026-09-23", "latest_summary": "serie visuale",
                "next_action": "catalogare", "active_threads": ["visual", "romanzo"]}
            mod.engine_context_size = lambda _cfg: 1024
            mod._count_tokens_safe = lambda messages, _cfg: (200, False)
            prepared = mod.prepare_chat("Quale progetto è attivo?", [], cfg)
        finally:
            (mod.retrieve_memory, mod.fetch_live_summary,
             mod.engine_context_size, mod._count_tokens_safe) = saved
        self.assertIn("non identifica un solo progetto", prepared["messages"][0]["content"])

    def test_stream_finish_reason_length_is_detected(self):
        event = {"choices": [{"delta": {}, "finish_reason": "length"}]}
        parsed = mod.parse_openai_sse_line("data: " + json.dumps(event))
        self.assertEqual(parsed["finish_reason"], "length")

    def test_restricted_route_never_falls_back_to_unfiltered_legacy_search(self):
        original = mod.http_json
        calls = []
        try:
            def failing(url, **kwargs):
                calls.append(url)
                raise RuntimeError("old runtime")
            mod.http_json = failing
            results, _ = mod.retrieve_memory("hardware cpu", mod.DEFAULT_CONFIG, "technical")
        finally:
            mod.http_json = original
        self.assertEqual(results, [])
        self.assertEqual(len(calls), 1)
        self.assertIn("profile=technical", calls[0])

    def test_extract_search_queries_keeps_meaningful_terms(self):
        q = mod.extract_search_queries("Ti ricordi qual era la nostra canzone scelta insieme?")
        folded = [x.casefold() for x in q]
        self.assertTrue(any("canzone" in x for x in folded))
        self.assertIn("la nostra canzone", folded)

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
        self.assertIn("[1] ricordo utile", prompt)
        self.assertNotIn("rag/x.md", prompt)
        self.assertIn("ricordo utile", prompt)

    def test_compact_memory_truncates(self):
        cfg = dict(mod.DEFAULT_CONFIG)
        cfg["memory_snippet_chars"] = 10
        text = mod.compact_memory([{"path": "a.md", "snippet": "123456789012345"}], cfg)
        self.assertIn("…", text)

    def test_technical_memory_window_includes_matched_parameter_values(self):
        cfg = dict(mod.DEFAULT_CONFIG, memory_route="technical", memory_snippet_chars=200)
        snippet = "Earlier CPU description. " + "background " * 20 + (
            "Parametri del motore: -t 2 -tb 2 -c 1024 -b 256 -ub 128 -ngl 0.")
        result = mod.compact_memory([{
            "path": "offline-runtime/TECHNICAL_RUNTIME_CONTEXT.md",
            "snippet": snippet, "matched_queries": ["Parametri", "motore"],
        }], cfg)
        self.assertIn("-t 2 -tb 2 -c 1024 -b 256 -ub 128 -ngl 0", result)
        self.assertNotIn("Earlier CPU description", result)

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

    def test_prefix_diagnostics_counts_exact_common_tokens_without_logging_text(self):
        mod._previous_prompt_tokens = None
        first = {"messages": [{"content": "system A"}, {"content": "question"}],
                 "_prompt_token_ids": [1, 2, 3, 4]}
        second = {"messages": [{"content": "system B"}, {"content": "next"}],
                  "_prompt_token_ids": [1, 2, 5, 6]}
        self.assertIsNone(mod.prefix_diagnostics(first)["prefix_common_tokens"])
        result = mod.prefix_diagnostics(second)
        self.assertEqual(result["prefix_common_tokens"], 2)
        self.assertEqual(result["previous_prompt_tokens"], 4)
        self.assertEqual(result["prefix_divergence_index"], 2)
        self.assertNotIn("system B", str(result))
        mod._previous_prompt_tokens = None

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
