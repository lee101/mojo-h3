"""C ABI for the H3 hierarchy and spherical-distance kernels."""

from std.math import atan2, cos, sin, sqrt

comptime IPtr = UnsafePointer[Int, AnyOrigin[mut=True]]
comptime FPtr = UnsafePointer[Float64, AnyOrigin[mut=True]]

comptime CELL_MODE = 1
comptime MODE_SHIFT = 59
comptime RES_SHIFT = 52
comptime BASE_SHIFT = 45
comptime DIGIT_MASK = 7
comptime EARTH_RADIUS_KM = 6371.007180918475


def resolution(h: Int) -> Int:
    return (h >> RES_SHIFT) & 15


def digit(h: Int, r: Int) -> Int:
    return (h >> (3 * (15 - r))) & DIGIT_MASK


def set_digit(h: Int, r: Int, d: Int) -> Int:
    var mask = DIGIT_MASK << (3 * (15 - r))
    return (h & ~mask) | (d << (3 * (15 - r)))


def is_pentagon_base(base: Int) -> Bool:
    return base == 4 or base == 14 or base == 24 or base == 38 or base == 49 or base == 58 or base == 63 or base == 72 or base == 83 or base == 97 or base == 107 or base == 117


def valid_cell(h: Int) -> Bool:
    if h < 0 or ((h >> MODE_SHIFT) & 15) != CELL_MODE or ((h >> 56) & 7) != 0:
        return False
    var res = resolution(h)
    var base = (h >> BASE_SHIFT) & 127
    if res > 15 or base > 121:
        return False
    for r in range(1, 16):
        var d = digit(h, r)
        if r <= res:
            if d > 6:
                return False
        elif d != 7:
            return False
    if is_pentagon_base(base):
        for r in range(1, res + 1):
            var d = digit(h, r)
            if d == 0:
                continue
            if d == 1:
                return False
            break
    return True


def pentagon(h: Int) -> Bool:
    if not valid_cell(h) or not is_pentagon_base((h >> BASE_SHIFT) & 127):
        return False
    for r in range(1, resolution(h) + 1):
        if digit(h, r) != 0:
            return False
    return True


def with_resolution(h: Int, target: Int) -> Int:
    return (h & ~(15 << RES_SHIFT)) | (target << RES_SHIFT)


def pow7(n: Int) -> Int:
    var value = 1
    for _ in range(n):
        value *= 7
    return value


def child_count(h: Int, target: Int) -> Int:
    var delta = target - resolution(h)
    if delta < 0:
        return 0
    if not pentagon(h):
        return pow7(delta)
    return 1 + 5 * (pow7(delta) - 1) / 6


def has_pentagon_deleted_direction(h: Int, current: Int) -> Bool:
    if not is_pentagon_base((h >> BASE_SHIFT) & 127):
        return False
    for r in range(1, current + 1):
        var d = digit(h, r)
        if d != 0:
            return False
    return True


def distance_rads(lat1: Float64, lng1: Float64, lat2: Float64, lng2: Float64) -> Float64:
    var dlat = (lat2 - lat1) * 0.5
    var dlng = (lng2 - lng1) * 0.5
    var a = sin(dlat) * sin(dlat) + cos(lat1) * cos(lat2) * sin(dlng) * sin(dlng)
    if a > 1.0:
        a = 1.0
    return 2.0 * atan2(sqrt(a), sqrt(1.0 - a))


@export("mjh_get_resolution")
def mjh_get_resolution(h: Int) abi("C") -> Int:
    return resolution(h)


@export("mjh_get_base_cell")
def mjh_get_base_cell(h: Int) abi("C") -> Int:
    return (h >> BASE_SHIFT) & 127


@export("mjh_is_valid_cell")
def mjh_is_valid_cell(h: Int) abi("C") -> Int:
    return 1 if valid_cell(h) else 0


@export("mjh_is_pentagon")
def mjh_is_pentagon(h: Int) abi("C") -> Int:
    return 1 if pentagon(h) else 0


@export("mjh_cell_to_parent")
def mjh_cell_to_parent(h: Int, target: Int) abi("C") -> Int:
    var current = resolution(h)
    if not valid_cell(h) or target < 0 or target > current:
        return 0
    var parent = with_resolution(h, target)
    for r in range(target + 1, 16):
        parent = set_digit(parent, r, 7)
    return parent


@export("mjh_cell_to_center_child")
def mjh_cell_to_center_child(h: Int, target: Int) abi("C") -> Int:
    var current = resolution(h)
    if not valid_cell(h) or target < current or target > 15:
        return 0
    var child = with_resolution(h, target)
    for r in range(current + 1, target + 1):
        child = set_digit(child, r, 0)
    return child


@export("mjh_cell_to_children_size")
def mjh_cell_to_children_size(h: Int, target: Int) abi("C") -> Int:
    if not valid_cell(h) or target < resolution(h) or target > 15:
        return -1
    return child_count(h, target)


@export("mjh_cell_to_children")
def mjh_cell_to_children(h: Int, target: Int, dst_addr: Int, dst_len: Int) abi("C") -> Int:
    if not valid_cell(h) or target < resolution(h) or target > 15:
        return -1
    var required = child_count(h, target)
    if dst_addr == 0 or dst_len < required:
        return -2
    var dst = IPtr(unsafe_from_address=dst_addr)
    var current = resolution(h)
    var span = pow7(target - current)
    var written = 0
    var starts_in_deleted_direction = has_pentagon_deleted_direction(h, current)
    for code in range(span):
        var value = with_resolution(h, target)
        var digits = code
        var valid = True
        for r in range(target, current, -1):
            var d = digits % 7
            digits /= 7
            if starts_in_deleted_direction and d == 1 and digits == 0:
                valid = False
            value = set_digit(value, r, d)
        if valid:
            dst[written] = value
            written += 1
    return written


@export("mjh_great_circle_distance")
def mjh_great_circle_distance(lat1: Float64, lng1: Float64, lat2: Float64, lng2: Float64) abi("C") -> Float64:
    return distance_rads(lat1, lng1, lat2, lng2)


@export("mjh_great_circle_distance_batch")
def mjh_great_circle_distance_batch(a_addr: Int, a_len: Int, b_addr: Int, b_len: Int, n: Int, dst_addr: Int, dst_len: Int) abi("C") -> Int:
    if n < 0 or a_len < 2 * n or b_len < 2 * n or dst_len < n:
        return -1
    if n > 0 and (a_addr == 0 or b_addr == 0 or dst_addr == 0):
        return -1
    var a = FPtr(unsafe_from_address=a_addr)
    var b = FPtr(unsafe_from_address=b_addr)
    var dst = FPtr(unsafe_from_address=dst_addr)
    for i in range(n):
        dst[i] = distance_rads(a[2 * i], a[2 * i + 1], b[2 * i], b[2 * i + 1])
    return 0
