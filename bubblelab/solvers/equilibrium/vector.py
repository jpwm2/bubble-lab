"""Small deterministic 3-vector helpers; kept dependency-free for CI portability."""
from __future__ import annotations

import math
from typing import Iterable

Vec3 = tuple[float, float, float]


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def norm(a: Vec3) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec3, *, eps: float = 1.0e-30) -> Vec3:
    length = norm(a)
    if length <= eps:
        raise ValueError("cannot normalize a near-zero vector")
    return scale(a, 1.0 / length)


def mean(values: Iterable[Vec3]) -> Vec3:
    xs = ys = zs = 0.0
    count = 0
    for x, y, z in values:
        xs += x
        ys += y
        zs += z
        count += 1
    if count == 0:
        raise ValueError("cannot average an empty vector collection")
    inv = 1.0 / count
    return (xs * inv, ys * inv, zs * inv)
