"""Tracked-front contact response against deterministic SDF solids."""
from __future__ import annotations

import math
from typing import Iterable

from .sdf import BoundarySet, SolidBoundary, Vec3


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: Vec3) -> Vec3:
    n = _norm(a)
    return (0.0, 0.0, 0.0) if n <= 0.0 else _mul(a, 1.0 / n)


def _neighbors(front) -> list[set[int]]:
    out = [set() for _ in front.vertices]
    for i, j, k in front.faces:
        out[i].update((j, k))
        out[j].update((i, k))
        out[k].update((i, j))
    return out


def constrain_velocity(
    point_m: Vec3,
    velocity_m_s: Vec3,
    boundaries: BoundarySet | Iterable[SolidBoundary],
    dt_s: float,
    tolerance_m: float,
) -> tuple[Vec3, float]:
    """Remove predicted inward normal motion while retaining free-slip tangential motion."""
    boundary_set = boundaries if isinstance(boundaries, BoundarySet) else BoundarySet(boundaries)
    corrected = velocity_m_s
    correction_l1 = 0.0
    for boundary in boundary_set:
        distance = boundary.signed_distance(point_m)
        normal = boundary.outward_normal(point_m)
        wall = boundary.wall_velocity_m_s
        relative = _sub(corrected, wall)
        normal_speed = _dot(relative, normal)
        if normal_speed < 0.0 and distance + normal_speed * dt_s < tolerance_m:
            delta = _mul(normal, -normal_speed)
            corrected = _add(corrected, delta)
            correction_l1 += _norm(delta)
    return corrected, correction_l1


def _project_outside(front, boundary_set: BoundarySet, tolerance_m: float) -> tuple[float, float, float]:
    max_pre = 0.0
    max_post = 0.0
    correction_l1 = 0.0
    vertices = list(front.vertices)
    for index, point in enumerate(vertices):
        corrected = point
        for boundary in boundary_set:
            distance = boundary.signed_distance(corrected)
            max_pre = max(max_pre, max(0.0, -distance))
            if distance < tolerance_m:
                closest = boundary.closest_point(corrected)
                normal = boundary.outward_normal(closest)
                projected = _add(closest, _mul(normal, tolerance_m))
                correction_l1 += _norm(_sub(projected, corrected))
                corrected = projected
        vertices[index] = corrected
    front.vertices = vertices
    for point in front.vertices:
        for boundary in boundary_set:
            max_post = max(max_post, max(0.0, -boundary.signed_distance(point)))
    return max_pre, max_post, correction_l1


def _contact_indices(front, boundary: SolidBoundary, tolerance_m: float) -> tuple[int, ...]:
    band = max(4.0 * tolerance_m, 1.0e-12)
    return tuple(
        index
        for index, point in enumerate(front.vertices)
        if boundary.signed_distance(point) <= band
    )


def measure_contact_angle_deg(front, boundary: SolidBoundary, contact_indices: Iterable[int]) -> float | None:
    """Measure the acute film-wall angle from numerical side-face geometry."""
    contacts = set(contact_indices)
    if not contacts:
        return None
    normals: dict[int, list[Vec3]] = {index: [] for index in contacts}
    for i, j, k in front.faces:
        face = (i, j, k)
        contact_count = sum(index in contacts for index in face)
        if contact_count == 0 or contact_count == 3:
            continue
        a, b, c = (front.vertices[index] for index in face)
        face_normal = _unit(_cross(_sub(b, a), _sub(c, a)))
        if _norm(face_normal) <= 0.0:
            continue
        for index in face:
            if index in contacts:
                normals[index].append(face_normal)
    angles: list[float] = []
    for index in sorted(contacts):
        local = normals.get(index, [])
        if not local:
            continue
        average = _unit((
            sum(n[0] for n in local),
            sum(n[1] for n in local),
            sum(n[2] for n in local),
        ))
        wall_normal = boundary.outward_normal(front.vertices[index])
        cosine = min(1.0, max(0.0, abs(_dot(average, wall_normal))))
        angles.append(math.degrees(math.acos(cosine)))
    return sum(angles) / len(angles) if angles else None


def _apply_wetting(front, boundary: SolidBoundary, contacts: tuple[int, ...], tolerance_m: float) -> float:
    target = boundary.wetting.effective_acute_angle_deg
    if target is None or not contacts or boundary.wetting.iterations == 0:
        return 0.0
    target = min(max(target, 1.0), 88.0)
    slope = math.tan(math.radians(target))
    neighbors = _neighbors(front)
    contact_set = set(contacts)
    total_correction = 0.0
    for _ in range(boundary.wetting.iterations):
        proposals: dict[int, list[Vec3]] = {}
        for contact_index in sorted(contact_set):
            contact = front.vertices[contact_index]
            closest = boundary.closest_point(contact)
            normal = boundary.outward_normal(closest)
            for neighbor_index in sorted(neighbors[contact_index]):
                if neighbor_index in contact_set:
                    continue
                neighbor = front.vertices[neighbor_index]
                relative = _sub(neighbor, closest)
                normal_height = _dot(relative, normal)
                tangent = _sub(relative, _mul(normal, normal_height))
                tangent_distance = _norm(tangent)
                if tangent_distance <= max(tolerance_m, 1.0e-15):
                    continue
                if tangent_distance > boundary.wetting.contact_band_m:
                    continue
                desired_height = tangent_distance * slope
                relaxed_height = (
                    normal_height
                    + boundary.wetting.relaxation * (desired_height - normal_height)
                )
                candidate = _add(neighbor, _mul(normal, relaxed_height - normal_height))
                proposals.setdefault(neighbor_index, []).append(candidate)
        if not proposals:
            break
        vertices = list(front.vertices)
        for index in sorted(proposals):
            candidates = proposals[index]
            averaged = (
                sum(point[0] for point in candidates) / len(candidates),
                sum(point[1] for point in candidates) / len(candidates),
                sum(point[2] for point in candidates) / len(candidates),
            )
            total_correction += _norm(_sub(averaged, vertices[index]))
            vertices[index] = averaged
        front.vertices = vertices
        _project_outside(front, BoundarySet((boundary,)), tolerance_m)
    return total_correction


