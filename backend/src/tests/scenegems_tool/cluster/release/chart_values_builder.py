"""A reference builder of a cluster's chart values file from release.json and the cluster's members.

It follows the rules in the docstring of scenegems_tool/cluster/release/roles.py, step by step, as the deployment
tool (Machine Hub) is to follow them: it reads release.json as plain JSON and knows nothing of SceneGEMS, so it
is an executable example for the tool and lets the tests check that the roles give the values the chart expects.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Set

PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
VALUES_PLACEHOLDERS = {"cluster", "name", "node", "machine.name", "release.revision"}
CHART_VALUES_PLACEHOLDERS = {"cluster", "release.revision"}
PARAMETER_KEY = "$parameter"
_INTEGER = re.compile(r"[+-]?[0-9]+")
_NUMBER = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)")


class ValuesError(ValueError):
    """The values file cannot be built: the message names the member, the parameter or the path."""


@dataclass(frozen=True)
class Member:
    """A role on a Kubernetes node: its instance name, the node, the node's machine and the operator's parameter values (text)."""

    role: str
    name: str
    node: str
    machine: str
    parameters: Mapping[str, str] = field(default_factory=dict)


def render(text: str, context: Mapping[str, str], where: str) -> str:
    def replace(match: "re.Match[str]") -> str:
        if match.group(1) not in context:
            raise ValuesError(f"{where}: no value for {{{match.group(1)}}} in {text!r}")
        return context[match.group(1)]

    return PLACEHOLDER.sub(replace, text)


def render_template(template: Any, context: Mapping[str, str], where: str) -> Any:
    """Text rendered, lists item by item, objects key by key; numbers, booleans and null as they are. No $parameter here."""
    if isinstance(template, str):
        return render(template, context, where)
    if isinstance(template, list):
        return [render_template(item, context, where) for item in template]
    if isinstance(template, dict):
        return {key: render_template(value, context, where) for key, value in template.items()}
    return template


def member_context(release: Mapping[str, Any], cluster: str, member: Member) -> Dict[str, str]:
    return {"cluster": cluster, "name": member.name, "node": member.node, "machine.name": member.machine, "release.revision": release["revision"]}


def parameter_values(role: Mapping[str, Any], member: Member, context: Mapping[str, str]) -> Dict[str, str]:
    """The member's value of every parameter of its role, its own or the default, rendered."""
    parameters = role["parameters"]
    unknown = sorted(set(member.parameters) - set(parameters))
    if unknown:
        raise ValuesError(f"{member.role} {member.name}: no parameter {', '.join(unknown)}")
    return {key: render(member.parameters.get(key, parameter["default"]), context, f"{member.role} {member.name} {key}") for key, parameter in parameters.items()}


def _scalar(text: str, value_type: str, where: str) -> Any:
    if value_type == "text":
        return text
    if value_type == "integer" and _INTEGER.fullmatch(text):
        return int(text)
    if value_type == "number" and _NUMBER.fullmatch(text):
        return int(text) if _INTEGER.fullmatch(text) else float(text)
    raise ValuesError(f"{where}: {text!r} is not of type {value_type}")


def convert(spec: Mapping[str, Any], values: Mapping[str, str], where: str) -> Any:
    """A $parameter object: the parameter's value as one value of the type, a list of them, or an object of key to one of them."""
    key = spec[PARAMETER_KEY]
    if key not in values:
        raise ValuesError(f"{where}: the role has no parameter {key}")
    where = f"{where} {key}"
    value_type = spec.get("type", "text")
    if "split" not in spec:
        return _scalar(values[key].strip(), value_type, where)
    parts = [part.strip() for part in values[key].split(spec["split"]) if part.strip()]
    if "pair" not in spec:
        return [_scalar(part, value_type, where) for part in parts]
    paired: Dict[str, Any] = {}
    for part in parts:
        name, separator, text = part.partition(spec["pair"])
        name = name.strip()
        if not separator or not name:
            raise ValuesError(f"{where}: {part!r} must read <key>{spec['pair']}<value>")
        if name in paired:
            raise ValuesError(f"{where}: {name} is listed twice")
        paired[name] = _scalar(text.strip(), value_type, where)
    return paired


