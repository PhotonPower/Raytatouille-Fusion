"""Plugin base class and the @action decorator."""

from __future__ import annotations

from typing import Callable

API_VERSION = 1


def action(label: str, *, description: str = "", on_workflow_edit: bool = False,
           block_types: tuple[str, ...] = ()) -> Callable:
    """Marks a method ``f(self, ctx)`` as an action shown in CAD (menu / tool column).

    ``on_workflow_edit``: CAD also runs it, quietly, shortly after the node workflow was edited
    (e.g. to draw what the edit changed); it should be quick and raise nothing.

    ``block_types``: an action on one block of the node workflow – CAD shows it in the context menu
    of blocks of these types (not in the menu or the tool column); ``ctx.target`` names the block
    ({"block": id, "scope": [group ids from the top level]})."""

    def mark(f: Callable) -> Callable:
        f._nfcad_action = {"label": label, "description": description}
        if on_workflow_edit:
            f._nfcad_action["on_workflow_edit"] = True
        if block_types:
            f._nfcad_action["block_types"] = list(block_types)
        return f

    return mark


class Plugin:
    """Base class. Subclasses define actions with :func:`action`; ``params`` (a dict of
    :class:`nfcad.Param`, in display order) describes the parameters CAD shows in the plugin
    panel."""

    params: dict = {}

    def params_schema(self) -> list[dict]:
        return [p.to_json(name) for name, p in self.params.items()]

    def convert_params(self, values: dict) -> dict:
        """Values from CAD as Python types; missing ones get their defaults."""
        return {name: p.convert(values.get(name)) for name, p in self.params.items()}

    def blocks(self) -> list[dict]:
        """Block types this plugin provides to the node workflow (ADR 0010, D2): catalogue entries
        (e.g. ``rtt_fusion.graph.remote.BlockProvider.catalogue()``); sent with the hello."""
        return []

    def evaluate_block(self, request: dict) -> dict:
        """Evaluates one of this plugin's blocks for the workflow engine (ADR 0010, D3), e.g. with
        ``BlockProvider.evaluate``; one request at a time, in a thread of its own."""
        return {"ok": False, "error": f"{type(self).__name__} provides no blocks"}

    def preview_block(self, request: dict) -> dict:
        """The overview drawing of a workflow block (docs/plugin-api.md, "Block previews") for the
        tab "Overview" of its parameter dialog: ``request`` holds the block (``"node"``, with the
        values in the dialog, not yet applied), its catalogue entry (``"type"``), the whole model
        (``"model"``: e.g. the source's glass catalogues), the groups around it (``"scope"``) and
        CAD's ``"locale"``. Return ``nfcad.drawing.answer(drawing)`` – or
        ``nfcad.drawing.unsupported()`` for a type this plugin does not draw (CAD then asks the next
        plugin or shows the block's schematic); an error ``{"ok": False, "error": …}`` is shown over
        the schematic. Called in a thread of its own, one request at a time; keep it quick (a second
        at most) – the user waits for it."""
        return {"ok": False, "unsupported": True, "error": f"{type(self).__name__} draws no blocks"}

    def actions(self) -> dict[str, dict]:
        out = {}
        for name in dir(type(self)):
            f = getattr(type(self), name, None)
            meta = getattr(f, "_nfcad_action", None)
            if meta is not None:
                out[name] = meta
        return out
