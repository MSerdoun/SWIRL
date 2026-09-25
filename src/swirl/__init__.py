"""SWIRL — open-source processing and interpretation of VNIR-SWIR point spectra."""

from swirl._version import __version__
from swirl.core import ProcessingStep, Quantity, SpectralSet, Spectrum
from swirl.io import read, write

__all__ = [
    "ProcessingStep",
    "Quantity",
    "SpectralSet",
    "Spectrum",
    "__version__",
    "read",
    "write",
]
