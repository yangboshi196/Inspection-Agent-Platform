#!/usr/bin/env python3
"""MCP server — exposes sia platform services to Hermes Agent via stdio."""

from __future__ import annotations

import json
import sys
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Install dependencies: pip install mcp", file=sys.stderr)
    raise


def _bootstrap_platform() -> None:
    try:
        from inspection_platform.env_bootstrap import apply_project_dotenv, bootstrap_platform_env

        apply_project_dotenv(override=True)
        bootstrap_platform_env()
    except Exception:
        pass


_bootstrap_platform()

mcp = FastMCP("sia-platform")


def _err(message: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "error": message}
    out.update(extra)
    return out


def _ok(**data: Any) -> dict[str, Any]:
    return {"ok": True, **data}


@mcp.tool()
def SIA_list_documents(limit: int = 50) -> dict[str, Any]:
    """List documents in the platform document library (SQLite metadata)."""
    try:
        from inspection_platform.document.service import DocumentService

        svc = DocumentService()
        svc.ensure_ready()
        lim = max(1, min(500, int(limit)))
        items = svc.list_document(limit=lim, offset=0, brief=True)
        return _ok(count=len(items), items=items)
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def SIA_ingest_knowledge(
    document_id: str,
    kb_id: str = "default",
    replace: bool = True,
) -> dict[str, Any]:
    """Ingest a document from the library into the knowledge vector store (Milvus)."""
    try:
        from inspection_platform.deps import get_knowledge_ingest_service

        result = get_knowledge_ingest_service().ingest_from_document(
            document_id=document_id.strip(),
            kb_id=(kb_id or "default").strip() or "default",
            replace_existing=replace,
        )
        return _ok(result=result)
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def SIA_query_knowledge(
    query: str,
    kb_id: str = "default",
    top_k: int = 5,
) -> dict[str, Any]:
    """Vector search over ingested knowledge chunks."""
    try:
        from inspection_platform.deps import get_knowledge_ingest_service

        hits = get_knowledge_ingest_service().query(
            kb_id=(kb_id or "default").strip() or "default",
            query=query.strip(),
            top_k=max(1, min(50, int(top_k))),
        )
        return _ok(count=len(hits), hits=hits)
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def SIA_generate_inspection_work(
    topic: str,
    region_id: str | None = None,
) -> dict[str, Any]:
    """Generate a draft inspection work from natural language (does not persist)."""
    try:
        from inspection_platform.deps import get_model_manager, get_specification_service
        from inspection_platform.inspection_work.matcher import generate_inspection_works

        result = generate_inspection_works(
            spec_svc=get_specification_service(),
            mm=get_model_manager(),
            region_id=region_id,
            topic=topic,
            max_works=1,
        )
        drafts = result.get("works") or []
        trace = result.get("retrieval_trace") or {}
        works_out: list[dict[str, Any]] = []
        for w in drafts:
            row = dict(w)
            row["ai_generation_trace"] = trace
            works_out.append(row)
        return _ok(
            count=len(works_out),
            works=works_out,
            retrieval_trace=trace,
        )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def SIA_list_inspection_works(
    limit: int = 20,
    work_status: str | None = None,
) -> dict[str, Any]:
    """List persisted inspection works; optional filter by work_status (online/offline)."""
    try:
        from inspection_platform.inspection_work.service import InspectionWorkService

        svc = InspectionWorkService()
        svc.ensure_ready()
        lim = max(1, min(500, int(limit)))
        items, total = svc.list_all(limit=lim, offset=0)
        status = (work_status or "").strip()
        if status:
            items = [w for w in items if str(w.get("work_status") or "") == status]
        return _ok(items=items, total=total, count=len(items), limit=lim)
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def SIA_create_inspection_work(payload_json: str) -> dict[str, Any]:
    """Create an inspection work from a JSON payload (validated via platform service)."""
    try:
        from inspection_platform.deps import get_specification_service
        from inspection_platform.inspection_work.service import InspectionWorkService
        from inspection_platform.inspection_work.validation import validate_work_payload

        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            return _err("payload_json must decode to a JSON object")

        rw = InspectionWorkService()
        spec_svc = get_specification_service()
        work_status = str(payload.get("work_status") or "online").strip() or "online"
        region_ids, primary_region = validate_work_payload(
            rule_set=payload.get("rule_set") or [],
            algorithm_set=payload.get("algorithm_set") or [],
            equipment_set=payload.get("equipment_set") or [],
            spec_svc=spec_svc,
            work_svc=rw,
            require_online_rules=work_status == "online",
            explicit_region_ids=payload.get("region_ids"),
        )
        rule_set = payload.get("rule_set") or []
        algorithm_set = payload.get("algorithm_set") or []
        if work_status == "online":
            rule_set, algorithm_set = rw.refresh_work_snapshots(
                rule_set=rule_set,
                algorithm_set=algorithm_set,
                spec_svc=spec_svc,
            )
        row = rw.create(
            work_id=payload.get("work_id"),
            region_id=primary_region,
            region_ids=region_ids,
            name=str(payload.get("name") or "").strip(),
            desc=str(payload.get("desc") or ""),
            rule_set=rule_set,
            algorithm_set=algorithm_set,
            equipment_set=payload.get("equipment_set") or [],
            equipment_algo_params=payload.get("equipment_algo_params") or {},
            schedule_mode=str(payload.get("schedule_mode") or "manual"),
            schedule_interval=payload.get("schedule_interval"),
            schedule_times=payload.get("schedule_times"),
            source=str(payload.get("source") or "manual"),
            work_status=work_status,
        )
        return _ok(work=row)
    except json.JSONDecodeError as e:
        return _err(f"invalid JSON: {e}")
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def SIA_patch_inspection_work(work_id: str, patch_json: str) -> dict[str, Any]:
    """Partially update an inspection work (e.g. set work_status to online)."""
    try:
        from inspection_platform.deps import get_specification_service
        from inspection_platform.inspection_work.service import InspectionWorkService
        from inspection_platform.inspection_work.validation import validate_work_payload

        patch = json.loads(patch_json)
        if not isinstance(patch, dict):
            return _err("patch_json must decode to a JSON object")

        rw = InspectionWorkService()
        spec_svc = get_specification_service()
        wid = work_id.strip()
        merged = rw.get(wid)
        if not merged:
            return _err("work not found", status=404)

        payload = {k: v for k, v in patch.items() if v is not None}
        if not payload:
            return _ok(work=merged)

        rule_set = payload.get("rule_set", merged.get("rule_set") or [])
        algorithm_set = payload.get("algorithm_set", merged.get("algorithm_set") or [])
        equipment_set = payload.get("equipment_set", merged.get("equipment_set") or [])
        next_status = payload.get("work_status", merged.get("work_status") or "online")
        explicit_region_ids = payload.get("region_ids") if "region_ids" in payload else None

        region_ids, primary_region = validate_work_payload(
            rule_set=rule_set,
            algorithm_set=algorithm_set,
            equipment_set=equipment_set,
            spec_svc=spec_svc,
            work_svc=rw,
            require_online_rules=next_status == "online",
            explicit_region_ids=explicit_region_ids,
        )
        if next_status == "online":
            rule_set, algorithm_set = rw.refresh_work_snapshots(
                rule_set=rule_set,
                algorithm_set=algorithm_set,
                spec_svc=spec_svc,
            )
            payload["rule_set"] = rule_set
            payload["algorithm_set"] = algorithm_set

        payload["region_id"] = primary_region
        payload["region_ids"] = region_ids
        row = rw.update(wid, **payload)
        if not row:
            return _err("work not found", status=404)
        return _ok(work=row)
    except json.JSONDecodeError as e:
        return _err(f"invalid JSON: {e}")
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def SIA_list_inspection_events(
    limit: int = 30,
    status: str | None = None,
    work_id: str | None = None,
) -> dict[str, Any]:
    """List recent inspection events with optional status/work_id filters."""
    try:
        from inspection_platform.inspection_event.service import InspectionEventService

        svc = InspectionEventService()
        lim = max(1, min(500, int(limit)))
        items, total = svc.list_events(
            status=status,
            work_id=work_id,
            limit=lim,
            offset=0,
        )
        return _ok(items=items, total=total, count=len(items), limit=lim)
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def SIA_patch_inspection_event(event_id: str, patch_json: str) -> dict[str, Any]:
    """Update inspection event status, handler, or resolution fields."""
    try:
        from inspection_platform.inspection_event.service import InspectionEventService

        patch = json.loads(patch_json)
        if not isinstance(patch, dict):
            return _err("patch_json must decode to a JSON object")

        svc = InspectionEventService()
        row = svc.update(
            event_id.strip(),
            status=patch.get("status"),
            handler=patch.get("handler"),
            handled_at=patch.get("handled_at"),
            resolution_outcome=patch.get("resolution_outcome"),
            resolution_detail=patch.get("resolution_detail"),
        )
        if not row:
            return _err("event not found", status=404)
        return _ok(event=row)
    except json.JSONDecodeError as e:
        return _err(f"invalid JSON: {e}")
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err(str(e))


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
