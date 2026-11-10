"""Run through ``pixi run bench`` so the shared benchmark lock is held."""

import os
import platform
import sys
import time

import h3
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python"))
import mojoh3 as mh3  # noqa: E402


def best(fn, reps=3):
    elapsed = float("inf")
    for _ in range(reps):
        start = time.perf_counter()
        fn()
        elapsed = min(elapsed, time.perf_counter() - start)
    return elapsed


def row(name, mojo_seconds, ref_seconds, reference):
    speedup = ref_seconds / mojo_seconds
    print(f"| {name} | {mojo_seconds * 1e3:.2f} ms | {ref_seconds * 1e3:.2f} ms | {speedup:.2f}x | {reference} |")


def _with_workers(workers, latlng1, latlng2):
    """Run the public batch wrapper at a fixed worker count, restoring the default after."""
    previous = mh3._BATCH_WORKERS
    mh3._BATCH_WORKERS = workers
    try:
        return mh3.great_circle_distance_batch(latlng1, latlng2)
    finally:
        mh3._BATCH_WORKERS = previous


def main():
    rng = np.random.default_rng(0)
    n = 1_000_000
    first = np.column_stack((rng.uniform(-89, 89, n), rng.uniform(-180, 180, n)))
    second = np.column_stack((rng.uniform(-89, 89, n), rng.uniform(-180, 180, n)))
    cell = h3.latlng_to_cell(37.775, -122.418, 7)
    pentagon = h3.get_pentagons(5)[0]

    mh3.great_circle_distance_batch(first[:10], second[:10])
    print(
        f"Machine: {platform.processor() or platform.machine()}, "
        f"Python {platform.python_version()}, h3 {h3.__version__}"
    )
    print("| kernel | mojo-h3 | h3 reference | speedup | comparison |")
    print("| --- | ---: | ---: | ---: | --- |")
    mojo = best(lambda: mh3.great_circle_distance_batch(first, second))
    reference = best(lambda: [h3.great_circle_distance(a, b) for a, b in zip(first, second)], reps=1)
    row("great_circle_distance_batch 1M", mojo, reference, "h3 scalar Python calls")
    mojo = best(lambda: mh3.cell_to_children(cell, 12))
    reference = best(lambda: h3.cell_to_children(cell, 12))
    row("cell_to_children res 7 -> 12", mojo, reference, "H3 C extension")
    mojo = best(lambda: mh3.cell_to_children(pentagon, 10))
    reference = best(lambda: h3.cell_to_children(pentagon, 10))
    row("pentagon children res 5 -> 10", mojo, reference, "H3 C extension")

    # Serial control for the threaded batch path, and the sizes either side of the
    # kernel's crossover (131,072 rows). Same harness, same lock.
    print()
    print("| serial control / crossover | mojo-h3 | serial control | speedup | comparison |")
    print("| --- | ---: | ---: | ---: | --- |")
    for n in (100_000, 1_000_000):
        serial = best(lambda: _with_workers(1, first[:n], second[:n]))
        threaded = best(lambda: _with_workers(8, first[:n], second[:n]))
        row(f"great_circle_distance_batch {n // 1000}k, 8 workers vs 1",
            threaded, serial, "serial control (same call, _BATCH_WORKERS=1)")


if __name__ == "__main__":
    main()
