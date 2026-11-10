import math

import h3
import numpy as np
import pytest

import mojoh3 as mh3
from mojoh3._lib import lib


@pytest.fixture(scope="module")
def cells():
    coords = [(37.775, -122.418), (51.5072, -0.1276), (-33.8688, 151.2093), (0.0, 0.0)]
    return [h3.latlng_to_cell(lat, lng, res) for lat, lng in coords for res in (0, 1, 5, 9, 14)]


def test_index_conversion_matches_h3(cells):
    for cell in cells:
        assert mh3.str_to_int(cell) == h3.str_to_int(cell)
        assert mh3.int_to_str(h3.str_to_int(cell)) == h3.int_to_str(h3.str_to_int(cell))


def test_index_properties_match_h3(cells):
    for cell in cells:
        assert mh3.get_resolution(cell) == h3.get_resolution(cell)
        assert mh3.get_base_cell_number(cell) == h3.get_base_cell_number(cell)
        assert mh3.is_valid_cell(cell) == h3.is_valid_cell(cell)
        assert mh3.is_pentagon(cell) == h3.is_pentagon(cell)
        assert mh3.is_res_class_III(cell) == h3.is_res_class_III(cell)


def test_validity_rejects_bad_mode_digits_and_pentagon_axis():
    invalid = ["0", "89283082803fffff"]
    # Base cell 4 is a pentagon; its leading K digit (1) is deleted.
    pent_bad = format((1 << 59) | (1 << 52) | (4 << 45) | (1 << 42) | ((1 << 42) - 1), "x")
    for cell in invalid + [pent_bad]:
        assert not h3.is_valid_cell(cell)
        assert not mh3.is_valid_cell(cell)


def test_parent_and_center_child_match_h3(cells):
    for cell in cells:
        res = h3.get_resolution(cell)
        if res:
            assert mh3.cell_to_parent(cell) == h3.cell_to_parent(cell)
            assert mh3.cell_to_parent(cell, 0) == h3.cell_to_parent(cell, 0)
        if res < 15:
            assert mh3.cell_to_center_child(cell) == h3.cell_to_center_child(cell)
            assert mh3.cell_to_center_child(cell, 15) == h3.cell_to_center_child(cell, 15)


@pytest.mark.parametrize("resolution", [0, 1, 3, 7, 15])
def test_pentagons_match_h3(resolution):
    got = mh3.get_pentagons(resolution)
    assert got == h3.get_pentagons(resolution)
    assert all(mh3.is_pentagon(cell) for cell in got)


def test_children_match_h3_for_hexagon_and_pentagon(cells):
    cases = [cells[8], h3.get_pentagons(0)[0], h3.get_pentagons(3)[0]]
    for cell in cases:
        base_res = h3.get_resolution(cell)
        for target in range(base_res, min(base_res + 3, 16)):
            assert mh3.cell_to_children_size(cell, target) == h3.cell_to_children_size(cell, target)
            assert mh3.cell_to_children(cell, target) == h3.cell_to_children(cell, target)


def test_pentagon_children_match_h3_across_five_resolutions():
    cell = h3.get_pentagons(5)[0]
    assert mh3.cell_to_children_size(cell, 10) == h3.cell_to_children_size(cell, 10)
    assert mh3.cell_to_children(cell, 10) == h3.cell_to_children(cell, 10)


def test_children_simd_tail_matches_h3():
    cell = h3.latlng_to_cell(37.775, -122.418, 8)
    assert mh3.cell_to_children(cell, 10) == h3.cell_to_children(cell, 10)


