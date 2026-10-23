"""Layered auto-layout for Archi views: one horizontal band per ArchiMate layer, top to bottom.

Coordinates are absolute (the Open Exchange Format convention; Archi converts nested
bounds to relative on import).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Model, View
from .rules import Rules

W, H = 120, 55
GAP_X, GAP_Y = 30, 30
PAD, LABEL_H = 20, 25
MARGIN = 20
MAX_COLS = 6
ASPECT_ORDER = ["active", "behavior", "passive", "motivation", "composite", "other"]


@dataclass
class Placed:
    kind: str  # "group" | "element"
    ref: str  # layer key for groups, element id for elements
    label: str
    x: int
    y: int
    w: int
    h: int
    children: list["Placed"] = field(default_factory=list)


def layout_view(model: Model, view: View, members: list[str], rules: Rules) -> list[Placed]:
    fixed = [m for m in members if m in view.layout]
    auto = [m for m in members if m not in view.layout]
    placed: list[Placed] = []
    bottom = MARGIN
    for m in fixed:
        x, y, w, h = view.layout[m]
        placed.append(Placed("element", m, model.elements[m].name, x, y, w, h))
        bottom = max(bottom, y + h + GAP_Y * 2)
    if auto:
        placed += _layered(model, auto, rules, top=bottom if fixed else MARGIN)
    return placed


def _layered(model: Model, members: list[str], rules: Rules, top: int) -> list[Placed]:
    by_layer: dict[str, list[str]] = {}
    for m in members:
        by_layer.setdefault(rules.layer_of(model.elements[m].type), []).append(m)
    for layer, ids in by_layer.items():
        ids.sort(key=lambda i: ASPECT_ORDER.index(rules.aspect_of(model.elements[i].type)))

    cols = min(MAX_COLS, max(len(ids) for ids in by_layer.values()))
    band_w = 2 * PAD + cols * W + (cols - 1) * GAP_X
    groups: list[Placed] = []
    y = top
    for layer in rules.layer_order():
        ids = by_layer.get(layer)
        if not ids:
            continue
        rows = (len(ids) + MAX_COLS - 1) // MAX_COLS
        band_h = LABEL_H + PAD + rows * H + (rows - 1) * GAP_Y
        group = Placed("group", layer, rules.layers[layer]["label"], MARGIN, y, band_w, band_h)
        for index, element_id in enumerate(ids):
            row, col = divmod(index, MAX_COLS)
            group.children.append(
                Placed(
                    "element",
                    element_id,
                    model.elements[element_id].name,
                    MARGIN + PAD + col * (W + GAP_X),
                    y + LABEL_H + row * (H + GAP_Y),
                    W,
                    H,
                )
            )
        groups.append(group)
        y += band_h + GAP_Y
    return groups


def flatten(placed: list[Placed]) -> list[Placed]:
    out: list[Placed] = []
    for p in placed:
        out.append(p)
        out.extend(flatten(p.children))
    return out
