"""文档域业务异常。"""

from __future__ import annotations


class DocumentInUseError(ValueError):
    """文档仍被已发布规范引用，无法删除。"""

    def __init__(self, doc_id: str, rule_count: int) -> None:
        self.doc_id = doc_id
        self.rule_count = int(rule_count)
        super().__init__(
            f"文档 {doc_id} 已被 {self.rule_count} 条已发布规范引用，无法删除"
        )
