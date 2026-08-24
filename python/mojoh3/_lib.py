"""Build and load the standalone Mojo kernels."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.environ.get("MOJO_H3_LIB") or os.path.join(ROOT, "dist", "libmojo-h3.so")
I = ctypes.c_int64
F = ctypes.c_double

_SIGNATURES = {
    "mjh_get_resolution": ([I], I),
    "mjh_get_base_cell": ([I], I),
    "mjh_is_valid_cell": ([I], I),
    "mjh_is_pentagon": ([I], I),
    "mjh_cell_to_parent": ([I, I], I),
    "mjh_cell_to_center_child": ([I, I], I),
    "mjh_cell_to_children_size": ([I, I], I),
    "mjh_cell_to_children": ([I, I, I, I], I),
    "mjh_cell_to_children_range": ([I, I, I, I, I, I], I),
    "mjh_great_circle_distance": ([F, F, F, F], F),
    "mjh_great_circle_distance_batch": ([I, I, I, I, I, I, I], I),
}


def build(force: bool = False) -> str:
    if os.environ.get("MOJO_H3_LIB") and os.path.exists(LIB) and not force:
        return LIB
    source = os.path.join(ROOT, "src", "capi.mojo")
    if not force and os.path.exists(LIB) and os.path.getmtime(LIB) >= os.path.getmtime(source):
        return LIB
    mojo = shutil.which("mojo")
    if not mojo:
        raise RuntimeError("mojo not found; run through pixi or set MOJO_H3_LIB")
    os.makedirs(os.path.dirname(LIB), exist_ok=True)
    proc = subprocess.run(
        [mojo, "build", "--emit", "shared-lib", source, "-o", LIB],
        text=True, capture_output=True, timeout=1800,
    )
    if proc.returncode or not os.path.exists(LIB):
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    return LIB


_loaded = None


def lib() -> ctypes.CDLL:
    global _loaded
    if _loaded is None:
        _loaded = ctypes.CDLL(build())
        for name, (argtypes, restype) in _SIGNATURES.items():
            fn = getattr(_loaded, name)
            fn.argtypes, fn.restype = argtypes, restype
    return _loaded
