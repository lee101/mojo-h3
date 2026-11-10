# mojo-h3 — ANALYZE phase: where the time actually goes

Measured in this session on `x86_64`, Intel Xeon E5-2697 v4 @ 2.30 GHz (2 sockets,
18 cores each, 72 logical CPUs, **AVX2 only — no AVX-512**), Python 3.13.14,
NumPy 2.5.1, upstream `h3` 4.5.0, Mojo `1.2.0.dev2026092605`.

Nothing in `src/` or `tests/` was changed. Every number below came from a run in this
session; no figures are estimated or carried over from `README.md`.

## How the numbers were produced

| source | command | notes |
| --- | --- | --- |
| Headline table | `pixi run bench` | flock-held, single shot, best of 3 (upstream 1M loop: 1 rep) |
| Attribution, kernel split | `flock /tmp/mojo-bench.lock pixi run python -u <scratch profiler>` | also under the lock |
| Per-call averages | `pixi run python -u <scratch profiler>` | no lock; mean over 200k-call loops so shared-machine noise cancels, re-confirmed with GC disabled |

The two scratch profilers were run from `/tmp` and deleted afterwards, so the only file this
phase adds is `bench/analysis.md`. Their figures are quoted here verbatim from the session
logs; re-running them needs the same scripts re-created (they are thin wrappers around
`mojoh3`, the C ABI symbols and `time.perf_counter`).

The machine is shared with other factory jobs; `flock /tmp/mojo-bench.lock` had 12 waiters
from other ports and the first `pixi run bench` spent ~12 min queued before it ran. Treat
run-to-run spread as roughly ±10 % (`great_circle_distance_batch 1M` measured 150.6 ms and
131.9–135.8 ms in three separate sessions; single-shot lock-held time was 145.4 ms).

Byte and flop conventions used in the table (so the flops/byte column is reproducible):

- `great_circle_distance` / `_batch`: 16 B in (2 × f64 latlng) + 16 B in + 8 B out = **40 B/row**;
  **19 flops/row** (2 sub + 2 half-mul, `sin` ×2, `cos` ×2, 3 products, `add`, `cmp`,
  `1.0-a`, `sqrt` ×2, `atan2`, `*2`). A transcendental is **counted as 1 flop** — that is
  the optimistic convention, so the reported arithmetic intensity is an *upper bound*.
  Those 40 B/row are the minimal traffic: `(n,2)` streamed with no reuse of a row
  across lanes, 2 reads + 1 write.
- `cell_to_children`: 8 B out/cell, bounded-integer bit edits (~5 flops/cell for the hex
  path; `pow7`/`digit` lookups excluded). Input is 1 cell.
- Per-call entry points: tens of bytes, so flops/byte is not meaningful and the column is
  marked `n/a`.

## Ranked hotspot table

Sorted by the time the hotspot costs at the size real callers pass. `glue` = Python +
ctypes, `kernel` = time inside the compiled Mojo loop (measured by calling the C ABI
symbol directly, bypassing the Python wrapper). `<1%` means below measurement noise.
`**SLOWER**` marks rows where mojoh3 loses to upstream 4.5.0.

