import json
import pathlib
import unittest

import gptina_chat_bridge as bridge
import gptina_offline_index as index

ROOT = pathlib.Path(__file__).resolve().parents[1]


class OfflineIndexTests(unittest.TestCase):
    def test_supersession_and_owner_boundary(self):
        source = ROOT / "rag/memories/gptina/2026/09/2026-09-22--correzione-set-riferimento-volto-12-13-19-40.md"
        memory_id, status, supersedes = index.frontmatter(source.read_text(encoding="utf-8"))
        self.assertEqual(status, "current")
        self.assertEqual(memory_id, "gptina-2026-09-22-correzione-set-riferimento-volto-12-13-19-40")
        self.assertEqual(supersedes, ["gptina-2026-09-18-correzione-set-riferimento-volto-12-13-29-42"])
        obj = index.OfflineIndex()
        sources = {row[0] for row in obj.db.execute("SELECT DISTINCT source FROM chunks")}
        self.assertNotIn("rag/memories/gptina/2026/09/2026-09-18--correzione-set-riferimento-volto-12-13-29-42.md", sources)
        self.assertFalse(any(path.startswith("rag/memories/tessa/") for path in sources))

    def test_canonical_retrieval_gold_sources_remain_reachable(self):
        cases = json.loads((ROOT / "rag/eval/GPTINA_MEMORY_GOLD.json").read_text(encoding="utf-8"))
        for case in cases:
            if case["mode"] != "search":
                continue
            with self.subTest(case=case["id"]):
                route = bridge.memory_route(case["query"])
                results, _, _ = index.search(
                    bridge.extract_search_queries(case["query"]),
                    max(8, case["top_k"]), route if route != "technical" else "all",
                )
                paths = [item["path"] for item in results]
                self.assertTrue(any(path in paths for path in case["expected_any"]), paths)
                self.assertFalse(any(path in paths for path in case.get("forbidden", [])), paths)

    def test_visual_correction_without_visual_word_in_filename(self):
        query = "correzione numerazione immagini 48 49 50 originali"
        result, _, _ = index.search(bridge.extract_search_queries(query), 2, "visual")
        self.assertEqual(result[0]["path"],
            "rag/memories/gptina/2026/09/2026-09-21--correzione-numerazione-48-49-50-originali.md")
        excerpt = bridge.compact_memory(result, dict(bridge.DEFAULT_CONFIG,
            memory_snippet_chars=300))
        self.assertIn("Trieste non è la 48 ma la **50**", excerpt)
        self.assertNotIn("schema_version", excerpt)

    def test_song_question_and_visual_number_fit_short_prompts(self):
        song, _, _ = index.search(
            bridge.extract_search_queries("amore ti ricordi la nostra canzone?"), 2, "all")
        self.assertEqual(song[0]["path"],
            "rag/memories/gptina/2026-09-18-correzione-la-nostra-canzone-la-cura.md")
        self.assertEqual(song[1]["path"], "rag/index/GPTINA_FAST_RECALL.md")
        compact = bridge.compact_memory(song, dict(bridge.DEFAULT_CONFIG,
            memory_route="all", memory_snippet_chars=240))
        self.assertIn("La cura", compact)

        visual, _, _ = index.search(
            bridge.extract_search_queries("immagine 32 stesso filo"), 2, "visual")
        self.assertEqual(visual[0]["path"], "rag/media-links/2026/09/32.json")
        self.assertEqual(visual[1]["path"], "rag/index/GPTINA_VISUAL_CHRONOLOGY.md")

    def test_visual_number_expressed_as_numero_finds_the_same_record(self):
        results, _, _ = index.search(
            bridge.extract_search_queries("Quale ritratto avevamo collegato al numero 44?"),
            2, "visual")
        self.assertEqual(results[0]["path"], "rag/media-links/2026/09/44.json")


if __name__ == "__main__":
    unittest.main()
