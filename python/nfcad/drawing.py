"""Overview drawings of workflow blocks (docs/plugin-api.md, "Block previews").

A plugin's :meth:`nfcad.Plugin.preview_block` returns ``{"ok": True, "drawing": d.to_json()}``
with a :class:`Drawing`: a dependency-free 2-D vector drawing (format "nfcad-drawing", version 1)
that CAD draws in the tab "Overview" of the block's parameter dialog – scaled to the tab, in
the colours of the light or dark palette, with a legend of the materials. Coordinates are in
``unit`` (e.g. "mm", "µm") with y up; ``aspect="equal"`` keeps one scale for both axes.

Items: filled polygons (``material`` names the legend entry and the colour), polylines,
texts, dimensions (a double arrow with its value) and arrows (light, directions). ``role``
gives lines their meaning and colour in CAD: "outline" (default), "surface", "axis", "ray",
"light", "stop", "detector", "dimension", "guide", "note", "error". Only plain Python numbers
and strings – no NumPy needed (NumPy scalars are converted).
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

FORMAT = "nfcad-drawing"
VERSION = 1
ROLES = ("outline", "surface", "axis", "ray", "light", "stop", "detector", "dimension", "guide", "note", "error")

Point = Sequence[float]


def _point(p: Point) -> list[float]:
    x, y = float(p[0]), float(p[1])
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError(f"a drawing point must be finite, not {p!r}")
    return [x, y]


class Drawing:
    """Collects the items of one drawing; :meth:`to_json` gives what CAD reads."""

    def __init__(self, title: str = "", *, unit: str = "mm", axes: tuple[str, str] | None = ("z", "y"),
                 aspect: str = "equal"):
        if aspect not in ("equal", "fit"):
            raise ValueError("aspect must be 'equal' or 'fit'")
        self.title = title
        self.unit = unit
        self.axes = axes
        self.aspect = aspect
        self.items: list[dict[str, Any]] = []
        self.materials: dict[str, dict[str, Any]] = {}
        self.notes: list[str] = []

    # ------------------------------------------------------------------ items
    def polygon(self, points: Iterable[Point], *, material: str = "", label: str = "", fill: str = "",
                hatched: bool = False, role: str = "") -> dict:
        """A closed, filled polygon (at least 3 points); ``material`` colours it and lists it in the
        legend, ``fill`` ("#rrggbb" or "#aarrggbb") overrides the colour."""
        item: dict[str, Any] = {"type": "polygon", "points": [_point(p) for p in points]}
        if len(item["points"]) < 3:
            raise ValueError("a polygon needs at least 3 points")
        if material:
            item["material"] = material
            self.materials.setdefault(material, {"name": material})
        for key, value in (("text", label), ("fill", fill), ("role", role)):
            if value:
                item[key] = value
        if hatched:
            item["hatched"] = True
        return self._add(item)

    def polyline(self, points: Iterable[Point], *, role: str = "outline", dashed: bool = False,
                 width: float = 0.0, color: str = "", label: str = "") -> dict:
        item: dict[str, Any] = {"type": "polyline", "points": [_point(p) for p in points], "role": role}
        if len(item["points"]) < 2:
            raise ValueError("a polyline needs at least 2 points")
        if dashed:
            item["dashed"] = True
        if width:
            item["width"] = float(width)
        if color:
            item["color"] = color
        if label:
            item["text"] = label
        return self._add(item)

    def text(self, at: Point, text: str, *, align: str = "center", valign: str = "middle", role: str = "",
             color: str = "") -> dict:
        """A text at a point of the drawing (fixed size on screen); ``align`` "left" starts it at
        the point, "right" ends it there."""
        item: dict[str, Any] = {"type": "text", "at": _point(at), "text": str(text)}
        if align != "center":
            item["align"] = align
        if valign != "middle":
            item["valign"] = valign
        if role:
            item["role"] = role
        if color:
            item["color"] = color
        return self._add(item)

    def dimension(self, start: Point, end: Point, text: str = "", *, role: str = "dimension") -> dict:
        """A dimension line with arrows at both ends and its value; draw it beside the part (the
        helper :meth:`extension` draws thin lines from the part to it)."""
        return self._add({"type": "dimension", "from": _point(start), "to": _point(end), "text": str(text),
                          "role": role})

    def extension(self, start: Point, end: Point) -> dict:
        """A thin dotted line from a part to its dimension line."""
        return self.polyline([start, end], role="guide")

    def arrow(self, start: Point, end: Point, text: str = "", *, role: str = "light", dashed: bool = False,
              align: str = "left", valign: str = "bottom") -> dict:
        """An arrow from `start` to `end`; its text at the start ("left": beginning there)."""
        item: dict[str, Any] = {"type": "arrow", "from": _point(start), "to": _point(end), "role": role}
        if text:
            item["text"] = str(text)
            if align != "left":
                item["align"] = align
            if valign != "bottom":
                item["valign"] = valign
        if dashed:
            item["dashed"] = True
        return self._add(item)

    def material(self, name: str, label: str = "", fill: str = "") -> None:
        """The legend entry of a material (e.g. "N-BK7 · n = 1.5168"); polygons add theirs."""
        entry = self.materials.setdefault(name, {"name": name})
        if label:
            entry["label"] = label
        if fill:
            entry["fill"] = fill

    def note(self, text: str) -> None:
        """A line under the drawing."""
        self.notes.append(str(text))

    def _add(self, item: dict) -> dict:
        role = item.get("role")
        if role and role not in ROLES:
            raise ValueError(f"unknown role {role!r} (one of {', '.join(ROLES)})")
        self.items.append(item)
        return item

    # ------------------------------------------------------------------ output
    def bounds(self) -> tuple[float, float, float, float] | None:
        """(x0, y0, x1, y1) of all items, None without items."""
        xs: list[float] = []
        ys: list[float] = []
        for item in self.items:
            for p in item.get("points") or [item[k] for k in ("at", "from", "to") if k in item]:
                xs.append(p[0])
                ys.append(p[1])
        return (min(xs), min(ys), max(xs), max(ys)) if xs else None

    def to_json(self) -> dict:
        out: dict[str, Any] = {"format": FORMAT, "version": VERSION, "title": self.title, "unit": self.unit,
                               "aspect": self.aspect, "items": self.items,
                               "materials": list(self.materials.values()), "notes": self.notes}
        out["axes"] = list(self.axes) if self.axes else False
        return out


def answer(drawing: Drawing) -> dict:
    """The answer of ``preview_block`` with a drawing."""
    return {"ok": True, "drawing": drawing.to_json()}


def unsupported(why: str = "") -> dict:
    """The answer of ``preview_block`` for a block type the plugin does not draw: CAD asks the next
    plugin or shows the block's schematic."""
    return {"ok": False, "unsupported": True, "error": why or "no overview drawing for this block type"}


