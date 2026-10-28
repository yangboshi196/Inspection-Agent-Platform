"""知识库 ingest 事件化流水线单元测试（mock Chroma，不依赖 embedding API）。"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from agent_base.rag.embedded_chunk import EmbeddedChunk

from inspection_platform.knowledge.ingest_pipeline import run_ingest_pipeline


class IngestPipelineRollbackTest(unittest.TestCase):
    def test_commit_failure_restores_backup(self) -> None:
        store = MagicMock()
        old = [
            EmbeddedChunk(
                chunk_id="doc1:0",
                text="old",
                vector=[0.1, 0.2],
                meta={"chunk_id": "doc1:0", "doc_id": "doc1", "kb_id": "default"},
            )
        ]
        store.count_by_filters.return_value = 1
        store.export_embedded_chunks_by_filters.return_value = list(old)
        store.delete_by_filters.return_value = 1
        store.add_embedded_chunks.side_effect = [ValueError("chroma write failed"), None]

        mm = MagicMock()
        with patch(
            "inspection_platform.knowledge.ingest_pipeline.extract_plain_text",
            return_value=("txt", "hello world"),
        ), patch(
            "inspection_platform.knowledge.ingest_pipeline.chunk_text",
            return_value=["hello world"],
        ), patch(
            "inspection_platform.knowledge.ingest_pipeline._embed_all_chunks",
            return_value=[
                EmbeddedChunk(
                    chunk_id="doc1:0",
                    text="hello world",
                    vector=[0.3, 0.4],
                    meta={"chunk_id": "doc1:0", "doc_id": "doc1"},
                )
            ],
        ):
            with self.assertRaises(ValueError):
                run_ingest_pipeline(
                    store=store,
                    mm=mm,
                    embedding_model_name=None,
                    filename="a.txt",
                    content=b"hello world",
                    kb_id="default",
                    doc_id="doc1",
                    library_sid="doc1",
                    replace_existing=True,
                    max_chars=900,
                    overlap=120,
                )

        self.assertGreaterEqual(store.add_embedded_chunks.call_count, 2)
        restored = store.add_embedded_chunks.call_args_list[-1].args[0]
        self.assertEqual(restored[0].text, "old")

    def test_embed_failure_does_not_touch_chroma(self) -> None:
        store = MagicMock()
        mm = MagicMock()
        with patch(
            "inspection_platform.knowledge.ingest_pipeline.extract_plain_text",
            return_value=("txt", "x"),
        ), patch(
            "inspection_platform.knowledge.ingest_pipeline.chunk_text",
            return_value=["x"],
        ), patch(
            "inspection_platform.knowledge.ingest_pipeline._embed_all_chunks",
            side_effect=ValueError("embed failed"),
        ):
            with self.assertRaises(ValueError):
                run_ingest_pipeline(
                    store=store,
                    mm=mm,
                    embedding_model_name=None,
                    filename="a.txt",
                    content=b"x",
                    kb_id="default",
                    doc_id="doc1",
                    library_sid=None,
                    replace_existing=True,
                    max_chars=900,
                    overlap=120,
                )

        store.delete_by_filters.assert_not_called()
        store.add_embedded_chunks.assert_not_called()


if __name__ == "__main__":
    unittest.main()
