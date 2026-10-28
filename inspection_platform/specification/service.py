"""规范规则：MySQL 元数据 + Milvus 规则向量（原文仅文档库 + 知识库向量）。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from agent_base.model_manager.manager import ModelManager
from inspection_platform.deps import platform_embed_texts
from agent_base.rag.embedded_chunk import EmbeddedChunk
from inspection_platform.app.vector import create_vector_store

from .config import spec_db_path
from .db import get_connection, init_db, row_to_api
from .levels import infer_level
from .rule_embed import build_rule_embed_text, requirements_preview

KB_RULES = "spec_rules"

_CONTENT_FIELDS = frozenset({"name", "desc", "requirements", "source", "level", "doc_id"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vector_action_error(exc: Exception, *, action: str) -> ValueError:
    msg = str(exc).strip() or type(exc).__name__
    hint = ""
    if "Milvus" in type(exc).__name__ or "connect" in msg.lower() or "19530" in msg:
        hint = "；请检查 Milvus 服务（MILVUS_HOST / MILVUS_PORT）是否可达"
    return ValueError(f"{action}失败：{msg}{hint}")


class SpecificationService:
    def __init__(
        self,
        model_manager: ModelManager,
        *,
        embedding_model_name: str | None = None,
    ) -> None:
        self._mm = model_manager
        self._emb_name = embedding_model_name

    def _rule_store(self):
        return create_vector_store(kb_id=KB_RULES)

    def _delete_rule_vectors(self, store: Any, rule_id: str) -> int:
        """删除规则在 spec_rules 中的向量分片（rule_id / chunk_id 双键）。"""
        rid = rule_id.strip()
        if not rid:
            return 0
        removed = 0
        for filters in ({"rule_id": rid}, {"chunk_id": rid}):
            try:
                removed += int(store.delete_by_filters(filters) or 0)
            except Exception:
                pass
        return removed

    def _safe_delete_rule_vectors(self, store: Any, rule_id: str) -> None:
        try:
            self._delete_rule_vectors(store, rule_id)
        except Exception:
            pass

    def _rule_vector_backend_ok(self) -> tuple[bool, str]:
        try:
            store = self._rule_store()
            _ = store.chunk_count
            return True, "规则向量库可用（Milvus）"
        except Exception as exc:
            return False, f"规则向量库不可用：{exc}"

    def _offline_works_for_rule(self, rule_id: str) -> int:
        from inspection_platform.inspection_work.service import InspectionWorkService

        svc = InspectionWorkService()
        svc.ensure_ready()
        return svc.offline_works_by_rule(rule_id)

    def count_rules_for_doc(self, doc_id: str, *, status: str | None = None) -> int:
        did = doc_id.strip()
        if not did:
            return 0
        conn = get_connection()
        try:
            if status:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM spec_rule WHERE doc_id = ? AND status = ?",
                    (did, status.strip()),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM spec_rule WHERE doc_id = ?",
                    (did,),
                ).fetchone()
            return int(row["c"]) if row else 0
        finally:
            conn.close()

    def list_rule_ids_for_doc(self, doc_id: str, *, status: str | None = None) -> list[str]:
        did = doc_id.strip()
        if not did:
            return []
        conn = get_connection()
        try:
            if status:
                cur = conn.execute(
                    "SELECT rule_id FROM spec_rule WHERE doc_id = ? AND status = ?",
                    (did, status.strip()),
                )
            else:
                cur = conn.execute(
                    "SELECT rule_id FROM spec_rule WHERE doc_id = ?",
                    (did,),
                )
            return [str(r["rule_id"]) for r in cur.fetchall()]
        finally:
            conn.close()

    def assert_doc_extractable(self, doc_id: str, *, re_extract: bool = False) -> None:
        did = doc_id.strip()
        if not did:
            raise ValueError("doc_id 不能为空")
        total = self.count_rules_for_doc(did)
        if total == 0:
            return
        if re_extract:
            return
        raise ValueError(
            f"文档 {did} 已抽取过规范条目；同一 PDF 暂不允许重复抽取。"
            "若需再次抽取，请设置 re_extract=true（将清除该文档下全部草稿后重抽，已发布条目保留）。"
        )

    def delete_draft_rules_for_doc(self, doc_id: str, *, conn: Any | None = None) -> int:
        """删除某文档下全部草稿规则（含 spec_rules 向量分片，不删已发布）。"""
        did = doc_id.strip()
        if not did:
            return 0
        store = self._rule_store()
        try:
            store.delete_by_filters({"doc_id": did, "status": "draft"})
        except Exception:
            pass
        own = conn is None
        if own:
            conn = get_connection()
        try:
            cur = conn.execute(
                "SELECT rule_id FROM spec_rule WHERE doc_id = ? AND status = 'draft'",
                (did,),
            )
            ids = [str(r["rule_id"]) for r in cur.fetchall()]
            for rid in ids:
                self._delete_rule_vectors(store, rid)
            if not ids:
                return 0
            conn.execute(
                "DELETE FROM spec_rule WHERE doc_id = ? AND status = 'draft'",
                (did,),
            )
            if own:
                conn.commit()
            return len(ids)
        except Exception:
            if own:
                conn.rollback()
            raise
        finally:
            if own:
                conn.close()

    def _check_source_document(self, doc_id: str) -> dict[str, Any]:
        from inspection_platform.document.service import DocumentService

        did = doc_id.strip()
        if not did:
            return {"ok": False, "message": "未关联来源文档"}
        doc_svc = DocumentService()
        try:
            rec = doc_svc.get_by_id(did)
        except KeyError:
            return {"ok": False, "message": f"来源文档 {did} 在文档库中不存在"}
        try:
            path = doc_svc.resolve_path(did)
        except KeyError:
            return {"ok": False, "message": f"来源文档 {did} 在文档库中不存在"}
        if not path.is_file():
            return {
                "ok": False,
                "message": f"来源文档 {did} 原文文件缺失（{rec.storage_relpath}）",
            }
        return {"ok": True, "message": "来源文档存在且原文可读", "document_name": rec.name}

    def publish_readiness(self, rule_id: str) -> dict[str, Any]:
        rec = self.get_rule(rule_id)
        checks: list[dict[str, Any]] = []

        name_ok = bool((rec.get("name") or "").strip())
        checks.append(
            {
                "id": "name",
                "ok": name_ok,
                "message": "条目标题已填写" if name_ok else "须填写条目标题",
            }
        )

        desc = (rec.get("desc") or "").strip()
        req = (rec.get("requirements") or "").strip()
        body_ok = bool(desc or req)
        checks.append(
            {
                "id": "content",
                "ok": body_ok,
                "message": "场景或要求至少一项非空" if body_ok else "须填写适用场景或可执行要求",
            }
        )

        doc_id = (rec.get("doc_id") or "").strip()
        doc_ok = bool(doc_id)
        checks.append(
            {
                "id": "doc_id",
                "ok": doc_ok,
                "message": "已关联来源文档" if doc_ok else "须关联来源文档（doc_id）",
            }
        )

        trace = rec.get("source_trace") or {}
        trace_ok = bool(doc_id) and (
            trace.get("doc_id") == doc_id or trace.get("document_id") == doc_id
        )
        checks.append(
            {
                "id": "source_trace",
                "ok": trace_ok,
                "message": "来源追溯信息完整"
                if trace_ok
                else "缺少来源追溯（请从文档抽取或保存 doc_id 追溯）",
            }
        )

        if doc_id:
            doc_check = self._check_source_document(doc_id)
            checks.append(
                {
                    "id": "source_document",
                    "ok": doc_check["ok"],
                    "message": doc_check["message"],
                }
            )

        vec_ok, vec_msg = self._rule_vector_backend_ok()
        checks.append(
            {
                "id": "vector_backend",
                "ok": vec_ok,
                "message": vec_msg,
            }
        )

        ready = all(c["ok"] for c in checks)
        return {"rule_id": rec["rule_id"], "ready": ready, "checks": checks}

    def create_rule(
        self,
        *,
        name: str,
        desc: str = "",
        source: str = "",
        requirements: str = "",
        doc_id: str | None = None,
        level: str | None = None,
        recommended_algorithms: list[str] | None = None,
        recommended_regions: list[str] | None = None,
        algorithm_reasoning: str = "",
        region_reasoning: str = "",
        source_trace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        nm = name.strip()
        if not nm:
            raise ValueError("name is required")
        lv = (level or "").strip() or infer_level(
            name=nm, desc=desc or "", requirements=requirements or "", source=source or ""
        )
        algos = [str(x).strip() for x in (recommended_algorithms or []) if str(x).strip()]
        regions = [str(x).strip() for x in (recommended_regions or []) if str(x).strip()]
        rule_id = uuid.uuid4().hex
        now = _now()
        did = (doc_id or "").strip() or None
        trace = dict(source_trace or {})
        if did and not trace.get("doc_id"):
            trace["doc_id"] = did
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO spec_rule (
                    rule_id, name, `desc`, source, level, requirements, doc_id, status,
                    recommended_algorithms_json, recommended_regions_json,
                    algorithm_reasoning, region_reasoning, source_trace_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule_id,
                    nm,
                    (desc or "").strip(),
                    (source or "").strip(),
                    lv,
                    (requirements or "").strip(),
                    did,
                    json.dumps(algos, ensure_ascii=False),
                    json.dumps(regions, ensure_ascii=False),
                    (algorithm_reasoning or "").strip(),
                    (region_reasoning or "").strip(),
                    json.dumps(trace, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_rule(rule_id)

    def create_rules_batch(
        self,
        items: list[dict[str, Any]],
        *,
        conn: Any | None = None,
    ) -> list[str]:
        """在同一 SQLite 事务中批量创建草稿规则；失败则全部回滚。"""
        if not items:
            return []
        own = conn is None
        if own:
            conn = get_connection()
        created_ids: list[str] = []
        try:
            if own:
                conn.execute("START TRANSACTION")
            now = _now()
            for item in items:
                nm = str(item.get("name") or "").strip()
                if not nm:
                    raise ValueError("name is required")
                desc = str(item.get("desc") or "").strip()
                source = str(item.get("source") or "").strip()
                requirements = str(item.get("requirements") or "").strip()
                did = (str(item.get("doc_id") or "").strip() or None)
                lv = str(item.get("level") or "").strip() or infer_level(
                    name=nm, desc=desc, requirements=requirements, source=source
                )
                algos = item.get("recommended_algorithms") or []
                regions = item.get("recommended_regions") or []
                ar = str(item.get("algorithm_reasoning") or "").strip()
                rr = str(item.get("region_reasoning") or "").strip()
                trace = dict(item.get("source_trace") or {})
                if did and not trace.get("doc_id"):
                    trace["doc_id"] = did
                rule_id = uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT INTO spec_rule (
                        rule_id, name, `desc`, source, level, requirements, doc_id, status,
                        recommended_algorithms_json, recommended_regions_json,
                        algorithm_reasoning, region_reasoning, source_trace_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rule_id,
                        nm,
                        desc,
                        source,
                        lv,
                        requirements,
                        did,
                        json.dumps(
                            [str(x).strip() for x in algos if str(x).strip()],
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            [str(x).strip() for x in regions if str(x).strip()],
                            ensure_ascii=False,
                        ),
                        ar,
                        rr,
                        json.dumps(trace, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                created_ids.append(rule_id)
            if own:
                conn.commit()
            return created_ids
        except Exception:
            if own:
                conn.rollback()
            raise
        finally:
            if own:
                conn.close()

    def sync_document_name(self, doc_id: str, document_name: str) -> dict[str, Any]:
        """文档改名后同步 spec_rule.source_trace 与已发布规则向量 metadata（不重算向量）。"""
        did = doc_id.strip()
        name = document_name.strip()
        if not did:
            return {"rules_updated": 0, "vectors_metadata_updated": 0}
        conn = get_connection()
        updated = 0
        vectors_metadata_updated = 0
        saved_rows: list[Any] = []
        try:
            cur = conn.execute("SELECT * FROM spec_rule WHERE doc_id = ?", (did,))
            saved_rows = cur.fetchall()
            now = _now()
            for row in saved_rows:
                rec = row_to_api(row)
                trace = dict(rec.get("source_trace") or {})
                trace["doc_id"] = did
                trace["document_name"] = name
                conn.execute(
                    """
                    UPDATE spec_rule SET source_trace_json = ?, updated_at = ?
                    WHERE rule_id = ?
                    """,
                    (json.dumps(trace, ensure_ascii=False), now, rec["rule_id"]),
                )
                updated += 1
            conn.commit()
        finally:
            conn.close()
        store = self._rule_store()
        for row in saved_rows:
            rec = row_to_api(row)
            if rec.get("status") != "published":
                continue
            trace = dict(rec.get("source_trace") or {})
            trace["doc_id"] = did
            trace["document_name"] = name
            vectors_metadata_updated += store.update_metadata_for_filters(
                {"rule_id": rec["rule_id"]},
                {
                    "document_name": name,
                    "source_trace_json": json.dumps(trace, ensure_ascii=False),
                },
            )
        return {"rules_updated": updated, "vectors_metadata_updated": vectors_metadata_updated}

    def get_rule(self, rule_id: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            cur = conn.execute("SELECT * FROM spec_rule WHERE rule_id = ?", (rule_id.strip(),))
            row = cur.fetchone()
        finally:
            conn.close()
        if row is None:
            raise KeyError(rule_id)
        return row_to_api(row)

    def list_rules(self, *, status: str | None = None) -> list[dict[str, Any]]:
        conn = get_connection()
        try:
            if status:
                cur = conn.execute(
                    "SELECT * FROM spec_rule WHERE status = ? ORDER BY updated_at DESC",
                    (status.strip(),),
                )
            else:
                cur = conn.execute("SELECT * FROM spec_rule ORDER BY updated_at DESC")
            return [row_to_api(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def validate_rules_for_inspection(self, rule_ids: list[str]) -> None:
        """巡检业务引用的规范须为已发布状态。"""
        for raw in rule_ids:
            rid = str(raw).strip()
            if not rid:
                continue
            try:
                rec = self.get_rule(rid)
            except KeyError:
                raise ValueError(f"规范不存在：{rid}") from None
            label = rec.get("name") or rid
            if rec.get("status") != "published":
                raise ValueError(f"规范「{label}」未发布，不能用于巡检业务")

    def _maybe_offline_on_content_change(
        self,
        before: dict[str, Any],
        *,
        name: str,
        desc: str,
        source: str,
        requirements: str,
        level: str,
        doc_id: str | None,
        status: str,
    ) -> None:
        changed = (
            before.get("name") != name
            or before.get("desc") != desc
            or before.get("source") != source
            or before.get("requirements") != requirements
            or before.get("level") != level
            or before.get("doc_id") != doc_id
            or (before.get("status") == "published" and status == "draft")
        )
        if changed:
            self._offline_works_for_rule(str(before["rule_id"]))

    def update_rule(
        self,
        rule_id: str,
        *,
        name: str | None = None,
        desc: str | None = None,
        source: str | None = None,
        requirements: str | None = None,
        level: str | None = None,
        doc_id: str | None = None,
        status: str | None = None,
        recommended_algorithms: list[str] | None = None,
        recommended_regions: list[str] | None = None,
        algorithm_reasoning: str | None = None,
        region_reasoning: str | None = None,
        source_trace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rec = self.get_rule(rule_id)
        nm = rec["name"] if name is None else name.strip()
        dc = rec["desc"] if desc is None else desc.strip()
        src = rec["source"] if source is None else source.strip()
        req = rec["requirements"] if requirements is None else requirements.strip()
        lv = rec["level"] if level is None else (level.strip() or rec["level"])
        did = rec["doc_id"] if doc_id is None else (doc_id.strip() or None)
        st = rec["status"] if status is None else status.strip()
        algos = (
            rec["recommended_algorithms"]
            if recommended_algorithms is None
            else [str(x).strip() for x in recommended_algorithms if str(x).strip()]
        )
        regions = (
            rec.get("recommended_regions") or []
            if recommended_regions is None
            else [str(x).strip() for x in recommended_regions if str(x).strip()]
        )
        ar = rec["algorithm_reasoning"] if algorithm_reasoning is None else algorithm_reasoning.strip()
        rr = rec.get("region_reasoning") or "" if region_reasoning is None else region_reasoning.strip()
        trace = dict(rec.get("source_trace") or {})
        if source_trace is not None:
            trace.update(source_trace)
        if did != rec.get("doc_id"):
            if did:
                from inspection_platform.document.service import DocumentService

                trace["doc_id"] = did
                try:
                    doc_rec = DocumentService().get_by_id(did)
                    trace["document_name"] = doc_rec.name
                except KeyError:
                    trace.pop("document_name", None)
            else:
                trace.pop("doc_id", None)
                trace.pop("document_name", None)
        elif did and not trace.get("doc_id"):
            trace["doc_id"] = did
        if not nm:
            raise ValueError("name cannot be empty")
        if st not in ("draft", "published"):
            raise ValueError("status must be draft or published")
        if st == "published" and rec["status"] != "published":
            raise ValueError(
                "不能通过 PATCH 将规范设为 published，请使用 POST /api/spec/rules/{rule_id}/publish"
            )

        self._maybe_offline_on_content_change(
            rec,
            name=nm,
            desc=dc,
            source=src,
            requirements=req,
            level=lv,
            doc_id=did,
            status=st,
        )

        preview = {
            **rec,
            "name": nm,
            "desc": dc,
            "source": src,
            "requirements": req,
            "level": lv,
            "doc_id": did,
            "status": st,
            "recommended_algorithms": algos,
            "recommended_regions": regions,
            "algorithm_reasoning": ar,
            "region_reasoning": rr,
            "source_trace": trace,
        }
        was_published = rec["status"] == "published"
        will_be_published = st == "published"

        if will_be_published:
            try:
                self._sync_rule_vector(preview)
            except Exception as e:
                raise ValueError(f"规则向量同步失败：{e}") from e

        now = _now()
        conn = get_connection()
        try:
            conn.execute(
                """
                UPDATE spec_rule SET
                    name=?, `desc`=?, source=?, level=?, requirements=?, doc_id=?, status=?,
                    recommended_algorithms_json=?, recommended_regions_json=?,
                    algorithm_reasoning=?, region_reasoning=?,
                    source_trace_json=?, updated_at=?
                WHERE rule_id = ?
                """,
                (
                    nm,
                    dc,
                    src,
                    lv,
                    req,
                    did,
                    st,
                    json.dumps(algos, ensure_ascii=False),
                    json.dumps(regions, ensure_ascii=False),
                    ar,
                    rr,
                    json.dumps(trace, ensure_ascii=False),
                    now,
                    rule_id.strip(),
                ),
            )
            conn.commit()
        except Exception as e:
            if will_be_published and was_published:
                try:
                    self._sync_rule_vector(rec)
                except Exception:
                    pass
            raise ValueError(f"规则更新失败：{e}") from e
        finally:
            conn.close()

        out = self.get_rule(rule_id)
        if was_published and out["status"] == "draft":
            self._delete_rule_vectors(self._rule_store(), rule_id.strip())
        elif will_be_published and not self._rule_vector_exists(rule_id.strip()):
            try:
                self._sync_rule_vector(out)
            except Exception as e:
                raise ValueError(f"规则已保存但向量校验失败：{e}") from e
        return out

    def _rule_vector_exists(self, rule_id: str) -> bool:
        return self._rule_store().count_by_filters({"rule_id": rule_id.strip()}) > 0

    def publish_rule(self, rule_id: str) -> dict[str, Any]:
        readiness = self.publish_readiness(rule_id)
        if not readiness["ready"]:
            failed = [c["message"] for c in readiness["checks"] if not c["ok"]]
            raise ValueError("发布就绪检查未通过：" + "；".join(failed))
        rec = self.get_rule(rule_id)
        if rec["status"] == "published":
            try:
                if not self._rule_vector_exists(rule_id.strip()):
                    self._sync_rule_vector(rec)
                elif not self.verify_published_vector_sync(rule_id):
                    self._sync_rule_vector(rec)
            except ValueError:
                raise
            except Exception as e:
                raise _vector_action_error(e, action="已发布规则向量同步") from e
            return self.get_rule(rule_id)

        rec_as_published = {**rec, "status": "published"}
        store = self._rule_store()
        rid = rule_id.strip()
        try:
            self._sync_rule_vector(rec_as_published)
        except ValueError:
            raise
        except Exception as e:
            self._safe_delete_rule_vectors(store, rid)
            raise _vector_action_error(e, action="发布") from e

        if not self._rule_vector_exists(rid):
            self._safe_delete_rule_vectors(store, rid)
            raise ValueError("发布失败：向量写入后校验未通过")

        now = _now()
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE spec_rule SET status = 'published', updated_at = ? WHERE rule_id = ?",
                (now, rid),
            )
            conn.commit()
        except Exception as e:
            self._safe_delete_rule_vectors(store, rid)
            raise ValueError(f"发布失败：状态写入未成功 — {e}") from e
        finally:
            conn.close()
        out = self.get_rule(rule_id)
        if not self.verify_published_vector_sync(rule_id):
            rollback_now = _now()
            conn = get_connection()
            try:
                conn.execute(
                    "UPDATE spec_rule SET status = 'draft', updated_at = ? WHERE rule_id = ?",
                    (rollback_now, rid),
                )
                conn.commit()
            finally:
                conn.close()
            self._safe_delete_rule_vectors(store, rid)
            raise ValueError("发布失败：规则状态与向量库不一致，请重试或使用 rebuild-vectors")
        return out

    def verify_published_vector_sync(self, rule_id: str) -> bool:
        """校验已发布规则在 Milvus 中是否存在且 metadata.status=published。"""
        rid = rule_id.strip()
        if not rid:
            return False
        rec = self.get_rule(rid)
        if rec.get("status") != "published":
            return True
        n = self._rule_store().count_by_filters({"rule_id": rid, "status": "published"})
        return n > 0

    def _sync_rule_vector(self, rec: dict[str, Any]) -> None:
        rid = rec["rule_id"]
        embed_text = build_rule_embed_text(rec)
        if not embed_text.strip():
            raise ValueError("无法构建规则索引文本；请填写标题及场景或要求")
        req_full = (rec.get("requirements") or "").strip()
        store = self._rule_store()
        self._delete_rule_vectors(store, rid)
        try:
            vec = platform_embed_texts(
                [embed_text],
                model_name=self._emb_name,
                metadata={"stage": "spec_rule_sync", "rule_id": rid},
            )[0]
        except Exception as e:
            raise ValueError(f"规则向量化失败：{e}") from e
        trace = rec.get("source_trace") or {}
        doc_id = (rec.get("doc_id") or trace.get("doc_id") or "").strip()
        meta = {
            "chunk_id": rid,
            "rule_id": rid,
            "name": rec["name"],
            "level": rec["level"],
            "status": rec["status"],
            "doc_id": doc_id,
            "source_doc_id": doc_id,
            "document_name": str(trace.get("document_name") or trace.get("name") or ""),
            "kb_id": str(trace.get("kb_id") or "default"),
            "source_trace_json": json.dumps(trace, ensure_ascii=False),
            "requirements_preview": requirements_preview(req_full),
            "desc_preview": (rec.get("desc") or "").strip()[:500],
        }
        chunk = EmbeddedChunk(
            chunk_id=rid,
            text=embed_text,
            vector=list(map(float, vec)),
            meta=meta,
        )
        store.add_embedded_chunks([chunk])

    def rebuild_published_vectors(self) -> dict[str, Any]:
        """按当前索引模板重建全部已发布规则向量。"""
        rules = self.list_rules(status="published")
        rebuilt = 0
        failed: list[dict[str, str]] = []
        for rec in rules:
            rid = str(rec.get("rule_id") or "")
            try:
                self._sync_rule_vector(rec)
                rebuilt += 1
            except Exception as e:
                failed.append({"rule_id": rid, "error": str(e)})
        return {"total": len(rules), "rebuilt": rebuilt, "failed": failed}

    def _works_referencing_rule(self, rule_id: str) -> int:
        from inspection_platform.inspection_work.service import InspectionWorkService

        rid = rule_id.strip()
        if not rid:
            return 0
        svc = InspectionWorkService()
        svc.ensure_ready()
        count = 0
        offset = 0
        limit = 500
        while True:
            items, total = svc.list_all(limit=limit, offset=offset)
            for w in items:
                rule_set = w.get("rule_set") or []
                refs = {str(r.get("rule_id") or "").strip() for r in rule_set}
                if rid in refs:
                    count += 1
            offset += limit
            if offset >= total:
                break
        return count

    def delete_rule(self, rule_id: str) -> None:
        rid = rule_id.strip()
        rec = self.get_rule(rid)
        work_count = self._works_referencing_rule(rid)
        if work_count > 0:
            label = rec.get("name") or rid
            raise ValueError(
                f"规范「{label}」已被 {work_count} 条巡检业务引用，无法删除"
            )
        store = self._rule_store()
        self._delete_rule_vectors(store, rid)
        conn = get_connection()
        try:
            conn.execute("DELETE FROM spec_rule WHERE rule_id = ?", (rid,))
            conn.commit()
        finally:
            conn.close()

    def query_rules(
        self,
        *,
        query: str,
        top_k: int = 5,
        candidate_k: int | None = None,
    ) -> list[dict[str, Any]]:
        q = query.strip()
        if not q:
            raise ValueError("query is empty")
        try:
            qv = platform_embed_texts(
                [q],
                model_name=self._emb_name,
                metadata={"stage": "spec_rule_query"},
            )[0]
        except Exception as e:
            raise ValueError(f"规则检索向量化失败：{e}") from e
        store = self._rule_store()
        k = max(int(top_k), 1)
        cand = max(k, int(candidate_k)) if candidate_k is not None else k
        pairs = store.query_similar_chunks(
            list(map(float, qv)),
            top_k=k,
            candidate_k=cand,
            filters={"status": "published"},
        )
        out: list[dict[str, Any]] = []
        for score, ch in pairs:
            meta = dict(ch.meta or {})
            rid = str(meta.get("rule_id") or meta.get("chunk_id") or "").strip()
            hit: dict[str, Any] = {
                "score": score,
                "text": ch.text,
                "meta": meta,
            }
            if rid:
                try:
                    rule = self.get_rule(rid)
                    hit["rule"] = {
                        "rule_id": rule["rule_id"],
                        "name": rule["name"],
                        "desc": rule["desc"],
                        "requirements": rule["requirements"],
                        "level": rule["level"],
                        "doc_id": rule.get("doc_id"),
                        "status": rule["status"],
                        "source_trace": rule.get("source_trace") or {},
                    }
                except KeyError:
                    hit["rule"] = None
            else:
                hit["rule"] = None
            out.append(hit)
        return out

    def stats(self) -> dict[str, Any]:
        from inspection_platform.app.config import get_settings

        s = get_settings()
        return {
            "rule_chunks": self._rule_store().chunk_count,
            "vector_backend": "milvus",
            "milvus_uri": f"http://{s.milvus_host}:{s.milvus_port}",
            "sqlite_path": str(spec_db_path()),
        }
