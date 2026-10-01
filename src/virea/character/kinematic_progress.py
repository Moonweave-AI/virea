"""Compact cumulative measurements, without action-specific completion rules."""

from copy import deepcopy
from math import atan2, degrees, dist, hypot, pi


def activity_measurements(program, slot):
    """Project this window once; callers own whether its playback is committed."""
    phase = str(slot["phase_index"])
    value = deepcopy(program.get("motion_progress", {}).get(phase, {}))
    if value.get("last_slot_id") == slot["id"]:
        return value
    value.setdefault("original_activity", deepcopy(program["actions"][int(phase)]))
    value.setdefault("root_path_m", 0.0)
    value.setdefault("joint_path_m", {})
    value.setdefault("heading", dict(net_degrees=0.0, travel_degrees=0.0))
    for window in slot.get("windows", []):
        roots = window.get("root", [])
        for point in roots:
            if "last_root" in value:
                value["root_path_m"] += dist(value["last_root"], point)
            value.setdefault("initial_root", point)
            value["last_root"] = point
        for name, rows in window.get("joints", {}).items():
            previous = value.setdefault("last_joints", {}).get(name)
            path = value["joint_path_m"].get(name, 0.0)
            for point in rows:
                if previous is not None:
                    path += dist(previous, point)
                previous = point
            value["joint_path_m"][name] = path
            value["last_joints"][name] = previous
        heading = value["heading"]
        for x, y, z, w in window.get("rotations", {}).get("hips", []):
            norm = x * x + y * y + z * z + w * w
            if norm < 1e-12:
                continue
            # The hips rotation is global; BodyState.yaw is the scene transform.
            forward_x = 2 * (x * z + w * y) / norm
            forward_z = 1 - 2 * (x * x + y * y) / norm
            if hypot(forward_x, forward_z) < 1e-6:
                continue  # Heading is undefined when the forward axis is vertical.
            angle = atan2(forward_x, forward_z)
            previous = heading.get("last_radians", angle)
            delta = degrees((angle - previous + pi) % (2 * pi) - pi)
            heading["net_degrees"] += delta
            heading["travel_degrees"] += abs(delta)
            heading["minimum_degrees"] = min(
                heading.get("minimum_degrees", 0.0), heading["net_degrees"]
            )
            heading["maximum_degrees"] = max(
                heading.get("maximum_degrees", 0.0), heading["net_degrees"]
            )
            heading.setdefault("initial_degrees", degrees(angle))
            heading["current_degrees"] = degrees(angle)
            heading["last_radians"] = angle
    value["last_slot_id"] = slot["id"]
    value["through_activity_seconds"] = slot["phase_elapsed_end"]
    return value


def progress_evidence(value):
    """Expose measured totals, without private accumulation state."""
    return {
        key: (
            {k: v for k, v in item.items() if k != "last_radians"}
            if key == "heading"
            else item
        )
        for key, item in value.items()
        if key not in {"last_joints", "last_slot_id"}
    }
