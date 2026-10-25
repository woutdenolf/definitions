"""Read and write the NXDS source form (YAML)."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ._report import Report
from .model import SourceClass
from .nxdl import CompiledClass

_CLASS_KEYS = (
    "nxds",
    "class",
    "category",
    "extends",
    "describes",
    "deprecated",
    "doc",
    "defaults",
    "symbols",
    "undeclared",
    "require",
    "attributes",
    "children",
    "via",
    "provisional",
)
_MEMBER_KEYS = (
    "id",
    "node",
    "name",
    "class",
    "occurs",
    "recommended",
    "type",
    "shape",
    "units",
    "enum",
    "length",
    "rank",
    "names_child",
    "refines",
    "target",
    "deprecated",
    "doc",
    "show",
    "undeclared",
    "require",
    "attributes",
    "children",
    "via",
    "provisional",
)


class _Dumper(yaml.SafeDumper):
    pass


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.Node:
    if "\n" in data:
        text = "\n".join(line.rstrip() for line in data.splitlines())
        return dumper.represent_scalar("tag:yaml.org,2002:str", text, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def _is_scalar(value: Any) -> bool:
    return (
        value is None
        or isinstance(value, (str, int, float, bool))
        and "\n" not in str(value)
    )


def _represent_list(dumper: yaml.SafeDumper, data: list) -> yaml.Node:
    flow = all(_is_scalar(v) for v in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


def _represent_dict(dumper: yaml.SafeDumper, data: dict) -> yaml.Node:
    flow = (
        len(data) <= 3
        and all(_is_scalar(v) for v in data.values())
        and all(len(str(v)) < 40 for v in data.values())
    )
    return dumper.represent_mapping(
        "tag:yaml.org,2002:map", data.items(), flow_style=flow
    )


_Dumper.add_representer(str, _represent_str)
_Dumper.add_representer(list, _represent_list)
_Dumper.add_representer(dict, _represent_dict)


def dump_source(source: SourceClass) -> str:
    """The source form as YAML, with shorthands and a canonical key order."""
    data = source.model_dump(by_alias=True, exclude_none=True, mode="json")
    return yaml.dump(
        _compact_class(data),
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        width=88,
    )


def write_source(source: SourceClass, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_source(source))


def load_source(path: Path, label: str, report: Report) -> CompiledClass | None:
    """Read a ``*.nxds.yaml`` file; problems go to the report."""
    try:
        text = path.read_text()
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        data = yaml.safe_load(text)
    except (OSError, yaml.YAMLError) as exc:
        report.error("yaml", f"cannot read: {exc}", label)
        return None
    if not isinstance(data, dict):
        report.error("yaml", "not a mapping", label)
        return None
    if "defaults" not in data:
        report.error("missing-defaults", "every class file states `defaults`", label)
    try:
        source = SourceClass.model_validate(data)
    except ValidationError as exc:
        for error in exc.errors():
            location = tuple(str(p) for p in error["loc"])
            report.error(
                "metaschema",
                f"{'.'.join(location)}: {error['msg']}",
                label,
                _line_of(node, error["loc"]),
            )
        return None
    stem = path.name.split(".")[0]
    if source.class_ != stem:
        report.error(
            "name-mismatch", f"class {source.class_!r} in file {stem!r}", label
        )
    lines: dict[tuple[str, ...], int] = {(): 1}
    _collect_lines(node, (), lines)
    return CompiledClass(source=source, file=label, lines=lines)


def _line_of(node: yaml.Node | None, loc: tuple) -> int | None:
    for key in loc:
        if not isinstance(node, yaml.MappingNode):
            break
        for key_node, value_node in node.value:
            if key_node.value == str(key):
                node = value_node
                break
        else:
            break
    return node.start_mark.line + 1 if node is not None else None


def _collect_lines(
    node: yaml.Node, path: tuple[str, ...], lines: dict[tuple[str, ...], int]
) -> None:
    """Map member id paths (attributes as ``@id``) to their lines."""
    if not isinstance(node, yaml.MappingNode):
        return
    for key_node, value_node in node.value:
        if key_node.value == "children" and isinstance(value_node, yaml.MappingNode):
            for member_key, member_node in value_node.value:
                member_path = (*path, member_key.value)
                lines[member_path] = member_key.start_mark.line + 1
                _collect_lines(member_node, member_path, lines)
        elif key_node.value == "attributes" and isinstance(
            value_node, yaml.MappingNode
        ):
            for member_key, _ in value_node.value:
                lines[(*path, "@" + member_key.value)] = member_key.start_mark.line + 1


def _ordered(data: dict, keys: tuple[str, ...]) -> dict:
    result = {k: data[k] for k in keys if k in data}
    result.update({k: v for k, v in data.items() if k not in result})
    return result


def _compact_class(data: dict) -> dict:
    data = _drop_empty(data)
    for section in ("children", "attributes"):
        if section in data:
            data[section] = {k: _compact_member(v) for k, v in data[section].items()}
    return _ordered(data, _CLASS_KEYS)


def _compact_member(data: dict) -> dict:
    data = _drop_empty(data)
    enum = data.get("enum")
    if (
        enum is not None
        and not enum.get("open")
        and all(set(v) == {"value"} for v in enum["values"])
    ):
        data["enum"] = [v["value"] for v in enum["values"]]
    elif enum is not None and not enum.get("open"):
        enum.pop("open", None)
    shape = data.get("shape")
    if shape is not None and set(shape) == {"dims"}:
        data["shape"] = shape["dims"]
    for section in ("children", "attributes"):
        if section in data:
            data[section] = {k: _compact_member(v) for k, v in data[section].items()}
    return _ordered(data, _MEMBER_KEYS)


def _drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v not in ({}, [], None)}
