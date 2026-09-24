import json
import pathlib
import unittest

import gptina_chat_bridge as bridge
import gptina_offline_index as index

ROOT = pathlib.Path(__file__).resolve().parents[1]


class OfflineIndexTests(unittest.TestCase):
    def test_canonical_retrieval_gold_sources_remain_reachable(self):
        cases = json.loads((ROOT / "rag/eval/GPTINA_MEMORY_GOLD.json").read_text(encoding="utf-8"))
        for case in cases:
            if case["mode"] != "search":
                continue
            with self.subTest(case=case["id"]):
                results, _, _ = index.search(
                    bridge.extract_search_queries(case["query"]),
                    max(8, case["top_k"]), "all",
                )
                paths = [item["path"] for item in results]
                self.assertTrue(any(path in paths for path in case["expected_any"]), paths)
                self.assertFalse(any(path in paths for path in case.get("forbidden", [])), paths)

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


if __name__ == "__main__":
    unittest.main()