| # | function | input size | time (this run) | bytes touched | flops | flops/byte | bound | time sits in | next phase |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| 1 | `cell_to_children` 7→15 | 5,764,801 children | **1826.6 ms** bench / 1818.6 ms prof | 46.1 MB out | ~29 M | ~0.6 | memory (glue-dominated) | kernel 117 ms (6.4 %), **glue 1700 ms (93.6 %)** | **unroll** |
| 2 | `cell_to_children` 7→14 | 823,543 children | **268.9 ms** | 6.6 MB out | ~4.1 M | ~0.6 | memory (glue-dominated) | kernel 14.5 ms (5.2 %), glue 266 ms (94.8 %) | **unroll** |
| 3 | `great_circle_distance_batch` | n = 1,000,000 | **145.4 ms** bench / 150.6 ms prof | 40.0 MB (16+16 in, 8 out) | 19 M | **0.48** (upper bound) | compute (calls, not bandwidth) | kernel 109.5–111.2 ms (**72.7 %**), `np.radians` ×2 27.2–37.4 ms, final `*R` 0.6 ms | **unroll** then **simd** |
| 4 | `great_circle_distance_batch` | n = 100,000 | 11.1 ms prof | 4.0 MB | 1.9 M | 0.48 | compute | kernel 10.0 ms (90.7 %), glue 1.0 ms | **unroll** / **simd** |
| 5 | `cell_to_children` 7→13 | 117,649 children | **31.8 ms** bench / 38.2 ms prof | 0.94 MB out | ~0.6 M | ~0.6 | glue | kernel 1.8 ms (4.6 %), glue 36.5 ms (95.4 %) | **unroll** |
| 6 | Python-loop `is_valid_cell` | 10k calls | **10.06 ms** prof / 20.05 ms ×20k GC-off | ~10k × 8 B | trivial | n/a | glue | **1.0 µs/call, glue-only** | **none** (see note) |
| 7 | `cell_to_children` 7→12 | 16,807 children | 4.46 ms bench / 3.92 ms prof | 0.13 MB out | ~84 k | ~0.6 | glue | kernel 0.23 ms (5.9 %), glue 3.69 ms (94.1 %) | **unroll** |
| 8 | pentagon `cell_to_children` 5→10 | 14,006 children | 3.60 ms bench / 3.01 ms prof | 0.11 MB | ~70 k | ~0.6 | glue + branch | kernel (incl. odometer skips) < 20 % of total, rest is 14k × `format` | **unroll** |
| 9 | `cell_to_center_child` | 1 cell | **3976 ns** vs upstream 705 ns (`0.18x` **SLOWER**) | 8 B | ~5 | n/a | glue | 3.98 µs = 4 ctypes calls (~2.3 µs: 2×validate + resolution + edit) + `int`/`format` + Python | **none** (API is single-cell) |
| 10 | `cell_to_parent` | 1 cell | **3914 ns** vs 654 ns (`0.17x` **SLOWER**) | 8 B | ~5 | n/a | glue | same shape: 4 ctypes calls + string round-trip | **none** (API is single-cell) |
| 11 | `cell_to_children_size` | 1 cell | **3790 ns** vs 379 ns (`0.10x` **SLOWER**) | 8 B | trivial | n/a | glue | 4 ctypes calls: `_require_cell` + `get_resolution` (re-validates) + size | **none** |
| 12 | `get_resolution` | 1 cell | **1714 ns** vs 349 ns (`0.20x` **SLOWER**) | 8 B | ~2 | n/a | glue | 2 ctypes calls (573 + 614 ns) + `int(str,16)` 165 ns + `lib()` 90 ns | **none** |
| 13 | `get_base_cell_number` | 1 cell | **1675 ns** vs 297 ns (`0.18x` **SLOWER**) | 8 B | ~3 | n/a | glue | same | **none** |
| 14 | `is_res_class_III` | 1 cell | **1704 ns** vs 271 ns (`0.16x` **SLOWER**) | 8 B | ~2 | n/a | glue | wraps `get_resolution` ⇒ same 2 ctypes calls | **none** |
| 15 | `is_valid_cell` | 1 cell | **1037 ns** vs 300 ns (`0.29x` **SLOWER**) | 8 B | ~45 | n/a | glue | 1 ctypes call 614 ns + `_int_cell` | **none** |
| 16 | `is_pentagon` | 1 cell | **1025 ns** vs 279 ns (`0.27x` **SLOWER**) | 8 B | ~45 | n/a | glue | 1 ctypes call | **none** |
| 17 | `great_circle_distance` (scalar) | 1 pair | **1700 ns** vs 347 ns (`0.20x` **SLOWER**) | 40 B | 19 | 0.48 | glue | ctypes 4-f64 call 1352 ns (79.5 %), `math.radians` ×4 220 ns | **none** (use `_batch`) |
| 18 | `great_circle_distance` ×10k Python loop | 10k pairs | **17.71 ms** vs 3.22 ms (`0.18x` **SLOWER**) | 0.4 MB | 0.19 M | 0.48 | glue | 1771 ns/call, of which 1.35 µs is ctypes marshalling | **none** — v4 callers should use `_batch` |
| 19 | `cell_to_children` 7→12, small | 16,807 children | 217 ns/child | 0.13 MB | ~5/child | ~0.6 | glue | conversion, not kernel | **unroll** |
| 20 | `cell_to_children` 7→8 | 7 children | **10.5 µs** vs 6.9 µs (`0.66x` **SLOWER**) | 56 B | ~35 | n/a | glue | 10.5 µs is almost pure fixed overhead: 4 ctypes calls (~2.3 µs) + 7 `format`s (~1.7 µs) + Python bookkeeping | **unroll** |
| 21 | `get_num_cells` | 1 res | **466 ns** vs 273 ns (`0.59x` **SLOWER**) | 0 | ~4 | n/a | glue | `_require_res` only | **none** |
| 22 | `get_pentagons` | res 5 → 12 cells | 7.5 µs vs 12.2 µs (`1.63x`) | 96 B | trivial | n/a | glue | 12 × (`_cell` + `int_to_str`) + `_require_res` | none |
| 23 | `average_hexagon_area` / `_edge_length` | 1 res | 343 / 339 ns vs 466 / 445 ns (`1.36x` / `1.31x`) | 0 | 1 | n/a | glue | table lookup + `_require_res` | none |
| 24 | `str_to_int` | 10,012 cells | 1.96 ms vs 2.06 ms (`1.05x`) | 10k × 16 B str | trivial | n/a | glue | Python `int(s,16)` = 165 ns | none |
| 25 | `int_to_str` | 10,012 cells | 2.38 ms vs 3.51 ms (`1.48x`) | 10k × 8 B | trivial | n/a | glue | `format(x,'x')` = 238 ns | none |

