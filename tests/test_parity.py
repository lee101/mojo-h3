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
