from __future__ import annotations

SIZE_CURVES: dict[str, list[tuple[int, float]]] = {
    "none": [],
    "pop": [(0, 0.0), (3, 1.18), (6, 1.0)],
    "bounce": [(0, 0.0), (3, 1.3), (6, 0.9), (9, 1.0)],
    "grow": [(0, 0.7), (5, 1.0)],
    "punch": [(0, 1.6), (4, 1.0)],
}

ANIMATIONS = list(SIZE_CURVES)


def size_keys(animation: str, base_size: float, duration_frames: int) -> list[list[float]]:
    curve = SIZE_CURVES.get(animation)
    if curve is None:
        raise ValueError(f"Animación desconocida: {animation}")
    if not curve or duration_frames < 2:
        return []
    last_frame = curve[-1][0]
    squeeze = min(1.0, (duration_frames - 1) / last_frame)
    points: list[list[float]] = []
    for frame, factor in curve:
        scaled = round(frame * squeeze)
        if points and scaled <= points[-1][0]:
            points[-1] = [points[-1][0], round(base_size * factor, 5)]
            continue
        points.append([scaled, round(base_size * factor, 5)])
    return points


def hold_then_switch(first: float, second: float, switch_frame: int) -> list[list[float]]:
    if switch_frame < 2:
        return [[0, second]]
    return [[0, first], [switch_frame - 1, first], [switch_frame, second]]
