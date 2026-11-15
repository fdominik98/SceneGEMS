"""Small helpers to read generated SDF and parameter text in tests."""

import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple


def parse_sdf(text: str) -> ET.Element:
    """Root element of a generated SDF. The generators put whitespace before the XML declaration, which Gazebo accepts."""
    return ET.fromstring(text.strip())


def plugins(element: ET.Element, filename: str) -> List[ET.Element]:
    return [plugin for plugin in element.iter("plugin") if plugin.get("filename") == filename]


def child_float(element: ET.Element, tag: str) -> float:
    child = element.find(tag)
    assert child is not None and child.text is not None, f"<{tag}> missing in <{element.tag}>"
    return float(child.text)


def child_text(element: ET.Element, tag: str) -> str:
    child = element.find(tag)
    assert child is not None and child.text is not None, f"<{tag}> missing in <{element.tag}>"
    return child.text.strip()


def child_floats(element: ET.Element, tag: str) -> Tuple[float, ...]:
    """The numbers of a child that holds several, a pose or a size."""
    return tuple(float(value) for value in child_text(element, tag).split())


def names(element: ET.Element, tag: str) -> List[str]:
    """Names of every element of that tag below the given one (links, joints, collisions), in document order."""
    return [found.get("name", "") for found in element.iter(tag)]


def named(element: ET.Element, tag: str, name: str) -> ET.Element:
    """The one element of that tag and name below the given one."""
    found = [candidate for candidate in element.iter(tag) if candidate.get("name") == name]
    assert len(found) == 1, f'expected one <{tag} name="{name}">, found {len(found)}'
    return found[0]


def link(element: ET.Element, name: str) -> ET.Element:
    return named(element, "link", name)


def joint(element: ET.Element, name: str) -> ET.Element:
    return named(element, "joint", name)


def plugin_for(element: ET.Element, filename: str, tag: str, value: str) -> ET.Element:
    """The one plugin of that file whose child `tag` has the given text: the thruster system of a joint, the hydrodynamics of a link."""
    found = [plugin for plugin in plugins(element, filename) if plugin.find(tag) is not None and (plugin.find(tag).text or "").strip() == value]
    assert len(found) == 1, f"expected one {filename} plugin with <{tag}>{value}</{tag}>, found {len(found)}"
    return found[0]


def child_tags(element: ET.Element) -> List[str]:
    return [child.tag for child in element]


def parse_params(text: str) -> Dict[str, float]:
    """ArduPilot parameter file: one 'NAME<TAB>value' per line."""
    params = {}
    for line in text.splitlines():
        name, value = line.split("\t")
        params[name] = float(value)
    return params