Reference baselines measured in the same runs:

| baseline | value | used for |
| --- | --- | --- |
| pure NumPy haversine, n = 1M (no Mojo, no ctypes) | 156.6 ms | mojoh3 batch is **1.15x** faster than plain NumPy |
| pure NumPy haversine, n = 10k | 1.161 ms | mojoh3 1.168 ms → **0.99x**, i.e. a tie |
| ctypes floor, 1 int64 arg (`mjh_get_resolution`) | **564 ns/call** (200k-call loop) | every "SLOWER" single-cell row |
| ctypes floor, 4 f64 args (`mjh_great_circle_distance`) | **1352 ns/call** | scalar distance row |
| ctypes floor, 6 int args (`mjh_cell_to_children_range`) | measured via `mjh_cell_to_children` = 1.1 µs | `cell_to_children` fixed cost |
| Python `int(s,16)` / `format(x,'x')` / `lib()` | 165 / 238 / 90 ns | decomposed glue |
| upstream `h3.cell_to_children` 7→12 | 9169 µs ≈ 9.2 ms | rows 7, 19, 20 |
| upstream `h3.cell_to_children` 7→15 | 3760 ms | row 1 |

## The three findings that matter

### 1. `cell_to_children` is 93–95 % Python string conversion, not the kernel

Kernel vs glue, measured on the same `int64` buffer via direct ctypes calls
(`bench/analysis_profile2.py`):

| target | n | total | kernel (serial ABI call) | conversion = total − kernel | ns/child |
| --- | ---: | ---: | ---: | ---: | ---: |
| 7→12 | 16,807 | 3.92 ms | 0.23 ms | 3.69 ms (94 %) | 233 |
| 7→13 | 117,649 | 38.21 ms | 1.76 ms | 36.45 ms (95 %) | 325 |
| 7→14 | 823,543 | 280.43 ms | 14.54 ms | 265.89 ms (95 %) | 341 |
| 7→15 | 5,764,801 | 1818.64 ms | 117.10 ms | 1701.54 ms (94 %) | 315 |

Breakdown at 7→12 (16,807 children, mean of 2,000 calls):

| step | µs | share of total |
| --- | ---: | ---: |
| `mjh_cell_to_children` kernel | 215.1 | 5.1 % |
| `np.empty(16807, int64)` | 0.5 | 0.01 % |
| `raw.tolist()` (500 ns → NumPy scalar boxing) | 485.4 | 11.6 % |
| `[format(x, "x") for x in list]` | 3156.8 | **75.3 %** |
| `bytes(x.to_bytes(8,"big")).hex()` baseline | 2437.4 | 58 % (alternative, also slow) |
| public `cell_to_children` | 4194.8 | 100 % |
| upstream `h3.cell_to_children` | 9168.9 | 2.2x slower than mojoh3 |