def check(d: dict) -> list[str]:
    """What CAD would refuse in a drawing's JSON (empty: fine) – for the plugins' tests."""
    problems: list[str] = []
    if d.get("format", FORMAT) != FORMAT:
        problems.append(f"format {d.get('format')!r}")
    if not isinstance(d.get("items"), list):
        return problems + ["no items array"]
    if d.get("aspect", "equal") not in ("equal", "fit"):
        problems.append(f"aspect {d.get('aspect')!r}")

    def finite_point(p: Any) -> bool:
        return (isinstance(p, (list, tuple)) and len(p) == 2
                and all(isinstance(v, (int, float)) and math.isfinite(v) for v in p))

    for k, item in enumerate(d["items"]):
        kind = item.get("type")
        if kind in ("polygon", "polyline"):
            pts = item.get("points")
            if not isinstance(pts, list) or not all(finite_point(p) for p in pts):
                problems.append(f"item {k}: points")
            elif len(pts) < (3 if kind == "polygon" else 2):
                problems.append(f"item {k}: too few points")
        elif kind == "text":
            if not finite_point(item.get("at")) or not isinstance(item.get("text"), str):
                problems.append(f"item {k}: text")
        elif kind in ("dimension", "arrow"):
            if not finite_point(item.get("from")) or not finite_point(item.get("to")):
                problems.append(f"item {k}: from/to")
        else:
            problems.append(f"item {k}: unknown type {kind!r}")
    return problems


def fmt(value: float, digits: int = 4) -> str:
    """A number for a label: up to `digits` significant digits, no trailing zeros."""
    v = float(value)
    return f"{v:.{digits}g}" if math.isfinite(v) else str(v)
