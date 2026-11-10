"""Run through ``pixi run bench`` so the shared benchmark lock is held."""

import os
import platform
import sys
import time

import h3
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python"))
import mojoh3 as mh3  # noqa: E402
from mojoh3 import lib  # noqa: E402

# Every output a timed call produced, so the harness can prove the timed work was real
# instead of trusting that a short elapsed time means a fast kernel.
captured = []


def best(fn, reps=3):
    elapsed = float("inf")
    for _ in range(reps):
        start = time.perf_counter()
        result = fn()
        elapsed = min(elapsed, time.perf_counter() - start)
        captured.append(result)
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


def _kernel_seconds(fn, reps=9):
    elapsed = float("inf")
    for _ in range(reps):
        start = time.perf_counter()
        status = fn()
        elapsed = min(elapsed, time.perf_counter() - start)
        # Distance kernels return 0; the children kernel returns the number written.
        assert status >= 0
    return elapsed


def main():
    rng = np.random.default_rng(0)
    n = 1_000_000
    first = np.column_stack((rng.uniform(-89, 89, n), rng.uniform(-180, 180, n)))
    second = np.column_stack((rng.uniform(-89, 89, n), rng.uniform(-180, 180, n)))
    cell = h3.latlng_to_cell(37.775, -122.418, 7)
    pentagon = h3.get_pentagons(5)[0]
    expect_children = h3.cell_to_children(cell, 12)
    expect_pentagon = h3.cell_to_children(pentagon, 10)

    mh3.great_circle_distance_batch(first[:10], second[:10])
    captured.clear()
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

    batch_outputs = [result for result in captured if isinstance(result, np.ndarray) and result.shape == (n,)]

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

    # Kernel-only, C ABI, glue excluded. Same rows and same cells as the public rows above.
    print()
    print("| kernel only (C ABI) | ms | note |")
    print("| --- | ---: | --- |")
    out = np.empty(n)
    a_ptr, b_ptr = first.ctypes.data, second.ctypes.data
    rads = _kernel_seconds(lambda: lib().mjh_great_circle_distance_batch(
        a_ptr, first.size, b_ptr, second.size, n, out.ctypes.data, n))
    serial_ms = _kernel_seconds(lambda: lib().mjh_great_circle_distance_batch_degsafe_workers(
        a_ptr, first.size, b_ptr, second.size, n, out.ctypes.data, n, 1))
    threaded_ms = _kernel_seconds(lambda: lib().mjh_great_circle_distance_batch_degsafe_workers(
        a_ptr, first.size, b_ptr, second.size, n, out.ctypes.data, n, 8))
    print(f"| great_circle_distance_batch 1M, rads-in, kernel max workers | {rads * 1e3:.1f} | "
          f"`mjh_great_circle_distance_batch` |")
    print(f"| great_circle_distance_batch 1M, degsafe, 1 worker | {serial_ms * 1e3:.1f} | "
          f"`..._degsafe_workers(..., 1)` |")
    print(f"| great_circle_distance_batch 1M, degsafe, 8 workers | {threaded_ms * 1e3:.1f} | "
          f"`..._degsafe_workers(..., 8)` |")
    children = np.empty(len(expect_children), dtype=np.int64)
    children_14 = np.empty(mh3.cell_to_children_size(cell, 14), dtype=np.int64)
    pent_children = np.empty(len(expect_pentagon), dtype=np.int64)
    c7, p5 = h3.str_to_int(cell), h3.str_to_int(pentagon)
    t = _kernel_seconds(lambda: lib().mjh_cell_to_children(c7, 12, children.ctypes.data, children.size))
    print(f"| cell_to_children hex 7 -> 12 ({len(expect_children):,} cells) | {t * 1e3:.3f} | "
          f"`mjh_cell_to_children` |")
    t = _kernel_seconds(lambda: lib().mjh_cell_to_children(c7, 14, children_14.ctypes.data, children_14.size))
    print(f"| cell_to_children hex 7 -> 14 ({len(children_14):,} cells) | {t * 1e3:.2f} | "
          f"`mjh_cell_to_children` |")
    t = _kernel_seconds(lambda: lib().mjh_cell_to_children(p5, 10, pent_children.ctypes.data, pent_children.size))
    print(f"| pentagon children 5 -> 10 ({len(expect_pentagon):,} cells) | {t * 1e3:.3f} | "
          f"`mjh_cell_to_children` |")

    # What the clock measured is what was computed: every captured batch result must be
    # finite, non-negative and within 1e-12 relative of the h3 scalar reference. The
    # children results must equal upstream exactly.
    max_rel = 0.0
    for got in batch_outputs:
        assert got.shape == (n,) and np.all(np.isfinite(got)) and got.min() >= 0.0
        ref = np.array([h3.great_circle_distance(a, b) for a, b in zip(first, second)])
        max_rel = max(max_rel, float(np.max(np.abs(got - ref) / np.maximum(ref, 1e-300))))
    assert list(children) == [h3.str_to_int(c) for c in expect_children]
    assert list(children_14) == [h3.str_to_int(c) for c in h3.cell_to_children(cell, 14)]
    assert list(pent_children) == [h3.str_to_int(c) for c in expect_pentagon]
    assert max_rel < 1e-12, max_rel
    print()
    print(f"self-check: {len(batch_outputs)} timed 1M batch outputs, shape {n}, all finite; "
          f"max relative difference from h3 scalar {max_rel:.2e}; children kernels bit-identical to h3")


if __name__ == "__main__":
    main()
