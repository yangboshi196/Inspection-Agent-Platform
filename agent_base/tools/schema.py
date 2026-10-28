"""将 `ToolSpec.input_schema` 转为 OpenAI function calling 所需的 `parameters` JSON Schema。"""

from __future__ import annotations

from typing import Any


def tool_parameters_from_input_schema(input_schema: dict[str, Any] | None) -> dict[str, Any]:
    """把工具入参描述转成 `function.parameters`（JSON Schema object）。

    - `None`：空 object（无属性，仍合法）。
    - 已是 `{"type":"object","properties":...}` 形态：原样返回（可带 `required`）。
    - 否则按「字段名 → 类型提示字符串」的简写表解析，例如 `{"expr": "string"}`。
    """
    if not input_schema:
        return {"type": "object", "properties": {}}

    if input_schema.get("type") == "object" and isinstance(input_schema.get("properties"), dict):
        out: dict[str, Any] = {
            "type": "object",
            "properties": dict(input_schema["properties"]),
        }
        req = input_schema.get("required")
        if isinstance(req, list) and all(isinstance(x, str) for x in req):
            out["required"] = list(req)
        return out

    properties: dict[str, Any] = {}
    for key, hint in input_schema.items():
        if not isinstance(key, str):
            continue
        if isinstance(hint, dict):
            properties[key] = hint
            continue
        hint_s = str(hint).lower() if hint is not None else "string"
        json_type = "string"
        if "int" in hint_s and "point" not in hint_s:
            json_type = "integer"
        elif "number" in hint_s or "float" in hint_s or "double" in hint_s:
            json_type = "number"
        elif "bool" in hint_s:
            json_type = "boolean"
        elif "object" in hint_s or "dict" in hint_s:
            json_type = "object"
        elif "array" in hint_s or "list" in hint_s:
            json_type = "array"
        properties[key] = {"type": json_type, "description": str(hint)}

    return {"type": "object", "properties": properties}
