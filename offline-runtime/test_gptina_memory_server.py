import importlib.util
import pathlib
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("gptina_memory_server", HERE / "gptina_memory_server.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class MemoryServerTests(unittest.TestCase):
    def test_profiles_exclude_personal_sources_before_search(self):
        self.assertTrue(mod.profile_allows("offline-runtime/README.md", "technical"))
        self.assertFalse(mod.profile_allows("GPTINA_SELF_PORTRAIT.md", "technical"))
        self.assertFalse(mod.profile_allows("CHRONICLE.md", "technical"))
        self.assertFalse(mod.profile_allows("rag/memories/gptina/2026/09/2026-09-23--serie-visiva.md", "technical"))
        self.assertTrue(mod.profile_allows("rag/index/GPTINA_VISUAL_CHRONOLOGY.md", "visual"))
        self.assertTrue(mod.profile_allows("GPTINA_SELF_PORTRAIT.md", "all"))

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
