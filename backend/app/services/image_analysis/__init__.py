"""Image Analysis service (spec §8 step 7a): selfie -> five 1-100 skin scores + quality.

Public interface:
    analyze_image(image_b64) -> dict     the service contract (see README.md)
    load_models()                        load models once, e.g. in the FastAPI lifespan
    ImageRejected                        unusable photo; .issues lists why (HTTP 422)
    ModelUnavailable                     a model file is missing (HTTP 503)
"""

from .analyzer import analyze_image, load_models
from .errors import ImageRejected, ModelUnavailable

__all__ = ["ImageRejected", "ModelUnavailable", "analyze_image", "load_models"]
