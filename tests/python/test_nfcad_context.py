"""nfcad.Context.set_block_fields with a CAD before the request workflow.fields: the fields are set
in the workflow as the plugin reads it and written with workflow.set (as before), only if a block
changed. Pure Python."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from nfcad.context import Context, workflow_blocks  # noqa: E402


class OlderHost:
    def __init__(self, wf):
        self.wf, self.sets = wf, 0

    def request(self, method, args):
        if method == "workflow.fields":
            raise RuntimeError("unknown method workflow.fields")
        if method == "workflow.get":
            return self.wf
        if method == "workflow.set":
            self.wf, self.sets = args["workflow"], self.sets + 1
            return None
        raise AssertionError(method)


lens = {"id": "a", "params": {"f": 50}}
group = {"id": "g", "variant": "x", "variants": {"x": {"nodes": [dict(lens)]}, "y": {"nodes": [dict(lens)]}}}
ctx = Context.__new__(Context)
ctx._host = OlderHost({"model": {"nodes": [dict(lens), group]}})
fields = [{"name": "/f", "type": "number", "group": "G"}]
blocks = [{"block": n["id"], "scope": scope, "fields": fields}
          for scope, n in workflow_blocks(ctx._host.wf) if n["id"] == "a"]
assert [b["scope"] for b in blocks] == [[], [{"group": "g", "variant": "x"}], [{"group": "g", "variant": "y"}]]
assert ctx.set_block_fields(blocks) == 3 and ctx._host.sets == 1
nodes = ctx._host.wf["model"]["nodes"]
assert nodes[0]["fields"] == fields and nodes[0]["params"] == {"f": 50}
assert all(v["nodes"][0]["fields"] == fields for v in nodes[1]["variants"].values())
assert ctx.set_block_fields(blocks) == 0 and ctx._host.sets == 1  # unchanged: not written again
assert ctx.set_block_fields([]) == 0
print("nfcad context ok")
