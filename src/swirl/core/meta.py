"""Conventional metadata keys.

Metadata stays a free-form mapping so any instrument field can be kept, but these keys
have a fixed meaning across SWIRL (readers fill them, the GUI and exports rely on them).
"""

SAMPLE_ID = "sample_id"
HOLE_ID = "hole_id"
DEPTH_FROM = "depth_from"
"""Top of the sampled interval, metres along hole."""
DEPTH_TO = "depth_to"
"""Bottom of the sampled interval, metres along hole."""
EASTING = "easting"
NORTHING = "northing"
CRS = "crs"
INSTRUMENT = "instrument"
ACQUIRED_AT = "acquired_at"
"""ISO 8601 timestamp."""
SOURCE_PATH = "source_path"
"""File the spectrum was read from."""
SOURCE_COLUMN = "source_column"
"""Column name or index inside ``source_path`` (multi-spectrum files)."""
