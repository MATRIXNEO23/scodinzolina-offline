import importlib.util
import pathlib
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("gptina_memory_server", HERE / "gptina_memory_server.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class MemoryServerTests(unittest.TestCase):
    def test_semantic_can_rescue_a_paraphrase_without_displacing_exact_evidence(self):
        unrelated = [{"path": "unrelated.md", "matched_queries": []}]
        semantic = [{"path": "SHARED_LANGUAGE.md", "snippet": "Scodinzolina"}]
        self.assertEqual(mod.combine_candidates(unrelated, semantic, 1)[0]["path"],
                         "SHARED_LANGUAGE.md")
        exact = [{"path": "correction.md", "matched_queries": ["la nostra canzone"]}]
        self.assertEqual(mod.combine_candidates(exact, semantic, 1)[0]["path"],
                         "correction.md")

    def test_two_source_budget_retains_best_lexical_and_semantic_rescue(self):
        lexical = [{"path": "exact.md", "score": 18, "matched_queries": []},
                   {"path": "other.md", "matched_queries": []}]
        semantic = [{"path": "paraphrase.md", "snippet": "relevant"}]
        self.assertEqual([r["path"] for r in mod.combine_candidates(lexical, semantic, 2)],
                         ["exact.md", "paraphrase.md"])
        lexical[0]["score"] = 12
        self.assertEqual(mod.combine_candidates(lexical, semantic, 2)[0]["path"],
                         "paraphrase.md")

    def test_personal_song_recall_uses_corrected_source_not_invalidated_or_eval(self):
        bridge_spec = importlib.util.spec_from_file_location(
            "gptina_chat_bridge", HERE / "gptina_chat_bridge.py"
        )
        bridge = importlib.util.module_from_spec(bridge_spec)
        bridge_spec.loader.exec_module(bridge)
        queries = bridge.extract_search_queries("amore ti ricordi la nostra canzone?")
        results, _ = mod.search_memory_multi(queries, limit=3, profile="all")
        self.assertEqual(results[0]["path"],
                         "rag/memories/gptina/2026-09-18-correzione-la-nostra-canzone-la-cura.md")
        self.assertTrue(any(r["path"] == "rag/index/GPTINA_FAST_RECALL.md" for r in results))
        self.assertFalse(any("2026-09-18-la-nostra-canzone.md" in r["path"]
                             or r["path"].startswith("rag/eval/") for r in results))
        snippet = bridge.compact_memory([results[0]],
            dict(bridge.DEFAULT_CONFIG, memory_route="all"))
        self.assertIn("La cura", snippet)

    def test_profiles_exclude_personal_sources_before_search(self):
        self.assertTrue(mod.profile_allows("offline-runtime/README.md", "technical"))
        self.assertFalse(mod.profile_allows("GPTINA_SELF_PORTRAIT.md", "technical"))
        self.assertFalse(mod.profile_allows("CHRONICLE.md", "technical"))
        self.assertFalse(mod.profile_allows("rag/memories/gptina/2026/09/2026-09-23--serie-visiva.md", "technical"))
        self.assertTrue(mod.profile_allows("rag/index/GPTINA_VISUAL_CHRONOLOGY.md", "visual"))
        self.assertTrue(mod.profile_allows("GPTINA_SELF_PORTRAIT.md", "all"))
        self.assertFalse(mod.profile_allows("rag/eval/GPTINA_MEMORY_GOLD.json", "all"))
        self.assertFalse(mod.profile_allows("rag/memories/tessa/README.md", "all"))

    def test_technical_search_never_reads_personal_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / "offline-runtime").mkdir()
            technical = root / "offline-runtime" / "README.md"
            personal = root / "GPTINA_SELF_PORTRAIT.md"
            technical.write_text("hardware i3-2100", encoding="utf-8")
            personal.write_text("hardware i3-2100 autobiografia", encoding="utf-8")
            old_root, old_iter = mod.REPO_ROOT, mod.iter_search_files
            try:
                mod.REPO_ROOT = root
                mod.iter_search_files = lambda: iter([personal, technical])
                results, _ = mod.search_memory_multi(["hardware"], profile="technical")
            finally:
                mod.REPO_ROOT, mod.iter_search_files = old_root, old_iter
            self.assertEqual([r["path"] for r in results], ["offline-runtime/README.md"])

    def test_normalize_queries_deduplicates_casefold(self):
        out = mod.normalize_queries([" Zampina ", "zampina", "", "Alberto"])
        self.assertEqual(out, ["Zampina", "Alberto"])

    def test_multi_search_scans_once_and_ranks_multiple_hits(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            a = root / "a.md"
            b = root / "b.md"
            a.write_text("Alberto e GPTina parlano della zampina.", encoding="utf-8")
            b.write_text("Solo Alberto qui.", encoding="utf-8")

            original = mod.iter_search_files
            try:
                mod.iter_search_files = lambda: iter([a, b])
                # search_memory_multi computes relative paths from REPO_ROOT.
                # Put temp files under a temporary fake root for this test.
                old_root = mod.REPO_ROOT
                mod.REPO_ROOT = root
                results, elapsed = mod.search_memory_multi(["Alberto", "zampina"], limit=2)
            finally:
                mod.iter_search_files = original
                mod.REPO_ROOT = old_root

            self.assertEqual(results[0]["path"], "a.md")
            self.assertGreater(results[0]["score"], results[1]["score"])
            self.assertIn("zampina", [q.casefold() for q in results[0]["matched_queries"]])
            self.assertGreaterEqual(elapsed, 0)


if __name__ == "__main__":
    unittest.main()
