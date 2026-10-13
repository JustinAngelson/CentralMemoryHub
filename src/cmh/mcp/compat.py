"""Schemas retain all v1 fields; immutable inventory is shipped as package data."""

import json
from importlib.resources import files
from typing import Any

from mcp.types import CallToolResult, TextContent
from pydantic import ConfigDict, Field, create_model

from cmh.auth.context import current_context
from cmh.mcp.compat_formats import format_success
from cmh.policy.evaluator import deny, evaluate

TYPE_MAP = {
    "str": str, "int": int, "bool": bool, "List[str]": list[str],
    "List[float]": list[float], "Optional[str]": str | None, "Optional[int]": int | None,
    "Optional[bool]": bool | None, "Optional[List[str]]": list[str] | None,
    "Optional[Dict[str, str]]": dict[str, str] | None,
}
EXTRAS = {"namespace": (str | None, None), "source_type": (Any, None),
          "source_ref": (Any, None), "confidence": (Any, None), "occurred_at": (Any, None)}


def error_result(body):
    return CallToolResult(isError=True, content=[
        TextContent(type="text", text=json.dumps(body, default=str)),
    ], structuredContent=body)


def register_compat_tools(server, service):
    inventory = json.loads(files("cmh.mcp").joinpath("v1_inventory.json").read_text())
    definitions = {item["name"]: item for item in inventory["tools"]}
    for name, definition in definitions.items():
        if name in ("cmh_store_memory", "cmh_get_memory", "cmh_search_memory"):
            continue
        fields = {field["name"]: (TYPE_MAP[field["type"]], Field(
            ... if field["required"] else field.get("default"), **field.get("constraints", {}),
        )) for field in definition["fields"]}
        fields.update({key: value for key, value in EXTRAS.items() if key not in fields})
        model = create_model(
            definition.get("input_model") or "NoArguments",
            __config__=ConfigDict(extra="ignore", str_strip_whitespace=True,
                                 hide_input_in_errors=True, allow_inf_nan=False), **fields,
        )

        def factory(tool_name, input_model, has_arguments):
            def execute(payload):
                value = service.call(current_context.get(), tool_name, payload)
                if isinstance(value, dict) and value.get("outcome") == "DENY":
                    return error_result(value)
                return CallToolResult(content=[
                    TextContent(type="text", text=format_success(tool_name, value)),
                ])

            if has_arguments:
                def tool(params):
                    payload = params.model_dump(exclude_unset=True)
                    # Non-null legacy defaults are runtime behavior, not only schema decoration.
                    for field, definition in params.__class__.model_fields.items():
                        if field not in payload and field not in EXTRAS and (
                            definition.default is not None and not definition.is_required()
                        ):
                            payload[field] = definition.default
                    return execute(payload)
                tool.__annotations__ = {"params": input_model, "return": CallToolResult}
            else:
                def tool():
                    return execute({})
                tool.__annotations__ = {"return": CallToolResult}
            tool.__name__ = tool_name
            tool.__doc__ = "v1-compatible tool; attribution, authorization and audit use the caller."
            return tool

        server.tool(name=name)(factory(name, model, bool(definition["arguments"])))

    original = server.call_tool

    async def audited_dispatch(name, arguments):
        context = current_context.get()
        if name == "cmh_register_agent":
            return error_result(service.register_denial(context))
        if name in definitions and name != "cmh_health_check":
            with service.entities.engine.connect() as conn:
                permission = evaluate(conn, context, service.scope(name))
            if permission["outcome"] != "ALLOW":
                return error_result(service.identity.record(
                    context, permission, service.scope(name),
                ))
        try:
            return await original(name, arguments or {})
        except Exception as error:
            # FastMCP wraps Pydantic errors in ToolError. Do not log/return its input-bearing text.
            from mcp.server.fastmcp.exceptions import ToolError
            from pydantic import ValidationError

            cause = error
            while cause is not None:
                if isinstance(cause, ValidationError):
                    return error_result(service.identity.record(
                        context, deny("VALIDATION_FAILED", 7), service.scope(name),
                    ))
                cause = cause.__cause__
            if isinstance(error, ToolError) and name in definitions:
                raise
            raise

    server.call_tool = audited_dispatch
    # SDK JSON-schema validation otherwise rejects null argumentless envelopes
    # and legacy register shapes before policy/audit. FastMCP's Pydantic models
    # still validate every enabled tool after our scope/tier decision.
    server._mcp_server.call_tool(validate_input=False)(audited_dispatch)
