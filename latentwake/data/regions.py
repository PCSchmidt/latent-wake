"""Geographic bounding boxes for cropping national AIS files.

Boxes are deliberately loose: it is cheaper to crop a little extra water now
than to re-download a quarter of national files because a lane was cut off.
Refine them after looking at the first day's tracks on a map.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BBox:
    name: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    description: str = ""

    def __post_init__(self) -> None:
        if not (-90 <= self.lat_min < self.lat_max <= 90):
            raise ValueError(f"{self.name}: bad latitude range")
        if not (-180 <= self.lon_min < self.lon_max <= 180):
            raise ValueError(f"{self.name}: bad longitude range")

    def contains(self, lat: float, lon: float) -> bool:
        return self.lat_min <= lat <= self.lat_max and self.lon_min <= lon <= self.lon_max

    def grid_shape(self, cell_deg: float = 0.05) -> tuple[int, int]:
        """Rows and columns of a regular grid over the box (0.05 deg is about 5 km)."""
        rows = int(np.ceil((self.lat_max - self.lat_min) / cell_deg))
        cols = int(np.ceil((self.lon_max - self.lon_min) / cell_deg))
        return rows, cols

    def n_cells(self, cell_deg: float = 0.05) -> int:
        rows, cols = self.grid_shape(cell_deg)
        return rows * cols

    def cell_index(self, lat, lon, cell_deg: float = 0.05) -> np.ndarray:
        """Grid cell id for each position; positions outside the box clip to the edge cells."""
        rows, cols = self.grid_shape(cell_deg)
        r = np.clip(((np.asarray(lat) - self.lat_min) / cell_deg).astype(np.int64), 0, rows - 1)
        c = np.clip(((np.asarray(lon) - self.lon_min) / cell_deg).astype(np.int64), 0, cols - 1)
        return (r * cols + c).astype(np.int32)


REGIONS: dict[str, BBox] = {
    # Chesapeake Bay from the Susquehanna flats to the bay mouth, the lower
    # Potomac, Hampton Roads (Norfolk, Newport News, Portsmouth), and the
    # Cape Henry approach lanes. The east edge stops short of the Delmarva
    # Atlantic coast. Approximate; adjust after the first look at the data.
    "chesapeake": BBox(
        name="chesapeake",
        lat_min=36.60,
        lat_max=39.70,
        lon_min=-77.40,
        lon_max=-75.40,
        description="Chesapeake Bay and Hampton Roads, including Cape Henry approaches",
    ),
}


def get_region(name: str) -> BBox:
    try:
        return REGIONS[name]
    except KeyError:
        raise KeyError(f"Unknown region {name!r}. Known: {sorted(REGIONS)}") from None
