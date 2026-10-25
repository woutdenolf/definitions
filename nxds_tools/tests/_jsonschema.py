"""A small JSON Schema checker for the keywords the NXDS metaschema uses.

The tests may not depend on the ``jsonschema`` package; this covers ``$ref``
(local), ``type``, ``properties``, ``required``, ``additionalProperties``,
``unevaluatedProperties: false``, ``items``, ``enum``, ``const``, ``oneOf``,
``anyOf``, ``allOf``, ``minimum``, ``minItems`` and ``pattern``.
"""

import re
from typing import Any

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def errors(schema: dict, value: Any) -> list[str]:
    """The ways ``value`` violates ``schema`` (empty: valid)."""
    return _check(schema, schema, value, "")


def _resolve(root: dict, schema: dict) -> dict:
    while "$ref" in schema:
        node: Any = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        schema = {**node, **{k: v for k, v in schema.items() if k != "$ref"}}
    return schema


def _names(root: dict, schema: dict) -> set[str]:
    """Property names a schema evaluates (for ``unevaluatedProperties``)."""
    schema = _resolve(root, schema)
    names = set(schema.get("properties", {}))
    for sub in schema.get("allOf", []):
        names |= _names(root, sub)
    return names


def _check(root: dict, schema: Any, value: Any, where: str) -> list[str]:
    if schema is True or schema == {}:
        return []
    if schema is False:
        return [f"{where}: not allowed"]
    schema = _resolve(root, schema)
    found: list[str] = []
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[t](value) for t in types):
            return [f"{where}: {value!r} is not {types}"]
    if "const" in schema and value != schema["const"]:
        found.append(f"{where}: {value!r} is not {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        found.append(f"{where}: {value!r} not in {schema['enum']}")
    if "minimum" in schema and _TYPES["number"](value) and value < schema["minimum"]:
        found.append(f"{where}: {value} < {schema['minimum']}")
    if "pattern" in schema and isinstance(value, str):
        if re.search(schema["pattern"], value) is None:
            found.append(f"{where}: {value!r} does not match {schema['pattern']}")
    for sub in schema.get("allOf", []):
        found += _check(root, sub, value, where)
    if "anyOf" in schema:
        if all(_check(root, s, value, where) for s in schema["anyOf"]):
            found.append(f"{where}: matches none of anyOf")
    if "oneOf" in schema:
        matching = sum(1 for s in schema["oneOf"] if not _check(root, s, value, where))
        if matching != 1:
            found.append(f"{where}: matches {matching} of oneOf")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            found.append(f"{where}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for index, item in enumerate(value):
                found += _check(root, schema["items"], item, f"{where}[{index}]")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                found.append(f"{where}: {key!r} is required")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                found += _check(root, properties[key], item, f"{where}/{key}")
            elif "additionalProperties" in schema:
                found += _check(
                    root, schema["additionalProperties"], item, f"{where}/{key}"
                )
        if schema.get("unevaluatedProperties") is False:
            extra = set(value) - _names(root, schema)
            if extra:
                found.append(f"{where}: unexpected {sorted(extra)}")
    return found