def enforce_front_contact(
    front,
    boundaries: BoundarySet | Iterable[SolidBoundary],
    tolerance_m: float,
    dt_s: float,
    *,
    apply_wetting: bool = True,
) -> dict[str, object]:
    """Project tracked geometry out of solids and optionally relax local wetting angle."""
    if tolerance_m < 0.0:
        raise ValueError("boundary tolerance must be non-negative")
    if dt_s <= 0.0:
        raise ValueError("dt_s must be positive")
    boundary_set = boundaries if isinstance(boundaries, BoundarySet) else BoundarySet(boundaries)
    if not boundary_set:
        return {
            "bubble_id": front.bubble_id,
            "contact_vertex_count": 0,
            "contact_face_count": 0,
            "max_penetration_pre_m": 0.0,
            "max_penetration_post_m": 0.0,
            "position_correction_l1_m": 0.0,
            "velocity_correction_proxy_l1_m_s": 0.0,
            "boundary_ids": [],
            "boundaries": [],
        }

    max_pre, max_post, position_correction = _project_outside(front, boundary_set, tolerance_m)
    per_boundary: list[dict[str, object]] = []
    all_contacts: set[int] = set()
    all_faces: set[int] = set()
    for boundary in boundary_set:
        contacts = _contact_indices(front, boundary, tolerance_m)
        before_angle = measure_contact_angle_deg(front, boundary, contacts)
        wetting_correction = _apply_wetting(front, boundary, contacts, tolerance_m) if apply_wetting else 0.0
        contacts = _contact_indices(front, boundary, tolerance_m)
        measured = measure_contact_angle_deg(front, boundary, contacts)
        target = boundary.wetting.effective_acute_angle_deg
        contact_set = set(contacts)
        face_indices = tuple(
            face_index
            for face_index, face in enumerate(front.faces)
            if any(index in contact_set for index in face)
        )
        all_contacts.update(contacts)
        all_faces.update(face_indices)
        residual = None if target is None or measured is None else abs(measured - target)
        per_boundary.append({
            "boundary_id": boundary.boundary_id,
            "boundary_type": boundary.boundary_type,
            "contact_vertex_indices": list(contacts),
            "contact_vertex_count": len(contacts),
            "contact_face_count": len(face_indices),
            "target_contact_angle_deg": target,
            "measured_contact_angle_deg": measured,
            "contact_angle_residual_deg": residual,
            "pre_wetting_measured_contact_angle_deg": before_angle,
            "wetting_position_correction_l1_m": wetting_correction,
            "tracked_front_normal_condition": "NO_PENETRATION",
            "tracked_front_tangential_condition": "FREE_SLIP",
            "bulk_eulerian_wall_coupling": "NOT_IMPLEMENTED_PERIODIC_GRID",
            "contact_angle_fidelity": "MODELED_LOCAL_GEOMETRIC_LAW" if target is not None else "DISABLED",
        })
        position_correction += wetting_correction

    extra_pre, max_post_after, extra_correction = _project_outside(front, boundary_set, tolerance_m)
    max_pre = max(max_pre, extra_pre)
    max_post = max(max_post, max_post_after)
    position_correction += extra_correction
    return {
        "bubble_id": front.bubble_id,
        "contact_vertex_count": len(all_contacts),
        "contact_face_count": len(all_faces),
        "max_penetration_pre_m": max_pre,
        "max_penetration_post_m": max_post,
        "position_correction_l1_m": position_correction,
        "velocity_correction_proxy_l1_m_s": position_correction / dt_s,
        "boundary_ids": [entry["boundary_id"] for entry in per_boundary if entry["contact_vertex_count"]],
        "boundaries": per_boundary,
    }


def combine_contact_reports(*reports: dict[str, object]) -> dict[str, object]:
    """Combine sequential correction passes without hiding the worst penetration."""
    reports = tuple(report for report in reports if report)
    if not reports:
        return {}
    latest = reports[-1]
    boundary_latest: dict[str, dict[str, object]] = {}
    for report in reports:
        for entry in report.get("boundaries", []):
            boundary_latest[str(entry["boundary_id"])] = dict(entry)
    boundary_entries = [boundary_latest[key] for key in sorted(boundary_latest)]
    boundary_ids = sorted({
        str(boundary_id)
        for report in reports
        for boundary_id in report.get("boundary_ids", [])
    })
    return {
        "bubble_id": latest.get("bubble_id"),
        "contact_vertex_count": max(int(report.get("contact_vertex_count", 0)) for report in reports),
        "contact_face_count": max(int(report.get("contact_face_count", 0)) for report in reports),
        "max_penetration_pre_m": max(float(report.get("max_penetration_pre_m", 0.0)) for report in reports),
        "max_penetration_post_m": max(float(report.get("max_penetration_post_m", 0.0)) for report in reports),
        "position_correction_l1_m": sum(float(report.get("position_correction_l1_m", 0.0)) for report in reports),
        "velocity_correction_proxy_l1_m_s": sum(float(report.get("velocity_correction_proxy_l1_m_s", 0.0)) for report in reports),
        "boundary_ids": boundary_ids,
        "boundaries": boundary_entries,
    }
