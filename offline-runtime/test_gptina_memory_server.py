import importlib.util
import pathlib
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("gptina_memory_server", HERE / "gptina_memory_server.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class MemoryServerTests(unittest.TestCase):
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
