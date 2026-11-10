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

No GPU path is included. Child expansion is integer bit manipulation with one 8-byte
output per cell, so it is below the arithmetic-intensity threshold where device transfer
and launch costs can pay off. Great-circle distance is compute-intensive, but its CPU
batch was already more than 5x ahead of the upstream scalar-call reference and was not
an optimization target.

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
