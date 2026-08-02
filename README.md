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

Measured with `pixi run bench` on `x86_64`, Python 3.13.14, on 2026-08-02. Times are
the best of three runs except for the one-million-call upstream Python loop, which is
measured once. The upstream package was `h3` 4.5.0.

| kernel | mojo-h3 | h3 reference | speedup | comparison |
| --- | ---: | ---: | ---: | --- |
| great_circle_distance_batch 1M | 1087.81 ms | 2623.74 ms | 2.41x | h3 scalar Python calls |
| cell_to_children res 7 -> 12 | 6.31 ms | 8.82 ms | 1.40x | H3 C extension |
| pentagon children res 5 -> 10 | 5.27 ms | 7.32 ms | 1.39x | H3 C extension |

The batch speedup is over repeated Python-to-C calls, not a claim against a hypothetical
upstream vector API. Upstream has no batch great-circle-distance function.

## How it works

H3 cells encode mode, resolution, base cell, and fifteen three-bit hierarchy digits in
one 64-bit word. The Mojo kernel validates that layout, including the deleted K-axis at
each pentagon, then creates parents and children by editing only those bit fields. It
writes children into a caller-owned contiguous `int64` NumPy buffer; ctypes passes that
buffer's address to a fixed C ABI, so no per-child allocation crosses the boundary.

The distance batch kernel receives two contiguous `(n, 2)` float64 arrays, converts no
per-row Python objects, and evaluates the numerically stable haversine/`atan2` formula
in one compiled loop. Scalar `great_circle_distance` uses the same Mojo implementation.

## Verification

The pytest suite compares valid index properties, pentagons at five resolutions,
parents, center children, complete child ordering/counts for hexagons and pentagons,
all 16 global dimension rows, and geodesic results against `h3` 4.5.0. Run it with
`pixi run test`.

MIT. See [LICENSE](LICENSE).
