"""Quick Milvus connectivity check."""
from __future__ import annotations

from inspection_platform.app.config import get_settings


def main() -> None:
    s = get_settings()
    print(f"milvus_uri=http://{s.milvus_host}:{s.milvus_port}")
    try:
        from pymilvus import MilvusClient
    except ImportError as e:
        print(f"pymilvus_missing: {e}")
        return

    try:
        client = MilvusClient(uri=f"http://{s.milvus_host}:{s.milvus_port}")
        cols = list(client.list_collections() or [])
        print(f"collections_count={len(cols)}")
        for name in cols[:12]:
            try:
                st = client.get_collection_stats(name)
                rows = st.get("row_count", 0)
            except Exception as ex:
                rows = f"err:{ex}"
            print(f"  - {name}: rows={rows}")
        print("milvus_ok")
    except Exception as e:
        print(f"milvus_fail: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