def test_children_parallel_threshold_matches_h3_samples():
    cell = h3.latlng_to_cell(37.775, -122.418, 7)
    target = 14
    got = mh3.cell_to_children(cell, target)
    expected = h3.cell_to_children(cell, target)
    size = len(expected)
    for i in (0, 1, size // 2, size - 2, size - 1):
        assert got[i] == expected[i]


@pytest.mark.parametrize("resolution", range(16))
def test_num_cells_and_average_dimensions_match_h3(resolution):
    assert mh3.get_num_cells(resolution) == h3.get_num_cells(resolution)
    for unit in ("km^2", "m^2"):
        assert mh3.average_hexagon_area(resolution, unit) == pytest.approx(
            h3.average_hexagon_area(resolution, unit), rel=2e-15
        )
    for unit in ("km", "m"):
        assert mh3.average_hexagon_edge_length(resolution, unit) == pytest.approx(
            h3.average_hexagon_edge_length(resolution, unit), rel=2e-8
        )


@pytest.mark.parametrize("unit", ["rads", "km", "m"])
def test_great_circle_distance_matches_h3(unit):
    pairs = [((0, 0), (0, 90)), ((37.775, -122.418), (51.5072, -0.1276)), ((-80, 175), (79, -175))]
    for first, second in pairs:
        assert mh3.great_circle_distance(first, second, unit) == pytest.approx(
            h3.great_circle_distance(first, second, unit), rel=2e-15
        )


def test_batch_distance_matches_h3_scalar_reference():
    rng = np.random.default_rng(4)
    first = np.column_stack((rng.uniform(-89, 89, 1003), rng.uniform(-180, 180, 1003)))
    second = np.column_stack((rng.uniform(-89, 89, 1003), rng.uniform(-180, 180, 1003)))
    ref = np.array([h3.great_circle_distance(a, b, "km") for a, b in zip(first, second)])
    assert mh3.great_circle_distance_batch(first, second, "km") == pytest.approx(ref, rel=2e-15)


def _scalar_distance_km(rows, other_rows):
    """Per-row h3 scalar reference, so a tail leak can be attributed to one index."""
    return np.array([h3.great_circle_distance(a, b, "km") for a, b in zip(rows, other_rows)])


@pytest.mark.parametrize("n", [0, 1, 2, 3, 4, 5, 7, 8, 9, 1003, 20001])
def test_batch_distance_tail_lengths(n):
    """0, W-1, W, W+1 and large odd n, so every vector-body/tail split is exercised.

    Every row is compared with h3, index by index. A pad probe is what catches a tail
    leak; this test catches a wrong or misaligned row at any length.
    """
    rng = np.random.default_rng(1000 + n)
    first = np.column_stack((rng.uniform(-89, 89, n), rng.uniform(-180, 180, n)))
    second = np.column_stack((rng.uniform(-89, 89, n), rng.uniform(-180, 180, n)))
    got = mh3.great_circle_distance_batch(first, second, "km")
    assert got.shape == (n,)
    if n == 0:
        return
    ref = _scalar_distance_km(first, second)
    assert np.all(np.isfinite(got))
    # The fused kernel subtracts in degrees and scales once, so it is not bit-identical to
    # h3's radians-in form; 1e-13 relative covers that on 20k random rows and still fails
    # a misaligned row by many orders of magnitude.
    assert got == pytest.approx(ref, rel=1e-13, abs=1e-300)


def test_batch_distance_empty_and_antipodal_rows():
    got = mh3.great_circle_distance_batch(np.zeros((0, 2)), np.zeros((0, 2)))
    assert got.shape == (0,)
    pairs = [((0.0, 0.0), (0.0, 0.0)), ((0.0, 0.0), (0.0, 180.0)),
             ((90.0, 0.0), (-90.0, 37.0)), ((89.99999999999999, 0.0), (-89.99999999999999, 179.99999999999997))]
    first = np.array([p[0] for p in pairs])
    second = np.array([p[1] for p in pairs])
    got = mh3.great_circle_distance_batch(first, second, "km")
    assert np.all(np.isfinite(got)) and got.min() >= 0.0
    ref = _scalar_distance_km(first, second)
    assert got == pytest.approx(ref, rel=1e-14, abs=1e-12)


def test_batch_distance_noncontiguous_strided_inputs():
    """The wrapper copies strided views, so the kernel only ever sees contiguous buffers;
    this pins that the copy is reflected in the answer, at a tail length."""
    rng = np.random.default_rng(7)
    wide_a = np.column_stack((rng.uniform(-89, 89, 13), rng.uniform(-89, 89, 13), rng.uniform(-180, 180, 13)))
    wide_b = np.column_stack((rng.uniform(-89, 89, 13), rng.uniform(-89, 89, 13), rng.uniform(-180, 180, 13)))
    a = wide_a[:, ::2]
    b = wide_b[:, ::2]
    assert not a.flags.c_contiguous
    got = mh3.great_circle_distance_batch(a, b, "km")
    assert got == pytest.approx(_scalar_distance_km(a, b), rel=2e-15)


def test_batch_distance_kernel_does_not_write_past_n():
    """A vector body that rounds n up would scribble into the tail of the output buffer."""
    rng = np.random.default_rng(11)
    n, padded = 1003, 1003 + 8
    first = np.column_stack((rng.uniform(-89, 89, n), rng.uniform(-180, 180, n)))
    second = np.column_stack((rng.uniform(-89, 89, n), rng.uniform(-180, 180, n)))
    out = np.full(padded, -12345.0)
    status = lib().mjh_great_circle_distance_batch_degsafe(
        first.ctypes.data, first.size, second.ctypes.data, second.size, n, out.ctypes.data, n,
    )
    assert status == 0
    assert np.all(out[n:] == -12345.0)


def test_error_cases_follow_h3_shape():
    with pytest.raises(mh3.H3CellInvalidError):
        mh3.cell_to_parent("not-a-cell")
    with pytest.raises(mh3.H3ResMismatchError):
        mh3.cell_to_children(h3.get_pentagons(2)[0], 1)
    with pytest.raises(mh3.H3ValueError):
        mh3.great_circle_distance((0, 0), (1, 1), "yards")
    with pytest.raises(ValueError):
        mh3.great_circle_distance_batch(np.zeros((2, 3)), np.zeros((2, 3)))


def test_invalid_cells_do_not_cross_the_ctypes_integer_boundary():
    for cell in ("0", -1, 1 << 63):
        assert not mh3.is_valid_cell(cell)
        assert not mh3.is_res_class_III(cell)
        with pytest.raises(mh3.H3CellInvalidError):
            mh3.get_resolution(cell)
        with pytest.raises(mh3.H3CellInvalidError):
            mh3.get_base_cell_number(cell)


def test_batch_rejects_lossy_dtypes_and_preserves_noncontiguous_inputs():
    a = np.arange(12, dtype=np.float64).reshape(3, 4)[:, ::2]
    b = a + 1
    assert not a.flags.c_contiguous
    assert mh3.great_circle_distance_batch(a, b).shape == (3,)
    with pytest.raises(TypeError):
        mh3.great_circle_distance_batch(a.astype(np.longdouble), b.astype(np.longdouble))
    with pytest.raises(TypeError):
        mh3.great_circle_distance_batch(a.astype(np.float32), b.astype(np.float32))


def test_ffi_kernels_reject_null_or_undersized_output_buffers():
    cell = h3.latlng_to_cell(37.775, -122.418, 7)
    value = mh3.str_to_int(cell)
    size = mh3.cell_to_children_size(cell, 8)
    assert lib().mjh_cell_to_children(value, 8, 0, size) == -2
    assert lib().mjh_cell_to_children(value, 8, 1, size - 1) == -2
    assert lib().mjh_great_circle_distance_batch(0, 0, 0, 0, 1, 0, 0) == -1
