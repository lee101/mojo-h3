# mojo-h3

`mojo-h3` is a standalone Mojo implementation of the H3 4.x cell-index hierarchy
and spherical-distance primitives. It is intended for workloads that already have H3
cells and need to inspect or expand them quickly, plus large batches of geodesic
distance calculations.

Use it as an H3-compatible module for the covered API:

```python
import mojoh3 as h3

sf = "89283082803ffff"
print(h3.get_resolution(sf))              # 9
print(h3.cell_to_parent(sf, 7))           # '872830828ffffff'
print(len(h3.cell_to_children(sf, 10)))   # 7
print(h3.great_circle_distance((37.775, -122.418), (51.5072, -0.1276)))
```

## Covered API

The public functions match their `h3` 4.x names and signatures for this subset:

- Index conversion and inspection: `str_to_int`, `int_to_str`, `is_valid_cell`,
  `get_resolution`, `get_base_cell_number`, `is_pentagon`, `is_res_class_III`.
- Hierarchy: `cell_to_parent`, `cell_to_center_child`, `cell_to_children_size`,
  `cell_to_children`, `get_pentagons`, `get_num_cells`.
- Global H3 dimension constants: `average_hexagon_area` and
  `average_hexagon_edge_length` in the upstream-supported `km^2`/`m^2` and `km`/`m`
  units.
- Geodesics: `great_circle_distance`, plus the extension
  `great_circle_distance_batch(latlng1, latlng2, unit="km")` for `(n, 2)` NumPy
  arrays of latitude/longitude degrees.

All cell-returning functions use upstream's default hexadecimal string form. Invalid
cell and resolution inputs raise compatible `H3CellInvalidError`, `H3ResDomainError`,
or `H3ResMismatchError` classes.

Not yet covered: coordinate-to-cell conversion, boundaries, polygon filling,
neighbour/grid traversal, directed edges, vertices, compaction, and local IJ
coordinates. Those operations depend on the full icosahedral face projection and
topology tables; they are deliberately not shimmed through the upstream package.

## Install and run

Mojo is pinned in the included Pixi environment. The upstream `h3` wheel is installed
only as a test and benchmark reference; `mojoh3` itself loads `dist/libmojo-h3.so`.

```bash
pixi install
pixi run build
pixi run test
pixi run bench
```

`PYTHONPATH=python` is activated by Pixi, so the usage example above runs directly
under `pixi run python` from this checkout.

## Benchmarks

Measured with `pixi run bench` on `x86_64`, Python 3.13.14, on 2026-08-24. Times are
the best of three runs except for the one-million-call upstream Python loop, which is
measured once. The upstream package was `h3` 4.5.0.

| kernel | mojo-h3 | h3 reference | speedup | comparison |
| --- | ---: | ---: | ---: | --- |
| great_circle_distance_batch 1M | 163.71 ms | 2418.21 ms | 14.77x | h3 scalar Python calls |
| cell_to_children res 7 -> 12 | 3.83 ms | 8.47 ms | 2.21x | H3 C extension |
| pentagon children res 5 -> 10 | 2.95 ms | 7.07 ms | 2.40x | H3 C extension |

### Unroll phase (same machine, same harness)

`pixi run bench` end to end. "Before" is `pixi run bench` at the start of this phase;
"after" is `pixi run bench` after the kernel changes. The same-machine `h3` reference
column moves by more than the difference between these rows, so compare each mojo-h3
number against the reference measured beside it, not across rows.

| kernel | before | after | change | h3 reference beside "after" |
| --- | ---: | ---: | ---: | ---: |
| great_circle_distance_batch 1M | 138.39 ms | 135.27 ms | unchanged (within run-to-run spread) | 2632.65 ms |
| cell_to_children res 7 -> 12 | 4.00 ms | 4.16 ms | unchanged (glue-dominated, see below) | 9.53 ms |
| pentagon children res 5 -> 10 | 3.08 ms | 3.18 ms | unchanged (glue-dominated, see below) | 8.19 ms |

### SIMD phase (same machine, same harness)

`pixi run bench` end to end. "Before" is `pixi run bench` at the start of this phase
(kernel = unroll-phase code); "after" is
`pixi run bench` with the change. The shared machine drifts, so the single lock-held rows
are backed by an alternating A/B below.

| kernel | before | after | change | h3 reference beside "after" |
| --- | ---: | ---: | ---: | ---: |
| great_circle_distance_batch 1M | 129.39 ms | 118.96 ms | 1.09x | 2603.37 ms |
| cell_to_children res 7 -> 12 | 3.25 ms | 3.69 ms | unchanged (glue-dominated) | 8.67 ms |
| pentagon children res 5 -> 10 | 2.80 ms | 3.01 ms | unchanged (glue-dominated) | 7.30 ms |

The lock-held rows above do not agree with each other about the children kernels (both are
unmodified this phase), which is why the numbers below come from fresh processes
alternating the old and new tree in the same session, median of 5-7 rounds:

