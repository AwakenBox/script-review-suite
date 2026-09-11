"""Focused retrieval behavior tests using a tiny, self-contained knowledge base."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from search_knowledge import search_knowledge


class SearchKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "knowledge"
        self.root.mkdir()
        self.cards = [
            self.card("K01", "人物选择与动机", "reference", ["V1", "V2"],
                      ["V1-04", "V2-02"], ["人物动机", "人物选择"],
                      ["突然改变", "动机"], "重大选择需要此前行为和当场条件支撑。"),
            self.card("C01", "一次缺乏铺垫的离开", "case", ["V2"], ["V2-02"],
                      ["人物动机", "转折"], ["突然决定"], "人物突然离开，比较铺垫充分和不足的两稿。"),
            self.card("K02", "空间与声音的表达", "reference", ["V3"], ["V3-03"],
                      ["声音", "视听语言"], ["声画关系"], "声音可以改变观众对空间的感受。"),
            self.card("K03", "留白的边界", "reference", ["V2"], ["V2-06"],
                      ["留白"], ["开放结局"], "未解答的细节与没有兑现的期待应区分。"),
        ]
        self.write_index()

    def card(self, card_id, title, kind, modes, dimensions, tags, aliases, summary):
        path = f"{card_id}.md"
        (self.root / path).write_text(f"{card_id} selected body", encoding="utf-8")
        return {"id": card_id, "title": title, "kind": kind, "path": path,
                "modes": modes, "dimensions": dimensions, "tags": tags,
                "aliases": aliases, "summary": summary,
                "sources": [] if kind == "case" else [{
                    "title": "Test source", "url": "https://example.com/reference",
                    "checked": "2026-09-11"}]}

    def write_index(self):
        (self.root / "index.json").write_text(json.dumps({
            "knowledge_version": "0.1.0", "cards": self.cards
        }, ensure_ascii=False), encoding="utf-8")

    def search(self, query, **kwargs):
        return search_knowledge(query, self.root, **kwargs)

    def test_natural_chinese_query_and_bigrams(self):
        result = self.search("人物突然改变动机")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["hits"][0]["id"], "K01")
        self.assertIn("C01", [hit["id"] for hit in result["hits"]])
        # No complete tag/alias appears in this query: adjacent fragments suffice.
        fragment = self.search("空间组织怎样改变感受")
        self.assertEqual(fragment["hits"][0]["id"], "K02")
        self.assertEqual(self.search("留白")["hits"][0]["id"], "K03")

    def test_mode_and_dimension_are_hard_filters(self):
        result = self.search("人物动机", mode="V2", dimension="V2-02")
        self.assertEqual({hit["id"] for hit in result["hits"]}, {"K01", "C01"})
        self.assertEqual(self.search("人物动机", mode="V1")["hits"][0]["id"], "K01")
        self.assertEqual(self.search("人物动机", mode="V3")["hits"], [])
        self.assertEqual(self.search("人物动机", dimension="V2-06")["hits"], [])

    def test_empty_unrelated_and_single_character_have_no_hits(self):
        for query in ("", "   ", "量子计算机芯片", "人", "a", "!!!"):
            with self.subTest(query=query):
                result = self.search(query, mode="V2")
                self.assertEqual(result["status"], "no_match")
                self.assertEqual(result["hits"], [])

    def test_unsafe_paths_cannot_expose_external_text(self):
        outside = self.root.parent / "secret.md"
        outside.write_text("do not expose", encoding="utf-8")
        for malicious in ("../secret.md", "..\\secret.md", str(outside.resolve()), "C:\\secret.md"):
            with self.subTest(path=malicious):
                self.cards[0]["path"] = malicious
                self.write_index()
                with self.assertRaisesRegex(ValueError, "relative path|escapes"):
                    self.search("人物动机", include_text=True)

    def test_limit_metadata_and_selected_text_only(self):
        # A non-selected body is deliberately unreadable as UTF-8. Search must
        # inspect metadata only and read full text solely for selected matches.
        (self.root / "K02.md").write_bytes(b"\xff\xfe\xff")
        result = self.search("人物动机", limit=1, include_text=True)
        self.assertEqual(len(result["hits"]), 1)
        hit = result["hits"][0]
        self.assertEqual(hit["text"], "K01 selected body")
        self.assertEqual(hit["path"], "K01.md")
        self.assertEqual(hit["sources"][0]["url"], "https://example.com/reference")
        self.assertGreater(hit["relevance"], 0)
        self.assertTrue(hit["hit_reasons"])
        self.assertNotIn("text", self.search("人物动机", limit=1)["hits"][0])

    def test_invalid_arguments_and_index_are_clear_errors(self):
        for options in ({"mode": "V5"}, {"dimension": "V2-12"},
                        {"dimension": "V1-1"}, {"mode": "V1", "dimension": "V2-02"},
                        {"limit": 0}, {"limit": 9}, {"limit": True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.search("人物动机", **options)
        self.cards[0]["id"] = "invalid-id"
        self.write_index()
        with self.assertRaisesRegex(ValueError, "identifier"):
            self.search("人物动机")
        self.cards[0]["id"] = "K01"
        self.cards[0]["sources"] = "wrong"
        self.write_index()
        with self.assertRaisesRegex(ValueError, "sources"):
            self.search("人物动机")

    def test_cli_success_and_invalid_argument_exit(self):
        command = [sys.executable, str(Path(__file__).with_name("search_knowledge.py")),
                   "--knowledge-dir", str(self.root), "--query", "人物动机"]
        result = subprocess.run(command + ["--limit", "1"], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout.decode("utf-8"))["hits"]), 1)
        invalid = subprocess.run(command + ["--dimension", "V2-99"], capture_output=True)
        self.assertEqual(invalid.returncode, 2)
        self.assertIn(b"dimension", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
