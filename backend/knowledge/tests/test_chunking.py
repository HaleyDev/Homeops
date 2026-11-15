from django.test import SimpleTestCase

from knowledge.chunking import ChunkingError, ChunkLimitError, split_text


class TextChunkingTests(SimpleTestCase):
    def test_unicode_crlf_and_cr_are_normalized(self):
        chunks = split_text("  中文🙂\r\nEnglish\r混合文本  ")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].content, "中文🙂\nEnglish\n混合文本")
        self.assertEqual(chunks[0].start, 0)
        self.assertEqual(chunks[0].end, len(chunks[0].content))

    def test_blank_text_returns_no_chunks(self):
        self.assertEqual(split_text(" \r\n\t "), [])

    def test_natural_boundary_and_offsets(self):
        text = "第一段内容。\n第二段内容。\n第三段内容。"
        chunks = split_text(text, chunk_size=10, overlap=2)
        self.assertGreaterEqual(len(chunks), 2)
        for chunk in chunks:
            self.assertEqual(chunk.content, text[chunk.start : chunk.end])
            self.assertGreater(chunk.end, chunk.start)
            self.assertEqual(
                chunk.source_meta,
                {"char_start": chunk.start, "char_end": chunk.end},
            )

    def test_hard_cut_and_overlap_always_move_forward(self):
        text = "abcdefghij" * 20
        chunks = split_text(text, chunk_size=10, overlap=3)
        self.assertEqual(chunks[0].content, "abcdefghij")
        self.assertEqual(chunks[1].start, 7)
        starts = [chunk.start for chunk in chunks]
        self.assertEqual(starts, sorted(set(starts)))

    def test_short_boundaries_do_not_loop(self):
        chunks = split_text("a。b。c。d。", chunk_size=2, overlap=1)
        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(len(chunks), 8)

    def test_chunk_limit_is_enforced(self):
        with self.assertRaises(ChunkLimitError):
            split_text("a" * 100, chunk_size=5, overlap=0, max_chunks=2)

    def test_invalid_configuration_is_rejected(self):
        for kwargs in (
            {"chunk_size": 0},
            {"chunk_size": 10, "overlap": 10},
            {"max_chunks": 0},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ChunkingError):
                split_text("content", **kwargs)