| measurement | old (before this phase) | new | change |
| --- | ---: | ---: | ---: |
| `great_circle_distance_batch`, public wrapper, n = 1,000 | 0.14 ms | 0.13 ms | 1.10x |
| `great_circle_distance_batch`, public wrapper, n = 10,000 | 1.19 ms | 1.03 ms | 1.16x |
| `great_circle_distance_batch`, public wrapper, n = 100,000 | 11.79 ms | 10.89 ms | 1.08x |
| `great_circle_distance_batch`, public wrapper, n = 1,000,000 | 134.97 ms | 118.10 ms | 1.14x |
| batch distance kernel only (C ABI, glue excluded), n = 1,000 | 0.135 ms | 0.099 ms | 1.36x |
| batch distance kernel only, n = 100,000 | 14.71 ms | 10.98 ms | 1.34x |
| batch distance kernel only, n = 1,000,000 | 151.72 ms | 108.62 ms | 1.40x |

The kernel gain is most of the end-to-end gain; what the wrapper still adds on top is two
`ascontiguousarray` no-ops, one `np.empty`, one multiply by `EARTH_RADIUS_KM` and the
ctypes call, all unchanged in this phase. The wrapper now measures 1.19-1.35x faster end to
end than the value recorded in `bench/analysis.md` (145.4 ms at 1M) and in the table at the
top of this section, on the same machine.

**What changed and why it wins.** `great_circle_distance_batch` used to receive radians:
the wrapper ran `np.radians` twice over 16 MB, and the kernel then took the difference of
two already-rounded radian values. Now degrees go straight into the kernel and the
degree -> radian scaling is fused into the row (`mjh_great_circle_distance_batch_degsafe`).
That deletes two 16-byte-per-row passes, but on its own it only recovers about 1.1x. The
remaining 1.3x comes from where the scaling happens: subtracting in degrees and scaling
once is one rounding instead of three, and the compiler then keeps the whole row in
registers with a single multiply-by-constant, instead of a subtract fed by a previously
rounded radian load. `bench/analysis.md` attributed the kernel's 111 ns/row to five serial
transcendental calls; on this toolchain most of that was the radians-form row being
latency-bound, not `sin`/`cos`/`atan2` throughput.

**What did not pay, and is not in the code.** Each item below was implemented, built and
measured; the SIMD one was reverted unchanged:

- A `SIMD[DType.float64, 4]` body (`simd_width_of[DType.float64]()`) with the same formula
  and a scalar tail, measured bit-identical to the scalar row at every length tested. The
  compiler already emits packed arithmetic for the scalar row (`vmulpd` over `ymm`), and
  the transcendentals are libm calls either way. Kernel-only ratio against the scalar
  fused row: 1.10x at n = 1,000, 1.06x at 10,000, 1.03x at 100,000, 0.999x at 1,000,000
  (best of 7, each ratio stable to +-0.01 across 5 rounds). At the size real callers pass
  it is a wash and the three other sizes are within the +-10 % spread, so it was reverted.
- A naive fused variant that scales the *difference* (`(b - a) * (0.5 * DEG_TO_RAD)`).
  When two nearby degrees land on the same scaled value, the fused subtraction returns
  exactly 0 where the radians-in path returns 1 ulp, and a ctypes kernel result comes back
  as an exactly representable double, so no hidden rounding launder it. That is NaN at
  exact antipodes (`sqrt(1 - a)` with `a == 1`) and 0 km where the caller expects ~5e-10 km.
  Rejected on correctness, independent of speed.
- Hoisting `cos(DEG_TO_RAD * lat)` into a named local, and swapping the `for` loop for a
  `while` loop: bit-identical output, but the differences (1.394x vs 1.374x at 1M across 7
  alternating runs) are smaller than the spread between rounds and were not kept.

**Accuracy of the kept kernel** (bit-identical is not possible across a re-association, so
this is measured, not asserted): against the h3 scalar reference on random rows, relative
error is at worst 1.33e-14 (n = 20,001) and 8.5e-14 (n = 1,003) - i.e. the existing
`2e-15` tolerance in `tests/test_parity.py` no longer holds for this path at 20k random
rows. Against an exact-arithmetic check of the `sin` argument, the fused form is slightly
*closer* to the exact degree difference than the radians form (max relative error 7.6e-14
vs 8.3e-14 over 5,000 random latitude pairs).

Endpoint, reduction and buffer assumptions for this phase:

| item | what holds |
| --- | --- |
| endianness of lanes | one row is two adjacent `float64`s, so a group load is a strided even-odd pair |
| alignment | NumPy buffers are at least 8-byte aligned, not 32; the group load is the unaligned form (`load[width=...]`), and all scalar loads are unaligned |
| length 0 | wrapper returns an empty array without touching the kernel; the kernel's own n = 0 path is exercised through `mjh_great_circle_distance_batch_*` in `tests/test_parity.py` |
| tails | covered at 0, 1, 2, 3, 4, 5, 7, 8, 9, 1003 and 20001 rows for the public API, plus a guard that the kernel does not write past `n` |
| reductions | none in the distance kernel (each row is independent); `cell_to_children` has no read-modify-write over neighbouring lanes, so no cross-lane reductions were needed |
| shared buffers | the distance kernel reads `a` and `b` and writes `dst` once per row; nothing else reads the inputs in the same pass, so there is no second stage to fuse |


