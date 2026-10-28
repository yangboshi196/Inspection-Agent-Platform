"""Inspect Milvus collections and MySQL spec rules."""
from __future__ import annotations

import json

from inspection_platform.app.config import get_settings
from inspection_platform.deps import get_model_manager, platform_embedding_model_name
from inspection_platform.specification.service import SpecificationService


def milvus_summary() -> None:
    s = get_settings()
    print(f"milvus_uri=http://{s.milvus_host}:{s.milvus_port}")
    from pymilvus import MilvusClient

    client = MilvusClient(uri=f"http://{s.milvus_host}:{s.milvus_port}")
    cols = list(client.list_collections() or [])
    print(f"collections={cols}")
    for name in cols:
        st = client.get_collection_stats(name)
        print(f"  {name}: row_count={st.get('row_count', 0)}")

    if "spec_rules" in cols:
        rows = client.query(
            collection_name="spec_rules",
            filter="",
            output_fields=["text", "meta_json"],
            limit=5,
        )
        print(f"spec_rules sample ({len(rows)} rows shown):")
        for row in rows:
            meta = json.loads(str(row.get("meta_json") or "{}"))
            text = str(row.get("text") or "")[:80]
            print(f"  - rule_id={meta.get('rule_id')} name={meta.get('name')} text={text!r}")

    if "default" in cols:
        rows = client.query(
            collection_name="default",
            filter="",
            output_fields=["meta_json"],
            limit=3,
        )
        print("default kb sample doc_ids:")
        for row in rows:
            meta = json.loads(str(row.get("meta_json") or "{}"))
            print(f"  - doc_id={meta.get('doc_id')} kb_id={meta.get('kb_id')}")


def mysql_spec_summary() -> None:
    svc = SpecificationService(
        get_model_manager(),
        embedding_model_name=platform_embedding_model_name(),
    )
    stats = svc.stats()
    print(f"spec sqlite={stats.get('sqlite_path')} rule_chunks={stats.get('rule_chunks')}")
    published = svc.list_rules(status="published")
    draft = svc.list_rules(status="draft")
    print(f"mysql_spec published={len(published)} draft={len(draft)}")
    for r in published[:8]:
        print(
            f"  - {r.get('rule_id')[:12]}… {r.get('name')} "
            f"| algos={r.get('recommended_algorithms')}"
        )


def main() -> None:
    milvus_summary()
    print("---")
    mysql_spec_summary()


if __name__ == "__main__":
    main()
