"""A fast, standalone subset of the H3 4.x Python API."""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
import numpy as np

from ._lib import lib

__version__ = "0.1.0"

EARTH_RADIUS_KM = 6371.007180918475
_PENTAGON_BASE_CELLS = (4, 14, 24, 38, 49, 58, 63, 72, 83, 97, 107, 117)
_CHILD_PARALLEL_THRESHOLD = 262_144
_CHILD_CHUNK = 131_072
_AREA_KM2 = (
    4357449.416078383, 609788.4417941332, 86801.7803989972,
    12393.43465508816, 1770.347654491307, 252.9038581819449,
    36.12906216441245, 5.161293359717191, 0.7373275975944177,
    0.1053325134272067, 0.01504750190766435, 0.002149643129451879,
    0.000307091875631606, 0.000043870267947282954,
    0.000006267181135324312, 0.000000895311590760579,
)
_EDGE_KM = (
    1281.256011, 483.0568391, 182.5129565, 68.97922179, 26.07175968,
    9.85409099, 3.724532667, 1.406475763, 0.53141401, 0.200786148,
    0.075863783, 0.028663897, 0.010830188, 0.00409201, 0.0015461,
    0.000584169,
)


class H3BaseException(ValueError):
    pass


class H3CellInvalidError(H3BaseException):
    pass


class H3ResDomainError(H3BaseException):
    pass


class H3ValueError(H3BaseException):
    pass


def str_to_int(h):
    return int(h, 16) if isinstance(h, str) else int(h)


def int_to_str(x):
    return format(int(x), "x")


def _int_cell(h) -> int:
    value = str_to_int(h)
    if not 0 <= value < 1 << 63:
        raise ValueError("H3 cell integer is outside the C ABI range")
    return value


def _cell(h: int) -> str:
    return int_to_str(h)


def _require_cell(h) -> int:
    try:
        value = _int_cell(h)
    except (TypeError, ValueError) as exc:
        raise H3CellInvalidError(f"Invalid H3 cell: {h}") from exc
    if not lib().mjh_is_valid_cell(value):
        raise H3CellInvalidError(f"Invalid H3 cell: {h}")
    return value


def _require_res(res) -> int:
    if not isinstance(res, int) or not 0 <= res <= 15:
        raise H3ResDomainError(f"Resolution must be between 0 and 15, got {res!r}")
    return res


def get_resolution(h):
    return int(lib().mjh_get_resolution(_require_cell(h)))


def get_base_cell_number(h):
    return int(lib().mjh_get_base_cell(_require_cell(h)))


def is_valid_cell(h):
    try:
        return bool(lib().mjh_is_valid_cell(_int_cell(h)))
    except (TypeError, ValueError):
        return False


def is_pentagon(h):
    try:
        return bool(lib().mjh_is_pentagon(_int_cell(h)))
    except (TypeError, ValueError):
        return False


def is_res_class_III(h):
    try:
        return bool(get_resolution(h) & 1)
    except H3CellInvalidError:
        return False


def cell_to_parent(h, res=None):
    value = _require_cell(h)
    current = get_resolution(value)
    target = current - 1 if res is None else _require_res(res)
    if target > current:
        raise H3ResMismatchError("Parent resolution must not exceed cell resolution")
    if target < 0:
        raise H3ResDomainError("Resolution must be between 0 and 15")
    return _cell(lib().mjh_cell_to_parent(value, target))


class H3ResMismatchError(H3BaseException):
    pass


def cell_to_center_child(h, res=None):
    value = _require_cell(h)
    current = get_resolution(value)
    target = current + 1 if res is None else _require_res(res)
    if target < current:
        raise H3ResMismatchError("Child resolution must not be below cell resolution")
    return _cell(lib().mjh_cell_to_center_child(value, target))


def cell_to_children_size(h, res=None):
    value = _require_cell(h)
    current = get_resolution(value)
    target = current + 1 if res is None else _require_res(res)
    if target < current:
        raise H3ResMismatchError("Child resolution must not be below cell resolution")
    return int(lib().mjh_cell_to_children_size(value, target))


