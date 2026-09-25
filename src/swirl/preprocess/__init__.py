"""Pre-processing: operations on spectra, recipes that chain them, and quality control.

Every operation is registered with a parameter model; see :func:`operations` for the list
and each model's ``model_json_schema()`` for its parameters, defaults and descriptions.
"""

from swirl.preprocess.continuum import ContinuumParams, upper_hull
from swirl.preprocess.qc import QCParams, QCResult, run_qc
from swirl.preprocess.recipe import Recipe, RecipeStep, load_recipe, save_recipe
from swirl.preprocess.registry import (
    Operation,
    Params,
    ProcessingError,
    apply,
    get_operation,
    operation,
    operations,
)
from swirl.preprocess.smooth import SmoothParams
from swirl.preprocess.spectral import CropParams, MaskParams, ResampleParams
from swirl.preprocess.splice import SpliceParams, correct_splices

__all__ = [
    "ContinuumParams",
    "CropParams",
    "MaskParams",
    "Operation",
    "Params",
    "ProcessingError",
    "QCParams",
    "QCResult",
    "Recipe",
    "RecipeStep",
    "ResampleParams",
    "SmoothParams",
    "SpliceParams",
    "apply",
    "correct_splices",
    "get_operation",
    "load_recipe",
    "operation",
    "operations",
    "run_qc",
    "save_recipe",
    "upper_hull",
]