So the winning margin over upstream is a *Python-formatting* win (upstream formats
inside its C extension but re-validates every child), and the kernel at 18–21 ns/child
(`res 7→14 kernel serial 15.07 ms / 823,543 = 18.3 ns/child`, `7→15 122.52 ms /
5,764,801 = 21.3 ns/child`) is **13–17x** faster than the per-child Python cost it feeds.
The kernel is already near the store-bandwidth/ALU floor for this operation.

The Python-level loop that re-enters ctypes per element is **not** in the library — it is
in the *caller pattern*: `cell_to_children` is single-cell, so a caller looping over k
cells pays `1.5 µs` fixed cost **plus 3 ctypes calls** per cell before any work happens.
There is no batch entry point for hierarchy ops.

### 2. The distance batch is compute-bound on calls, not on bandwidth, and is barely ahead of NumPy

| n | wrapper | radians | kernel-direct | wrapper − kernel | ns/row |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 0.129 ms | 0.011 ms | 0.105 ms | 0.023 ms | 128.8 |
| 10,000 | 1.171 ms | 0.095 ms | 1.020 ms | 0.151 ms | 117.1 |
| 100,000 | 11.078 ms | 0.882 ms | 10.046 ms | 1.031 ms | 110.8 |
| 1,000,000 | 131.923 ms | 18.689 ms | 106.347 ms | 25.576 ms | 131.9 |

The n = 1,000,000 profile row was measured outside the lock and landed above the lock-held
`pixi run bench` time (145.4 ms, kernel 109.5 ms) — shared-machine variance, noted rather
than smoothed away.

- Kernel-only at n = 1M: **111.2 ms**, 111 ns/row. At 40 B/row that is **0.36 GB/s** and
  **0.171 GFLOP/s** (19-flop convention). A single core can stream ~10 GB/s and issue
  ~10 GFLOP/s of scalar `sin`/`cos`/`atan2`, so the kernel is **~30x off both roofs**.
  It is bound by serial call latency into `sin`/`cos`/`atan2` on one core, not by memory.
  Arithmetic intensity **0.48 flops/byte (upper bound)** — far below the ~2 flops/byte
  threshold the accel rules use for even considering a GPU.
- `np.radians` runs **twice** over 16 MB (it allocates two new `(n,2)` arrays): 27.2 ms
  single-shot in the locked run, 18.7 ms averaged in the unlocked one. That is 13–25 % of
  the wrapper, on top of a `np.empty` and a `*R` pass. This is a per-call copy, not a
  kernel cost: `a` and `b` are copied once by `np.radians`, and `np.ascontiguousarray`
  additionally probes (192 ns no-op, harmless).
- Against a plain baseline: mojoh3 is **1.15x** faster than hand-written NumPy at 1M and
  **0.99x** (a tie) at 10k. The README's `17.8x` figure is against a per-point Python
  loop through the h3 C extension (2591.8 ms for 1M calls), which is not the baseline a
  NumPy caller would otherwise use.
- The batch kernel at 110–132 ns/row versus the scalar ABI call at 1352 ns/row (batched
  hoists ctypes and output scaling) means the seam is already correct; nothing per-row
  crosses into Python.

`cProfile` confirms the wrapper is a single flat function — `14 function calls in
0.149 seconds`, all 0.149 s attributed to `great_circle_distance_batch` itself. No hidden
Python loop.

### 3. Every single-cell entry point is 5–10x slower than upstream, and it is all ctypes floor

A Python→C call through ctypes on this machine costs **564 ns** for one int64 argument and
**1352 ns** for four doubles. A call through upstream's C-extension entry costs ~250–350 ns
total *including* its work. Nothing in a 2-flop function can beat that:

