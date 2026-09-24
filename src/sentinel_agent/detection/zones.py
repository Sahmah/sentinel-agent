"""Static camera-calibration data: shared between the synthetic scenario
generator and the detector so both agree on where the restricted zone is,
without the detector depending on the synthetic-only scenario module."""

RESTRICTED_ZONE = (200, 60, 100, 140)  # x, y, w, h, in pixels


def point_in_zone(
    point: tuple[int, int], zone: tuple[int, int, int, int] = RESTRICTED_ZONE
) -> bool:
    x, y, w, h = zone
    px, py = point
    return x <= px <= x + w and y <= py <= y + h
