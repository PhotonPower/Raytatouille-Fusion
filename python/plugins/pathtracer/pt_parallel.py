"""Rendering on several processor cores: the samples are cut into jobs, worker processes
(pt_worker.py) render them with seeds of their own, and the results are averaged. The jobs do
not depend on the number of processes, so neither does the result. NumPy and the standard
library only."""

from __future__ import annotations

import os
import pickle
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import numpy as np

import pt_integrator
import pt_worker


def process_count(processes: int) -> int:
    """processes as given; 0: half of the processor cores, at most 4 (each process holds the
    scene and its paths – some hundred MB)."""
    if processes > 0:
        return processes
    return max(1, min((os.cpu_count() or 2) // 2, 4))


def job_size(samples: int) -> int:
    """Samples per job: 16 jobs where the samples allow, 20 000 … 200 000 each."""
    return int(np.clip(samples // 16, 20_000, 200_000))


def combine(results: list[dict]) -> dict:
    """The mean of the results of independent jobs, weighted by their samples."""
    done = sum(r["samples"] for r in results)
    if not done:
        return results[0]
    weight = [r["samples"] / done for r in results]
    out = {"values": sum(w * r["values"] for w, r in zip(weight, results)),
           "channels": sum(w * r["channels"] for w, r in zip(weight, results)),
           "samples": done, "rays": sum(r["rays"] for r in results)}
    if all(r.get("error") is not None for r in results):
        out["error"] = np.sqrt(sum((w * r["error"]) ** 2 for w, r in zip(weight, results)))
    elif len(results) > 1:                                   # single batches: the spread of the jobs
        mean_sq = sum(w * r["values"] ** 2 for w, r in zip(weight, results))
        out["error"] = np.sqrt(np.clip((mean_sq - out["values"] ** 2) / (len(results) - 1), 0.0, None))
    else:
        out["error"] = None
    if "radius" in results[0]:
        out["radius"] = max(r["radius"] for r in results)
        out["passes"] = sum(r["passes"] for r in results)
    return out


PILOT = 4            # jobs that find out where the samples are needed, when sampling adapts


def render(scene, sensor, method: str, samples: int, depth: int, *, seed: int = 0, processes: int = 0,
           radius: float = 0.0, adaptive: bool = False, progress=None, cancelled=None) -> dict:
    """As pt_integrator.render, on `processes` processor cores (0: see process_count). Small
    computations and a single process run in this process. The result has "processes".

    adaptive: the first PILOT jobs adapt on their own; from their errors together the sensor's
    shares for all other jobs are set (the same for any number of processes)."""
    count = process_count(processes)
    size = job_size(samples)
    if count <= 1 or samples < 2 * size:
        out = pt_integrator.render(scene, sensor, method, samples, depth, seed=seed, radius=radius,
                                   adaptive=adaptive, progress=progress, cancelled=cancelled)
        return {**out, "processes": 1}
    todo = [{"method": method, "samples": min(size, samples - start), "depth": depth,
             "seed": seed * 1_000_003 + number, "radius": radius, "adaptive": adaptive}
            for number, start in enumerate(range(0, samples, size))]
    number = len(todo)
    count = min(count, number)
    steer = adaptive and pt_integrator.adapts(method, sensor.camera) and number > PILOT
    jobs: queue.Queue = queue.Queue()
    results: queue.Queue = queue.Queue()
    stop = threading.Event()

    def serve(process) -> None:                              # one thread per worker: job out, result in
        try:
            while True:
                job = jobs.get()
                if job is None or stop.is_set():
                    return
                pt_worker.write(process.stdin, job)
                answer = pt_worker.read(process.stdout)
                results.put(answer if answer is not None else {"failed": "a worker process ended unexpectedly"})
        except (OSError, ValueError) as e:                   # the pipe broke (also: stopped on purpose)
            results.put({"failed": f"a worker process ended unexpectedly ({e})"})

    got: list[dict] = []
    failed = ""

    def collect(until: int) -> bool:
        """Waits until `until` jobs are back; False if cancelled or failed."""
        nonlocal failed
        while len(got) < until:
            if cancelled is not None and cancelled():
                return False
            try:
                answer = results.get(timeout=0.2)
            except queue.Empty:
                continue
            if "failed" in answer:
                failed = answer["failed"]
                return False
            got.append(answer)
            if progress is not None:
                progress(sum(r["samples"] for r in got) / samples)
        return True

    with tempfile.TemporaryDirectory(prefix="pathtracer-") as folder:
        scene_file = Path(folder) / "scene.pickle"
        sensor.reset()
        with open(scene_file, "wb") as f:
            pickle.dump((scene, sensor), f, protocol=4)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        workers = [subprocess.Popen([sys.executable, str(Path(pt_worker.__file__).resolve()), str(scene_file)],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    creationflags=flags) for _ in range(count)]
        threads = [threading.Thread(target=serve, args=(w,), daemon=True) for w in workers]
        for t in threads:
            t.start()
        try:
            first = PILOT if steer else number
            for job in todo[:first]:
                jobs.put(job)
            if collect(first) and steer:
                error = combine(got)["error"]
                if error is not None:
                    sensor.adapt(error)                      # from the pilot jobs together
                for job in todo[first:]:
                    jobs.put({**job, "adaptive": False, "weights": sensor.prob.copy()})
                collect(number)
        finally:
            stop.set()
            for _ in workers:
                jobs.put(None)
            for w in workers:
                if len(got) < number:                        # stopped early: do not wait for running jobs
                    w.kill()
                else:
                    w.stdin.close()
            for w in workers:
                w.wait()
            for w in workers:
                for stream in (w.stdin, w.stdout):
                    try:
                        stream.close()
                    except OSError:
                        pass
            sensor.reset()
    if failed:
        raise RuntimeError(f"path tracer worker: {failed}")
    if not got:                                              # cancelled before the first job came back
        channels = np.zeros((len(scene.wavelengths), sensor.count))
        return {"values": channels.sum(axis=0), "channels": channels, "error": None, "samples": 0, "rays": 0,
                "processes": count}
    return {**combine(got), "processes": count}
