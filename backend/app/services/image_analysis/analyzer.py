"""Image Analysis service: analyze_image(image_b64) -> Skin Profile scores.

Models are loaded once (FastAPI lifespan calls load_models() at startup) and reused for
every request. Images are processed in memory only and never written anywhere.
"""

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import quality, scoring
from . import scoring_config as cfg
from .decode import decode_image, to_canonical_resolution
from .errors import ImageRejected, ModelUnavailable
from .face import FaceDetector, align_face
from .lighting import Lighting
from .lighting import measure as measure_lighting
from .skin_type import WEIGHTS_PATH, load_skin_type_classifier

SERVICE_VERSION = "1.1.0"  # 1.1.0: canonical 720 px resolution before any check (7b-ii)

SERVICE_DIR = Path(__file__).resolve().parent
MODELS_DIR = SERVICE_DIR / "models"
FACE_MODEL_PATH = MODELS_DIR / "face_landmarker.task"

MISSING_FACE_MODEL = (
    "Face landmark model not found at {path}. Download it once with "
    "`python -m app.services.image_analysis.download_models` (run from backend/), "
    "then retry — no restart needed."
)

# Readable score name -> region weights, for the "not enough skin visible" check.
SCORE_REGIONS = {
    "redness": cfg.REDNESS_REGIONS,
    "acne": cfg.ACNE_REGIONS,
    "pigmentation": cfg.PIGMENT_REGIONS,
    "pores": cfg.PORE_REGIONS,
    "wrinkles": cfg.WRINKLE_REGIONS,
}


@dataclass
class AnalysisResult:
    scores: dict[str, int]
    warnings: list[str]
    model_version: str
    skin_type: str | None = None
    skin_type_confidence: float | None = None
    skin_type_labels_supported: list[str] = field(default_factory=list)
    raw_features: dict[str, float] = field(default_factory=dict)
    lighting: Lighting | None = None  # measurements behind the lighting checks
    timings_ms: dict[str, float] = field(default_factory=dict)
    debug: dict[str, np.ndarray] = field(default_factory=dict)

    def to_response(self) -> dict:
        """The service contract (see README.md)."""
        return {
            **self.scores,
            "skin_type_prediction": self.skin_type,
            "skin_type_confidence": self.skin_type_confidence,
            "skin_type_labels_supported": list(self.skin_type_labels_supported),
            "quality": {"ok": True, "issues": list(self.warnings)},
            "model_version": self.model_version,
        }


class ImageAnalyzer:
    def __init__(
        self, face_model_path: Path = FACE_MODEL_PATH, skin_type_weights: Path = WEIGHTS_PATH
    ):
        if not face_model_path.is_file():
            raise ModelUnavailable(MISSING_FACE_MODEL.format(path=face_model_path))
        try:
            self.face_detector = FaceDetector(face_model_path)
        except Exception as exc:  # corrupt/partial download
            raise ModelUnavailable(
                f"Face landmark model at {face_model_path} failed to load ({exc}). "
                "Delete it and download it again."
            ) from exc
        # Optional: None (prediction null) if the weights or PyTorch are missing.
        self.skin_type_classifier, self.skin_type_status = load_skin_type_classifier(
            skin_type_weights
        )

    @property
    def model_version(self) -> str:
        skin_type = (
            "none" if self.skin_type_classifier is None else self.skin_type_classifier.version
        )
        return f"image-analysis-{SERVICE_VERSION}+{cfg.SCORING_VERSION}+skin-type-{skin_type}"

    def analyze(
        self, bgr: np.ndarray, debug: bool = False, lighting_gate: bool = True
    ) -> AnalysisResult:
        """Analyse a decoded BGR photo. Raises ImageRejected for unusable photos.

        `lighting_gate=False` is for the evaluation scripts only: dim / uneven lighting
        become warnings instead of rejections, so before/after comparisons can score the
        photos the gate rejects. The public analyze_image() never turns the gate off.
        """
        timer = _Timer()
        # Every caller (the API, the dev and evaluation scripts) gets the same canonical
        # resolution before any check or measurement.
        bgr = to_canonical_resolution(bgr)
        hard = quality.check_whole_image(bgr)
        if hard:
            raise ImageRejected(hard)

        faces = self.face_detector.detect(bgr)
        timer.lap("face_detection")
        hard, warnings = quality.check_framing(faces, bgr.shape)
        if hard:
            raise ImageRejected(hard)

        aligned = align_face(bgr, faces[0])
        maps = scoring.build_maps(aligned)
        light = measure_lighting(aligned, maps, bgr)
        hard, soft = quality.check_face_photometry(maps, light, lighting_gate)
        warnings += soft
        if hard:
            raise ImageRejected(hard)

        hard, soft, usable = quality.check_region_coverage(
            scoring.region_coverage(maps), SCORE_REGIONS
        )
        warnings += soft
        if hard:
            raise ImageRejected(hard)
        timer.lap("normalisation_and_quality")

        measurement = scoring.measure(maps, usable, debug=debug)
        timer.lap("scoring")

        skin_type, confidence, supported = None, None, []
        if self.skin_type_classifier is not None:
            skin_type, confidence = self.skin_type_classifier.predict(aligned)
            supported = self.skin_type_classifier.labels
            timer.lap("skin_type")

        result = AnalysisResult(
            scores=measurement.scores,
            warnings=warnings,
            model_version=self.model_version,
            skin_type=skin_type,
            skin_type_confidence=confidence,
            skin_type_labels_supported=supported,
            raw_features=measurement.raw,
            lighting=light,
            debug=(
                {
                    "aligned": aligned.image,
                    "skin": maps.skin,
                    "region_masks": maps.polygons,
                    **measurement.debug,
                }
                if debug
                else {}
            ),
        )
        result.timings_ms = timer.laps
        return result


class _Timer:
    def __init__(self):
        self._last = time.perf_counter()
        self.laps: dict[str, float] = {}

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.laps[name] = round((now - self._last) * 1000, 1)
        self._last = now


_analyzer: ImageAnalyzer | None = None
_load_lock = threading.Lock()


def load_models() -> ImageAnalyzer:
    """Load models once; later calls return the same instance.

    Raises ModelUnavailable if a model file is missing. Not cached on failure, so
    downloading the model makes the next request succeed without a restart.
    """
    global _analyzer
    if _analyzer is None:
        with _load_lock:
            if _analyzer is None:
                _analyzer = ImageAnalyzer()
    return _analyzer


def analyze_image(image_b64: str) -> dict:
    """Analyse a base64 JPEG/PNG (bare or as a data URL) and return the service contract.

    Raises ImageRejected (-> HTTP 422) for photos that can't be scored reliably and
    ModelUnavailable (-> HTTP 503) if the face model hasn't been downloaded.
    """
    analyzer = load_models()
    return analyzer.analyze(decode_image(image_b64)).to_response()
