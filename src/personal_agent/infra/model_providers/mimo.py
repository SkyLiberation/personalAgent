"""MiMo thinking, native tool streaming and outbound object-reference projection."""

from copy import deepcopy
import re
from typing import Any

from langchain_core.utils.json_schema import dereference_refs

from personal_agent.kernel.model_provider import ChatModelCapabilities, ModelProviderConfigurationError

from .openai_compatible import ChatParameters, OpenAICompatiblePolicy

_LOCAL_DEFINITION = re.compile(r"#/(?:\$defs|definitions)/[A-Za-z0-9_.-]+\Z")
_SKIP_KEYS = ("$defs", "definitions", "const", "enum", "default", "examples")
_SCOPED_KEYS = frozenset({
    "$id", "id", "$anchor", "$dynamicRef", "$dynamicAnchor", "$recursiveRef", "$recursiveAnchor",
})


def _supports_inline(
    node: Any, root: dict[str, Any], seen: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(node, dict):
        if _SCOPED_KEYS.intersection(node):
            return False
        if "$ref" in node:
            ref = node["$ref"]
            if (len(node) != 1 or not isinstance(ref, str)
                    or not _LOCAL_DEFINITION.fullmatch(ref) or ref in seen):
                return False
            _, definitions, name = ref.split("/")
            target = root.get(definitions, {}).get(name)
            return isinstance(target, dict) and _supports_inline(target, root, seen | {ref})
        return all(
            _supports_inline(value, root, seen)
            for key, value in node.items() if key not in _SKIP_KEYS
        )
    if isinstance(node, list):
        return all(_supports_inline(value, root, seen) for value in node)
    return True


def _object_parameter(parameter: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    if "type" in parameter or not _supports_inline(parameter, schema):
        return parameter
    projected = dereference_refs(parameter, full_schema=schema, skip_keys=_SKIP_KEYS)
    if projected.get("type") == "object":
        return projected
    for keyword in ("oneOf", "anyOf"):
        branches = projected.get(keyword)
        if isinstance(branches, list) and branches and all(
            isinstance(x, dict) and x.get("type") == "object" for x in branches
        ):
            projected["type"] = "object"
            return projected
    return parameter


def _project_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected = deepcopy(tools)
    for tool in projected:
        function = tool.get("function")
        if tool.get("type") != "function" or not isinstance(function, dict):
            continue
        schema = function.get("parameters")
        if not isinstance(schema, dict) or _SCOPED_KEYS.intersection(schema):
            continue
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for name, parameter in tuple(properties.items()):
                if isinstance(parameter, dict):
                    properties[name] = _object_parameter(parameter, schema)
    return projected


class MiMoPolicy(OpenAICompatiblePolicy):
    def configure(self, request: ChatParameters) -> ChatModelCapabilities:
        thinking = request.thinking_mode()
        if thinking == "adaptive":
            raise ModelProviderConfigurationError("mimo thinking.type must be enabled or disabled")
        if request.reasoning_effort is not None:
            raise ModelProviderConfigurationError("MiMo Chat Completions does not expose reasoning_effort")
        return ChatModelCapabilities("max_completion_tokens", () if thinking == "disabled" else ("temperature", "top_p"))

    def prepare_tools(self, parameters: dict[str, Any], request: ChatParameters) -> None:
        if parameters.get("tools"):
            if parameters.get("tool_choice") == "none":
                raise ModelProviderConfigurationError("MiMo only supports tool_choice=auto; omit tools to forbid calls")
            parameters.update(stream=True, stream_options={"include_usage": True}, tool_choice="auto")
            parameters["tools"] = _project_tools(parameters["tools"])
