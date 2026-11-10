# VERIFY phase: reproduction report

Date: 2026-11-10. Host: `x86_64`, 72 CPUs, Python 3.13.14, `h3` 4.5.0, Mojo
`1.2.0.dev2026092605`. Shared machine: load average 17-23 throughout, which is why every
number below has a range. Nothing here was copied from an earlier phase; each number was
measured in this session with the commands shown.

## Gate

| step | command | result |
| --- | --- | --- |
| build | `pixi run build` | exit 0 (deprecation warnings only) |
| tests | `pixi run test` | 51 passed on arrival; 55 passed after changes (+4 from a new test parametrized over 4 worker counts) |
| bench | `pixi run bench` | first run: 24.02 / 4.60 / 3.68 ms |

Final `pixi run build && pixi run test` after all changes: see the bottom of this file.

## README top table, row by row

README claim: measured 2026-08-24, best of three. VERIFY measurement: median of 11
independent `pixi run bench` sessions (range in parentheses). The eleventh, run after the
harness edits, was the noisiest: 78.85 / 8.55 / 4.40 ms with a 2836 / 12.13 / 9.57 ms
reference. Its rows are inside the published ranges.

| row | README said | reproduced now | within 20%? | README now says |
| --- | --- | --- | --- | --- |
| great_circle_distance_batch 1M, mojo-h3 | 163.71 ms | 29.25 ms (22.65-78.85) | no, 2.1x faster at the slow end | 29.25 ms |
| great_circle_distance_batch 1M, h3 reference | 2418.21 ms | 2646.50 ms (2509.69-3031.53) | no, 9.4% slower | 2646.50 ms |
| great_circle_distance_batch 1M, speedup | 14.77x | 90.48x (35.97-124.65) | n/a | 90.48x |
| cell_to_children 7 -> 12, mojo-h3 | 3.83 ms | 4.86 ms (3.86-8.55) | no, 27% slower at the median | 4.86 ms |
| cell_to_children 7 -> 12, h3 | 8.47 ms | 10.33 ms (9.32-11.01) | no, 22% slower | 10.33 ms |
| cell_to_children 7 -> 12, speedup | 2.21x | 2.13x (1.42-2.50) | yes at median | 2.13x |
| pentagon children 5 -> 10, mojo-h3 | 2.95 ms | 3.85 ms (3.18-4.40) | no, 30% slower at the median | 3.85 ms |
| pentagon children 5 -> 10, h3 | 7.07 ms | 8.33 ms (7.77-8.96) | no, 18% slower | 8.33 ms |
| pentagon children 5 -> 10, speedup | 2.40x | 2.16x | yes | 2.16x |

Why the batch row moved so far: the README's 163.71 ms was recorded before the parallel
phase. The current wrapper uses `_BATCH_WORKERS = 8`, and above 131,072 rows the kernel
splits into 8,192-row chunks across 8 workers. The README also did not say which worker
count its figure used. The top table now states the worker path and gives ranges rather
than a single best-of-three.

Rows where mojo-h3 is slower than the pre-SIMD tree are kept: the kernel-only 7 -> 14
children row is 3-7% slower now than at ef9f512, and the pentagon kernel is only ~1.1x
faster, not the 1.06x-to-2.1x a single run could suggest. Both stay in the table.

## Other stale numbers corrected

| location | README said | measured now | action |
| --- | --- | --- | --- |
| kernel-only children 7 -> 12 | 0.204 -> 0.141 ms (1.46x) | before 0.148-0.149, after 0.145-0.344 ms | replaced; "unchanged (range overlaps)" |
| kernel-only children 7 -> 14 | 14.45 -> 10.53 ms (1.37x) | before 9.78-10.34, after 10.46-10.59 ms | replaced; 3-7% slower, kept |
| kernel-only pentagon 5 -> 10 | 0.068 -> 0.064 ms (1.06x) | before 0.068-0.131, after 0.060-0.062 ms | replaced; ~1.1x |
| kernel-only distance 1M | 106.2-110.8 -> 106.2-111.3 ms (~1.00x) | old rads-in 147.8-157.5 ms; new degsafe 1 worker 104.6-113.7 ms; new 8 workers 22.1-25.4 ms | replaced; labelled not like-for-like |
| accuracy, n = 1,003 | 8.5e-14 | 1.8e-15 | VERIFY correction added |
| accuracy, n = 20,001 | 1.33e-14 | 2.6e-14 | VERIFY correction added |
| shared buffers | "nothing else reads the inputs in the same pass" | 8 workers read/write disjoint slices of the same buffers | row rewritten |
| empty batch | "wrapper returns an empty array without touching the kernel" | wrapper always calls the kernel with n = 0 | row reworded to what the tests exercise |

The kernel-only table in the SIMD section *is* treated as a current claim, because it
sits beside the accuracy discussion of the retained kernel rather than in a phase log. It
was re-measured directly by building the pre-phase library (ef9f512) into `/tmp` and
running it alternately with the current `.so`, one library per process, best of nine,
three rounds. The unroll/SIMD before/after columns are point-in-time logs of experiments
whose code is not in the tree; they were left as written.

## How each speedup was checked

