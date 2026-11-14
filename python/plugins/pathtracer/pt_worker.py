"""A worker process of pt_parallel: reads the scene and the sensor from the file named on the
command line, then renders the jobs it gets on its standard input and writes the results to
its standard output (both as pickles with their length in front)."""

from __future__ import annotations

import pickle
import struct
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def read(stream):
    """The next object from the stream; None at its end."""
    head = stream.read(8)
    if len(head) < 8:
        return None
    (size,) = struct.unpack("<Q", head)
    data = stream.read(size)
    return pickle.loads(data) if len(data) == size else None


def write(stream, obj) -> None:
    data = pickle.dumps(obj, protocol=4)
    stream.write(struct.pack("<Q", len(data)))
    stream.write(data)
    stream.flush()


def main() -> int:
    import pt_integrator

    with open(sys.argv[1], "rb") as f:
        scene, sensor = pickle.load(f)
    while True:
        job = read(sys.stdin.buffer)
        if job is None:
            return 0
        try:
            result = pt_integrator.render(scene, sensor, **job)
        except Exception:  # tell the parent instead of dying silently
            result = {"failed": traceback.format_exc()}
        write(sys.stdout.buffer, result)


if __name__ == "__main__":
    sys.exit(main())