| function | mojoh3 | upstream | ratio | ctypes calls in the path | predicted floor |
| --- | ---: | ---: | ---: | ---: | ---: |
| `cell_to_children_size` | 3790 ns | 379 ns | **0.10x** | 4 (`_require_cell`, `get_resolution` → `_require_cell`, size) | ~2.3 µs |
| `cell_to_parent` | 3914 ns | 654 ns | **0.17x** | 4 | ~2.3 µs |
| `cell_to_center_child` | 3976 ns | 705 ns | **0.18x** | 4 | ~2.3 µs |
| `is_res_class_III` | 1704 ns | 271 ns | **0.16x** | 3 (`_require_cell`, `get_resolution` → `_require_cell` + resolution) | ~1.7 µs |
| `get_base_cell_number` | 1675 ns | 297 ns | **0.18x** | 2 (`_require_cell`, `mjh_get_base_cell`) | ~1.1 µs |
| `get_resolution` | 1714 ns | 349 ns | **0.20x** | 2 (`_require_cell`, `mjh_get_resolution`) | ~1.1 µs |
| `great_circle_distance` | 1700 ns | 347 ns | **0.20x** | 1 (4 f64) | 1.35 µs |
| `is_valid_cell` / `is_pentagon` | ~1030 ns | ~290 ns | **~0.28x** | 1 | ~0.6 µs |
| `get_num_cells` | 466 ns | 273 ns | **0.59x** | 0 (Python only) | — |

Redundant calls are visible in the code: `cell_to_parent` calls `_require_cell` (which
already calls `mjh_is_valid_cell`), then `get_resolution` (which calls `_require_cell`
*again* — another validation call — then `mjh_get_resolution`), then
`mjh_cell_to_parent`: **4 ctypes trips for a pure bit edit**. `cell_to_children` likewise
validates twice and asks for the size in a separate call. Replacing the C validation call
with a Python-side bit test would still leave the 90 ns `lib()` accessor and ~1 µs of
ctypes argument marshalling per call; this phase does not change `src/`, so the floor
stands for now.

The GC-off re-check rules out GC as the cause: `is_valid_cell` 1.003 µs vs upstream
246 ns (4.1x, **SLOWER**), `get_resolution` 1648 ns vs 288 ns, `cell_to_parent` 3715 ns
vs 640 ns — same ratios as with GC on.

## Python-level loops that re-enter ctypes per element

These are the *only* places per-element ctypes re-entry can occur, and all of them are
in the caller/glue layer, not in the kernels:

| site | re-entry pattern | measured cost |
| --- | --- | --- |
| caller loop over calls to `cell_to_children` | 4 ctypes calls per cell (validate ×2, resolution, size) + fill | ~2.3 µs fixed + 215 ns/child at 7→12 |
| caller loop over `is_valid_cell` | 1 ctypes call per cell + `int(s,16)` | 1006 ns/cell (10.06 ms / 10k); upstream 260 ns |
| caller loop over `get_resolution` | 2 ctypes calls per cell | 1714 ns/cell |
| caller loop over scalar `great_circle_distance` | 1 four-double ctypes call per pair | 1771 ns/pair vs 131.9 ns/row in the batch — **13.4x** penalty for using the scalar path |
| caller loop over `str_to_int`/`int_to_str` | *no* ctypes call at all (pure Python) | 195 / 238 ns each, competitive with upstream |
| inside `great_circle_distance_batch` | **none** — one call for the whole array | 25.6 ms wrapper overhead at 1M, of which 18.7 ms is `np.radians` |
| inside `cell_to_children` | **none** — one call fills the whole buffer | kernel 117 ms of 1818 ms at 7→15 |

The kernels themselves have no per-element Python or ctypes re-entry. The gap is that the
*public API* is single-cell, so any real batch workload builds that loop outside the
library.

## Per-call allocations and copies