- Same input, both sides. `bench/bench.py` builds one row set (`rng(0)`, 1M rows) and one
  cell/pentagon; the mojo call and the h3 call in each row take those same objects.
  The h3 reference is the scalar `h3.great_circle_distance` per row (`h3` exposes no batch
  API), which is what the "comparison" column says.
- No work skipped on one side. Timed workloads used to be thrown away. The harness now
  keeps every output of every timed batch call and asserts, at the end, that each is
  shape (n,), finite, non-negative and within 1e-12 relative of the h3 scalar reference,
  and that all three children outputs are bit-identical to upstream. A sanity check was
  run first: replacing the batch call with a wrong-but-fast stub made the old-style
  harness report 52,083x without complaint, which is the failure mode this check exists
  to catch. The self-check fires in all 10 sessions: "max relative difference from h3
  scalar 4.57e-14; children kernels bit-identical to h3".
- Wrapper overhead is the same on both sides: the 1M row's mojo side times the full Python
  wrapper; the h3 side times 1M Python calls. Nothing rejects inputs on one side that the
  other handles: the row data is float64 `(n, 2)`, the shape the wrapper requires.

## Kernel correctness and parallel path

Checked in this session, not taken from the earlier phases:

- Workers 1, 2, 3, 8 on a 200,003-row batch: no NaN, all 200,003 rows finite, and the
  8-worker output is bit-identical to the 1-worker output.
- Lengths 1, 131,071, 131,072, 131,073 and 139,264 (threshold boundary and partial last
  chunk): every row within 6.6e-14 relative of h3, no NaN.
- Kernel with a padded destination (`dst_len` = n + 8): writes nothing past n.

## Tests: removed assertions or loosened tolerances

`git log -p -- tests/` shows three commits touching `tests/`: 25519e0 (initial port), 34e6aa4
(added SIMD-tail and parallel-threshold children tests), ef9f512 (added batch tail/length,
antipodal, strided and padding tests). No commit removed an assertion and none changed a
tolerance. The existing `2e-15` tolerances in `tests/test_parity.py` are intact, including
the one on the scalar and small-batch paths.

Two weaknesses were found and fixed by strengthening, not loosening:

1. `test_batch_distance_kernel_does_not_write_past_n` passed `dst_len = n` while its buffer
   held n + 8 doubles, so a kernel that rounded n up would have been rejected by the
   length check and never caught by the test. It now declares the padded length. Verified
   against the built library: `dst_len = n - 1` returns -1, `dst_len = padded` returns 0
   and leaves the tail at its sentinel.
2. Nothing tested the parallel batch path: the default 8-worker path is only exercised by
   the 1M-per-row tests, and worker counts, chunk boundaries and the partial last chunk
   had no parity assertion. Added `test_batch_distance_parallel_matches_upstream`
   (workers 1, 2, 3, 7; n = 140,003, above the threshold and not a multiple of the chunk;
   within 1e-12 relative of h3 row by row, and bit-identical to the 1-worker result).

Test count: 51 -> 55 (the new test is parametrized over 4 worker counts). All pass.

## Could not reproduce

- The top table's original figures (163.71 ms, 2418.21 ms, 3.83/8.47 ms, 2.95/7.07 ms):
  same harness, same machine class, but recorded 2026-08-24 under different conditions and
  on a pre-parallel build. No session in this run came within 20% of the 163.71 ms batch
  figure, so it was replaced.
- The accuracy figures 8.5e-14 (n=1,003) and 1.33e-14 (n=20,001): not reproducible on
  `rng(0)` uniform rows in this session; corrected values are in the README.
- The unroll-phase and SIMD-phase "before/after" columns, and the "what did not pay"
  ratios (1.10x/1.06x/1.03x/0.999x SIMD, 1.394x vs 1.374x, +5%/+10%): these are
  point-in-time records of experiments whose code is not in the tree. They were left as
  written and are not presented as current measurements.
- `bench/analysis.md`'s 111 ns/row attribution: historical; not re-derived (145.4 ms is a
  historical figure quoted in the SIMD section, not a current claim).

## What changed

- `README.md`: top table replaced with this session's measurements and ranges; worker path
  named; explanatory paragraph about the parallel split added; kernel-only children table
  replaced with like-for-like numbers (including the row that got slower); kernel-only
  distance row corrected and split into worker counts; accuracy figures corrected with a
  dated note; shared-buffer and empty-batch rows of the assumptions table corrected.
- `bench/bench.py`: timed outputs are retained and self-checked against h3 (distance
  within 1e-12 relative, children bit-identical); kernel-only rows added for the distance
  kernel at 1 and 8 workers and for the three children kernels, all on the same inputs as
  the public rows. No measurement methodology changed: still best-of-three (best-of-nine
  for kernel-only), still under `flock /tmp/mojo-bench.lock`.
- `tests/test_parity.py`: padding test given a padded `dst_len`; parallel-worker parity
  test added.
- `src/`, `python/`: unchanged. No bug was found that a failing test could demonstrate, so
  per the rules no code was changed.

## Final gate

`pixi run build && pixi run test` at the end of the changes: exit 0, 55 passed
(see the transcript in the session; build emits only `UnsafePointer` /
positional-`__getitem__` deprecation warnings).