def render_entry(template: Any, context: Mapping[str, str], values: Mapping[str, str], where: str) -> Any:
    if isinstance(template, str):
        return render(template, context, where)
    if isinstance(template, list):
        return [render_entry(item, context, values, where) for item in template]
    if isinstance(template, dict):
        if PARAMETER_KEY in template:
            return convert(template, values, where)
        return {key: render_entry(value, context, values, where) for key, value in template.items()}
    return template


def member_entry(release: Mapping[str, Any], cluster: str, member: Member) -> Any:
    """The values the member gives: its role's entry rendered for it."""
    role = release["roles"][member.role]
    context = member_context(release, cluster, member)
    return render_entry(role["values"]["entry"], context, parameter_values(role, member, context), f"{member.role} {member.name}")


def member_images(release: Mapping[str, Any], cluster: str, member: Member) -> Set[str]:
    """The images the member needs: its role's, and those of the items its list parameters name (as for compose)."""
    role = release["roles"][member.role]
    values = parameter_values(role, member, member_context(release, cluster, member))
    images = set(role["images"])
    for key, parameter in role["parameters"].items():
        items = parameter.get("items")
        if not items:
            continue
        for part in (part.strip() for part in values[key].split(items["separator"])):
            if not part:
                continue
            item = part.split(items["key_separator"], 1)[0].strip() if items.get("key_separator") else part
            if items.get("images") and item not in items["images"]:
                raise ValuesError(f"{member.role} {member.name} {key}: unknown item {item}")
            images.update(items.get("images", {}).get(item, []))
    return images


def needed_images(release: Mapping[str, Any], cluster: str, members: Iterable[Member]) -> Set[str]:
    """The images the tool pushes for the cluster."""
    return {image for member in members for image in member_images(release, cluster, member)}


def at_path(path: str, value: Any) -> Dict[str, Any]:
    keys = path.split(".")
    for key in reversed(keys[1:]):
        value = {key: value}
    return {keys[0]: value}


def merge(target: Dict[str, Any], source: Mapping[str, Any], where: str = "") -> None:
    """Objects merge key by key; a path set twice must get equal values."""
    for key, value in source.items():
        path = f"{where}.{key}" if where else key
        if isinstance(target.get(key), dict) and isinstance(value, dict):
            merge(target[key], value, path)
        elif key in target and target[key] != value:
            raise ValuesError(f"{path} is set to both {target[key]!r} and {value!r}")
        else:
            target[key] = value


def build_values(release: Mapping[str, Any], cluster: str, members: Iterable[Member], pushed: Mapping[str, str]) -> Dict[str, Any]:
    """The values file of a cluster: the chart's values, each role's values per member, and the reference of every image pushed for it.

    pushed maps an image tag of the release to the reference the tool pushed it as (registry/repository@sha256:<digest>);
    it must hold every image the members need.
    """
    members = list(members)
    unknown = sorted({member.role for member in members} - set(release["roles"]))
    if unknown:
        raise ValuesError(f"the release has no role {', '.join(unknown)}")
    values: Dict[str, Any] = render_template(release["chart"]["values"], {"cluster": cluster, "release.revision": release["revision"]}, "chart values")
    for role_name, role in release["roles"].items():
        of_role = sorted((member for member in members if member.role == role_name), key=lambda member: member.name)
        path = role["values"]["path"]
        if role["count"] == "many":
            merge(values, at_path(path, [member_entry(release, cluster, member) for member in of_role]))
        elif len(of_role) > 1:
            raise ValuesError(f"a cluster has one {role_name}")
        elif of_role:
            merge(values, at_path(path, member_entry(release, cluster, of_role[0])))
    for member in members:
        image_values = release["roles"][member.role]["image_values"]
        for image in sorted(member_images(release, cluster, member)):
            if image not in pushed:
                raise ValuesError(f"{member.role} {member.name} needs {image}, which was not pushed")
            merge(values, at_path(image_values[image], pushed[image]))
    return values


def placeholders(template: Any) -> List[str]:
    """Every placeholder a template's text uses."""
    if isinstance(template, str):
        return PLACEHOLDER.findall(template)
    if isinstance(template, list):
        return [name for item in template for name in placeholders(item)]
    if isinstance(template, dict):
        return [name for value in template.values() for name in placeholders(value)]
    return []