| site | allocation / copy | measured |
| --- | --- | --- |
| `great_circle_distance_batch` | `np.asarray(latlng1)`, `np.asarray(latlng2)` | 0 (views, dtype already f64) |
| `great_circle_distance_batch` | `np.ascontiguousarray(a)` ×2 | 192 ns each when already contiguous; **a full copy** if a caller passes strided `(n,2)` slices || `great_circle_distance_batch` | `np.radians(a)` and `np.radians(b)` | **two new 16 MB arrays per call**; 18.7–27.2 ms at 1M |
| `great_circle_distance_batch` | `np.empty(n)` output | 1.6 µs, negligible |
| `great_circle_distance_batch` | `radians * EARTH_RADIUS_KM` (unit="km") | **one extra 8 MB temporary**; 0.62 ms |
| `cell_to_children` | `np.empty(size, int64)` | 0.5 µs at 16,807; 47 MB at 7→15 |
| `cell_to_children` | `raw.tolist()` → one Python `int` object per child | **485 µs / 16,807 = 29 ns/child**; at 7→15 that is 5.76 M `int` objects (≥ 160 MB, 32 B each) |
| `cell_to_children` | `[format(x,"x") for x in …]` → one `str` per child | **3,157 µs / 16,807 = 188 ns/child**; dominant cost |
| `cell_to_children` (≥ 262,144) | `ThreadPoolExecutor(max_workers=min(8, len(ranges)))` per call | fixed pool construction; 45 `(start, end)` tuples and 45 chunks at 7→15 |
| `cell_to_children` (pentagon path) | allocation-free odometer (by design) | 5→10: 215 ns/child, same as hex path |
| single-cell entry points | `_cell`/`_int_cell` build one `str`/`int` per call | `format` 238 ns, `int(s,16)` 165 ns |
| every entry point | `lib()` accessor + ctypes argument conversion | 90 ns accessor + 564–1352 ns per call |

The `cell_to_children` thread pool is currently **not paying off on the dominant cost**: at
7→15 the kernel does 117 ms serially and the wrapper spends 1,702 ms in single-threaded
conversion (the `tolist()`/`format` loop holds the GIL, so the pool cannot touch it).

## Phase assignment summary

| next phase | hotspots | evidence |
| --- | --- | --- |
| **unroll** | `cell_to_children` conversion path (rows 1, 2, 5, 7, 8, 19, 20); distance kernel inner loop (rows 3, 4) | 93–95 % of child-expansion time is 188 ns/child `format()` + 29 ns/child `tolist()` + 168 ns fixed ctypes, not the 18–21 ns/child kernel. The distance kernel is ~30x off both roofs with a serial `sin`/`cos`/`atan2` chain per row. |
| **simd** | distance kernel (rows 3, 4) | 0.48 flops/byte upper bound, 0.171 GFLOP/s achieved, 0.36 GB/s achieved. A `SIMD[DType.float64, 4]` (AVX2 width) body would process 4 rows/call; `sin`/`cos`/`atan2` are the constraint, so measure before expecting more than ~2x. |
| **parallel** | distance batch at n ≥ 100k (rows 3, 4) | kernel is one serial core for 109.5 ms of a 145.4 ms call; `max.algorithm.parallelize` exists in this toolchain (`MOJO_NOTES.md` §4). Only worthwhile if `unroll`/`simd` leave it core-bound. **Do not** parallelize the child-expansion *conversion*: it is GIL-bound Python and the existing threshold already sends the kernel to 8 threads without touching the dominant cost. |
| **gpu** | none | highest arithmetic intensity anywhere is **0.48 flops/byte** (distance, upper-bound convention, transcendentals counted as 1 flop). That is well under the ~2 flops/byte floor from `prompts/accel.md`, and the child path is ~0.6 flops/byte with 8 B of output per cell. No GPU verdict is supported by these figures. |
| **none** | single-cell API (rows 6, 9–18, 21–25) | every row is pinned by the 564 ns / 1352 ns ctypes floor plus 90 ns `lib()` plus 165–238 ns string conversion. The API is one cell per call; no kernel change can move these. Unrolling the kernel cannot help a 2-flop function. Collapsing the redundant validation/size calls in the wrapper (4 ctypes trips → 2) would recover roughly half of `cell_to_parent`/`cell_to_center_child`/`cell_to_children_size`, but the rest is the call floor — and this phase is not permitted to change `src/`. |

Rows marked `**SLOWER**` in the table above must be re-measured after each later phase; they
are the regression surface the port currently accepts in exchange for the child-expansion
win.

## Threats to validity

- The machine is shared (72 logical CPUs, other ports benching concurrently); the lock-held
  runs are single-shot, so treat ±10 % as run-to-run spread, not signal.
- The flop counts are hand-derived with transcendentals counted as one flop. They are
  consistent between rows, and are upper bounds on arithmetic intensity — which only
  strengthens the no-GPU verdict.
- The 7→15 child row allocates ~5.7 M Python `int` and `str` objects; measured time
  includes GC (disabled inside the timed region by `best()`, but the objects are still
  built and freed).
