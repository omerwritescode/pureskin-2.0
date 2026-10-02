"""Face detection (MediaPipe Face Landmarker, Tasks API) and alignment to a canonical frame."""

import math
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from . import scoring_config as cfg
from .regions import (
    FACE_OVAL,
    LEFT_EYE_CORNERS,
    LEFT_FACE_EDGE,
    RIGHT_EYE_CORNERS,
    RIGHT_FACE_EDGE,
)


@dataclass
class DetectedFace:
    points: np.ndarray  # (478, 2) landmark pixel coordinates in the input image
    yaw_deg: float  # head turned left/right
    pitch_deg: float  # head tilted up/down
    smile: float  # 0-1, from MediaPipe's mouthSmile blendshapes

    @property
    def width(self) -> float:
        """Face width at cheekbone level, independent of in-plane head tilt."""
        return float(np.linalg.norm(self.points[LEFT_FACE_EDGE] - self.points[RIGHT_FACE_EDGE]))


@dataclass
class AlignedFace:
    image: np.ndarray  # BGR uint8, face rotated level and scaled to CANONICAL_FACE_WIDTH_PX
    points: np.ndarray  # landmarks in aligned coordinates
    valid: np.ndarray  # bool, False where the canvas extends past the original photo


class FaceDetector:
    def __init__(self, model_path: Path):
        # Load from bytes rather than a path: MediaPipe's native loader has trouble with
        # some Windows paths (spaces, non-ASCII), and this keeps it to one file read.
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_buffer=model_path.read_bytes()),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=cfg.MAX_FACES_TO_DETECT,
            min_face_detection_confidence=cfg.FACE_DETECTION_CONFIDENCE,
            min_face_presence_confidence=cfg.FACE_PRESENCE_CONFIDENCE,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        # One graph instance shared by the threadpool; detect() isn't documented as
        # thread-safe, and it takes only a few tens of ms, so serialise it.
        self._lock = threading.Lock()

    def detect(self, bgr: np.ndarray) -> list[DetectedFace]:
        """All faces found, largest first."""
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        with self._lock:
            result = self._landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))

        height, width = bgr.shape[:2]
        faces = []
        for i, landmarks in enumerate(result.face_landmarks):
            points = np.array([[p.x * width, p.y * height] for p in landmarks], dtype=np.float32)
            yaw, pitch = _pose(result.facial_transformation_matrixes[i])
            smile = max(
                (
                    c.score
                    for c in result.face_blendshapes[i]
                    if c.category_name in ("mouthSmileLeft", "mouthSmileRight")
                ),
                default=0.0,
            )
            faces.append(DetectedFace(points, yaw, pitch, float(smile)))
        return sorted(faces, key=lambda f: f.width, reverse=True)


def _pose(matrix) -> tuple[float, float]:
    """Yaw and pitch in degrees from the face's 4x4 transformation matrix."""
    rotation = np.asarray(matrix, dtype=np.float64)[:3, :3]
    yaw = math.degrees(math.asin(float(np.clip(-rotation[2, 0], -1.0, 1.0))))
    pitch = math.degrees(math.atan2(rotation[2, 1], rotation[2, 2]))
    return yaw, pitch


def align_face(bgr: np.ndarray, face: DetectedFace) -> AlignedFace:
    """Rotate so the eyes are level and scale so the face is CANONICAL_FACE_WIDTH_PX wide.

    Every later measurement is in these canonical pixels, which is what makes spot,
    pore and line sizes comparable between a close-up and an arm's-length selfie.
    """
    points = face.points.astype(np.float64)
    source = bgr
    scale = cfg.CANONICAL_FACE_WIDTH_PX / face.width
    if scale < 1.0:
        # Area-average down first: a single rotate+shrink warp would alias fine texture.
        source = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        points = points * (
            source.shape[1] / bgr.shape[1],
            source.shape[0] / bgr.shape[0],
        )
        scale = cfg.CANONICAL_FACE_WIDTH_PX / float(
            np.linalg.norm(points[LEFT_FACE_EDGE] - points[RIGHT_FACE_EDGE])
        )

    right_eye = points[list(RIGHT_EYE_CORNERS)].mean(axis=0)
    left_eye = points[list(LEFT_EYE_CORNERS)].mean(axis=0)
    angle = math.degrees(math.atan2(left_eye[1] - right_eye[1], left_eye[0] - right_eye[0]))
    center = points[FACE_OVAL].mean(axis=0)
    matrix = cv2.getRotationMatrix2D((float(center[0]), float(center[1])), angle, scale)

    moved = points @ matrix[:, :2].T + matrix[:, 2]
    margin = cfg.ALIGN_MARGIN_FRACTION * cfg.CANONICAL_FACE_WIDTH_PX
    top_left = moved[FACE_OVAL].min(axis=0) - margin
    bottom_right = moved[FACE_OVAL].max(axis=0) + margin
    matrix[:, 2] -= top_left
    size = tuple(math.ceil(v) for v in bottom_right - top_left)

    interpolation = cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_LINEAR
    aligned = cv2.warpAffine(source, matrix, size, flags=interpolation, borderValue=(0, 0, 0))
    valid = cv2.warpAffine(
        np.ones(source.shape[:2], dtype=np.uint8), matrix, size, flags=cv2.INTER_NEAREST
    ).astype(bool)
    return AlignedFace(aligned, (moved - top_left).astype(np.float32), valid)
