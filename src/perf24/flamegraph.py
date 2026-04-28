from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import html


@dataclass(slots=True)
class Node:
    name: str
    value: int = 0
    children: dict[str, "Node"] = field(default_factory=dict)


def render_flamegraph_svg(
    stacks: Counter[tuple[str, ...]],
    title: str,
    subtitle: str = "",
    width: int = 1600,
    frame_height: int = 18,
    min_frame_width: float = 0.1,
) -> str:
    root = _build_tree(stacks)
    max_depth = _max_depth(root)
    header_height = 48
    margin = 10
    body_width = max(width - 2 * margin, 200)
    body_height = max(max_depth * frame_height, frame_height)
    svg_height = header_height + body_height + margin * 2
    total = max(root.value, 1)
    scale = body_width / total

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{svg_height}" viewBox="0 0 {width} {svg_height}">',
        "<style>",
        "text { font-family: Verdana, sans-serif; fill: #111827; }",
        ".title { font-size: 20px; font-weight: bold; }",
        ".subtitle { font-size: 12px; fill: #4b5563; }",
        ".frame { stroke: #7c2d12; stroke-width: 0.35; }",
        ".label { font-size: 12px; pointer-events: none; }",
        "</style>",
        f'<text class="title" x="{margin}" y="24">{html.escape(title)}</text>',
        f'<text class="subtitle" x="{margin}" y="40">{html.escape(subtitle)}</text>',
    ]

    x = margin
    for child in _sorted_children(root):
        child_width = child.value * scale
        _render_node(
            parts,
            node=child,
            x=x,
            depth=0,
            scale=scale,
            frame_height=frame_height,
            header_height=header_height,
            max_depth=max_depth,
            total=total,
            min_frame_width=min_frame_width,
        )
        x += child_width

    parts.append("</svg>")
    return "\n".join(parts)


def _build_tree(stacks: Counter[tuple[str, ...]]) -> Node:
    root = Node(name="root")
    for stack, count in stacks.items():
        root.value += count
        node = root
        for frame in stack:
            child = node.children.get(frame)
            if child is None:
                child = node.children[frame] = Node(name=frame)
            child.value += count
            node = child
    return root


def _max_depth(node: Node) -> int:
    if not node.children:
        return 0
    return 1 + max(_max_depth(child) for child in node.children.values())


def _sorted_children(node: Node) -> list[Node]:
    return sorted(node.children.values(), key=lambda child: (-child.value, child.name))


def _render_node(
    parts: list[str],
    node: Node,
    x: float,
    depth: int,
    scale: float,
    frame_height: int,
    header_height: int,
    max_depth: int,
    total: int,
    min_frame_width: float,
) -> None:
    width = node.value * scale
    if width < min_frame_width:
        return
    y = header_height + (max_depth - depth - 1) * frame_height
    color = _color_for(node.name)
    pct = 100.0 * node.value / total if total else 0.0
    label = _fit_label(node.name, width)

    parts.append(
        f'<g><title>{html.escape(node.name)} ({node.value} samples, {pct:.2f}%)</title>'
        f'<rect class="frame" x="{x:.3f}" y="{y:.3f}" width="{width:.3f}" height="{frame_height - 1}" '
        f'fill="{color}" rx="2" ry="2"/>'
    )
    if label:
        parts.append(
            f'<text class="label" x="{x + 3:.3f}" y="{y + frame_height - 5:.3f}">{html.escape(label)}</text>'
        )
    parts.append("</g>")

    child_x = x
    for child in _sorted_children(node):
        child_width = child.value * scale
        _render_node(
            parts,
            node=child,
            x=child_x,
            depth=depth + 1,
            scale=scale,
            frame_height=frame_height,
            header_height=header_height,
            max_depth=max_depth,
            total=total,
            min_frame_width=min_frame_width,
        )
        child_x += child_width


def _fit_label(text: str, width: float) -> str:
    max_chars = int((width - 6) / 7.0)
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 2:
        return ""
    return text[: max_chars - 2] + ".."


def _color_for(name: str) -> str:
    digest = hashlib.md5(name.encode("utf-8")).digest()
    hue = digest[0] % 50
    sat = 55 + digest[1] % 20
    light = 60 + digest[2] % 15
    return _hsl_to_hex(hue, sat / 100.0, light / 100.0)


def _hsl_to_hex(hue_degrees: int, saturation: float, lightness: float) -> str:
    hue = hue_degrees / 360.0

    if saturation == 0.0:
        red = green = blue = lightness
    else:
        def hue_to_rgb(p: float, q: float, t: float) -> float:
            if t < 0:
                t += 1
            if t > 1:
                t -= 1
            if t < 1 / 6:
                return p + (q - p) * 6 * t
            if t < 1 / 2:
                return q
            if t < 2 / 3:
                return p + (q - p) * (2 / 3 - t) * 6
            return p

        q = lightness * (1 + saturation) if lightness < 0.5 else lightness + saturation - lightness * saturation
        p = 2 * lightness - q
        red = hue_to_rgb(p, q, hue + 1 / 3)
        green = hue_to_rgb(p, q, hue)
        blue = hue_to_rgb(p, q, hue - 1 / 3)

    return "#{:02x}{:02x}{:02x}".format(int(red * 255), int(green * 255), int(blue * 255))