def cell_to_children(h, res=None):
    value = _require_cell(h)
    current = (value >> 52) & 15
    target = current + 1 if res is None else _require_res(res)
    if target < current:
        raise H3ResMismatchError("Child resolution must not be below cell resolution")
    size = int(lib().mjh_cell_to_children_size(value, target))
    raw = np.empty(size, dtype=np.int64)
    kernel = lib()
    if size >= _CHILD_PARALLEL_THRESHOLD and not kernel.mjh_is_pentagon(value):
        ranges = [(start, min(start + _CHILD_CHUNK, size))
                  for start in range(0, size, _CHILD_CHUNK)]

        def fill(bounds):
            start, end = bounds
            return kernel.mjh_cell_to_children_range(
                value, target, raw.ctypes.data, raw.size, start, end,
            )

        with ThreadPoolExecutor(max_workers=min(8, len(ranges))) as pool:
            counts = list(pool.map(fill, ranges))
        written = sum(counts) if all(count >= 0 for count in counts) else -1
    else:
        written = kernel.mjh_cell_to_children(value, target, raw.ctypes.data, raw.size)
    if written != size:
        raise RuntimeError("Mojo child-generation kernel failed")
    return [format(x, "x") for x in raw.tolist()]


def get_num_cells(res):
    return 2 + 120 * 7 ** _require_res(res)


def get_pentagons(res):
    res = _require_res(res)
    suffix = (1 << (3 * (15 - res))) - 1
    return [_cell((1 << 59) | (res << 52) | (base << 45) | suffix)
            for base in _PENTAGON_BASE_CELLS]


def average_hexagon_area(res, unit="km^2"):
    area = _AREA_KM2[_require_res(res)]
    if unit == "km^2":
        return area
    if unit == "m^2":
        return area * 1_000_000
    raise H3ValueError(f"Unknown unit: {unit}")


def average_hexagon_edge_length(res, unit="km"):
    length = _EDGE_KM[_require_res(res)]
    if unit == "km":
        return length
    if unit == "m":
        return length * 1_000
    raise H3ValueError(f"Unknown unit: {unit}")


def great_circle_distance(latlng1, latlng2, unit="km"):
    lat1, lng1 = latlng1
    lat2, lng2 = latlng2
    radians = lib().mjh_great_circle_distance(
        math.radians(lat1), math.radians(lng1), math.radians(lat2), math.radians(lng2),
    )
    if unit == "rads":
        return radians
    if unit == "km":
        return radians * EARTH_RADIUS_KM
    if unit == "m":
        return radians * EARTH_RADIUS_KM * 1_000
    raise H3ValueError(f"Unknown unit: {unit}")


def great_circle_distance_batch(latlng1, latlng2, unit="km"):
    """Vectorized great-circle distances for arrays shaped ``(n, 2)`` in degrees."""
    if unit not in ("rads", "km", "m"):
        raise H3ValueError(f"Unknown unit: {unit}")
    a = np.asarray(latlng1)
    b = np.asarray(latlng2)
    if a.ndim != 2 or a.shape[1] != 2 or b.shape != a.shape:
        raise ValueError("latlng1 and latlng2 must both have shape (n, 2)")
    if a.dtype != np.dtype(np.float64) or b.dtype != np.dtype(np.float64):
        raise TypeError("latitude/longitude arrays must have dtype float64")
    # These local arrays remain strongly referenced until the C call returns.
    a = np.ascontiguousarray(a)
    b = np.ascontiguousarray(b)
    radians = np.empty(a.shape[0], dtype=np.float64)
    radians_a, radians_b = np.radians(a), np.radians(b)
    status = lib().mjh_great_circle_distance_batch(
        radians_a.ctypes.data, radians_a.size, radians_b.ctypes.data, radians_b.size,
        a.shape[0], radians.ctypes.data, radians.size,
    )
    if status:
        raise RuntimeError("Mojo distance-batch kernel failed")
    if unit == "rads":
        return radians
    if unit == "km":
        return radians * EARTH_RADIUS_KM
    if unit == "m":
        return radians * EARTH_RADIUS_KM * 1_000
    raise AssertionError("validated unit")


__all__ = [
    "H3BaseException", "H3CellInvalidError", "H3ResDomainError",
    "H3ResMismatchError", "H3ValueError", "str_to_int", "int_to_str",
    "is_valid_cell", "get_resolution", "get_base_cell_number", "is_pentagon",
    "is_res_class_III", "cell_to_parent", "cell_to_center_child",
    "cell_to_children_size", "cell_to_children", "get_num_cells", "get_pentagons",
    "average_hexagon_area", "average_hexagon_edge_length", "great_circle_distance",
    "great_circle_distance_batch",
]