End-to-end `cell_to_children` at these sizes is 93-95% Python `format()` and `tolist()`
(`bench/analysis.md`), so the kernel gain is hidden: the 7 -> 12 call is 0.16 ms of
kernel inside ~4 ms of conversion. The kernel-only numbers, measured directly on the
C ABI in one process (best of 9, alternating old and new library), are:

| kernel (C ABI, glue excluded) | before | after |
| --- | ---: | ---: |
| cell_to_children hex 7 -> 12 (16,807 cells) | 0.204 ms | 0.141 ms (1.46x) |
| cell_to_children hex 7 -> 14 (823,543 cells, one core) | 14.45 ms | 10.53 ms (1.37x) |
| pentagon children 5 -> 10 (14,006 cells) | 0.068 ms | 0.064 ms (1.06x) |
| great_circle_distance_batch 1M (kernel only) | 106.2-110.8 ms | 106.2-111.3 ms (~1.00x) |

What changed in the children kernel: the per-digit shift is built once per expansion
instead of on every use, the group body and the scalar tail walk the digits with the same
loop shape (two digit steps per iteration; the trip count is a runtime value, so Mojo
cannot unroll it for us), and the helper the scalar tail used is gone. Output is
bit-identical to the previous kernel, and to upstream, at every resolution.

What did not pay on `great_circle_distance_batch`, and is therefore not in the code
(each was measured, then reverted): hoisting `cos(lat1)` out of the row
(sqrt(cos²) reconstruction, +5%), interleaving 4 rows as independent strips, splitting
rows into 4 residue-class partial passes, walking the inputs with their own pointer,
splitting into a latitude pass and a longitude pass, and the textbook
`2*asin(sqrt(h))` form (+10% here, and it moves the last bits). The row is bound by its
five transcendental calls: removing `sin`/`cos` takes it from 105 ms to 59 ms while
removing `atan2` takes it to 68 ms, so there is no serial-accumulator chain left to
break. The multi-accumulator technique therefore stays unused: no kernel in this port
accumulates a sum.

Results are bit-identical to the previous `cell_to_children` kernel. The batch distance
kernel changes only that it writes its output element by element and skips a redundant
bounds check per load; the summation order is unchanged and no tolerance changed. The
batch distance stays within the existing 2e-15 relative of the `h3` scalar reference.

The batch speedup is over repeated Python-to-C calls, not a claim against a hypothetical
upstream vector API. Upstream has no batch great-circle-distance function.

### GPU phase: skipped, no GPU path

No GPU path is included, and none was written or benchmarked in this phase. Two
independent gates both failed:

- **Arithmetic intensity.** The gate admits kernels above roughly 2 flops/byte. The
  highest figure anywhere in `bench/analysis.md` is `great_circle_distance_batch` at
  **0.48 flops/byte**, and that is an *upper bound* (transcendentals counted as 1 flop).
  `cell_to_children` is ~0.6 flops/byte. Per the gate rule, both are **CPU only:
  memory-bound** at the sizes callers pass, so there is no candidate to port.
- **Shared device capacity.** `nvidia-smi --query-gpu=memory.free --format=csv,noheader`
  on this host (2026-11-10, RTX 5090 32 GB, 13 other processes resident) reported
  **3550 MiB free**, under the 4000 MiB floor. The phase is skipped on that basis too.

Because no GPU code was written, there are no before/after GPU numbers to record, no GPU
path to fall back from, and no GPU tests to skip: the existing suite is CPU-only and runs
exactly as before. Should the device later have headroom, the distance batch is the only
plausible candidate (its kernel is ~110 ns/row on one core, bound by five transcendental
calls per row), but at 0.48 flops/byte it would first need to be re-measured against the
2 flops/byte gate rather than assumed to benefit from a transfer.

## How it works

H3 cells encode mode, resolution, base cell, and fifteen three-bit hierarchy digits in
one 64-bit word. The Mojo kernel validates that layout, including the deleted K-axis at
each pentagon, then creates parents and children by editing only those bit fields. Hexagon
children are generated in native-width SIMD groups with a scalar remainder; pentagons use
an allocation-free base-7 odometer. Expansions above 262,144 children are divided into
independent ranges and filled by up to eight GIL-free workers, while smaller requests stay
serial. Children are written into a caller-owned contiguous `int64` NumPy buffer; ctypes
passes that buffer's address to a fixed C ABI, so no per-child allocation crosses the
boundary. The final hex conversion uses Python integers in one bulk `tolist()` conversion
instead of boxing each NumPy scalar separately.

The distance batch kernel receives two contiguous `(n, 2)` float64 arrays, converts no
per-row Python objects, and evaluates the numerically stable haversine/`atan2` formula
in one compiled loop. Scalar `great_circle_distance` uses the same Mojo implementation.

## Verification

The pytest suite compares valid index properties, pentagons at five resolutions,
parents, center children, complete child ordering/counts for hexagons and pentagons,
all 16 global dimension rows, and geodesic results against `h3` 4.5.0. Run it with
`pixi run test`.

MIT. See [LICENSE](LICENSE).
