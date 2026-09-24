import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from gptina_semantic_index import SemanticIndex, prepare


class FakeIndex:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE chunks (source, heading, text)")
        self.db.executemany("INSERT INTO chunks VALUES (?, ?, ?)", [
            ("SHARED_LANGUAGE.md", "Scodinzolina", "Nome affettuoso per GPTina"),
            ("rag/memories/tessa/private.md", "Scodinzolina", "Non indicizzare Tessa"),
        ])
        # The existing manifest-filtered index must never insert another owner's
        # source. This fake index tests the cache contract with its own rows.
        self.db.execute("DELETE FROM chunks WHERE source LIKE '%tessa/%'")
        self.info = {1: {"kind": "shared_language"}}


class FakeEmbedder:
    def embed(self, texts, **_kwargs):
        for _ in texts:
            yield [1.0, 0.0]


@unittest.skipUnless(importlib.util.find_spec("numpy"), "optional semantic dependency")
class SemanticCacheTests(unittest.TestCase):
    def test_cache_is_reusable_and_invalidates_on_source_change(self):
        index = FakeIndex()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            report = prepare(index, cache, FakeEmbedder())
            self.assertEqual(report["chunks"], 1)
            semantic = SemanticIndex(index, cache, FakeEmbedder())
            found = semantic.search("Come ti chiamavo?", "relationship")
            self.assertEqual([item["path"] for item in found], ["SHARED_LANGUAGE.md"])
            index.db.execute("UPDATE chunks SET text='Nuova versione'")
            with self.assertRaisesRegex(ValueError, "obsoleto"):
                SemanticIndex(index, cache, FakeEmbedder())


if __name__ == "__main__":
    unittest.main()
