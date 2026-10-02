"""Skin-type classifier: EfficientNet-B0 fine-tuned on aligned face crops (Part 3).

Optional at runtime. If PyTorch isn't installed or the trained weights are missing, the
service still runs and returns skin_type_prediction = null. Inference uses the GPU when
one is available and falls back to the CPU automatically.

The preprocessing in classifier_input() is shared with train_skin_type.py, so training
and serving see identically prepared images.
"""

import threading
from pathlib import Path

import cv2
import numpy as np

from .face import AlignedFace

WEIGHTS_DIR = Path(__file__).resolve().parent / "weights"
WEIGHTS_PATH = WEIGHTS_DIR / "skin_type_efficientnet_b0.pt"

INPUT_SIZE = 224
# Serve a trained classifier only if it is credibly better than guessing on its held-out
# test split: the lower end of its test macro-F1 95% CI must exceed chance (1 / number of
# labels). Otherwise skin_type_prediction stays null rather than returning random labels.
# Set to False to serve regardless (e.g. to demo the plumbing).
REQUIRE_ABOVE_CHANCE = True
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def classifier_input(aligned: AlignedFace) -> np.ndarray:
    """The aligned face (eyes level, canonical scale) letterboxed to a square and resized
    to INPUT_SIZE. Returns RGB uint8, INPUT_SIZE x INPUT_SIZE x 3."""
    image = aligned.image
    height, width = image.shape[:2]
    side = max(height, width)
    canvas = np.zeros((side, side, 3), dtype=np.uint8)
    top, left = (side - height) // 2, (side - width) // 2
    canvas[top : top + height, left : left + width] = image
    square = cv2.resize(canvas, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(square, cv2.COLOR_BGR2RGB)


class SkinTypeClassifier:
    def __init__(self, weights_path: Path, device: str | None = None):
        import torch
        import torchvision

        # weights_only=True: the checkpoint may hold only tensors and plain data, never
        # arbitrary pickled objects.
        checkpoint = torch.load(weights_path, map_location="cpu", weights_only=True)
        self.labels: list[str] = list(checkpoint["labels"])
        self.version: str = checkpoint["version"]
        self.test_macro_f1: float | None = checkpoint.get("test_macro_f1")
        self.test_macro_f1_ci: tuple[float, float] | None = (
            tuple(checkpoint["test_macro_f1_ci"]) if "test_macro_f1_ci" in checkpoint else None
        )
        model = torchvision.models.efficientnet_b0(weights=None, num_classes=len(self.labels))
        model.load_state_dict(checkpoint["state_dict"])
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self._model = model.to(self.device).eval()
        self._mean = torch.tensor(IMAGENET_MEAN, device=self.device).view(1, 3, 1, 1)
        self._std = torch.tensor(IMAGENET_STD, device=self.device).view(1, 3, 1, 1)
        self._torch = torch
        self._lock = threading.Lock()  # one model shared by the request threadpool

    def predict(self, aligned: AlignedFace) -> tuple[str, float]:
        """(most likely label, its softmax probability)."""
        torch = self._torch
        rgb = classifier_input(aligned)
        batch = torch.from_numpy(rgb).to(self.device).permute(2, 0, 1).unsqueeze(0).float()
        batch = (batch / 255.0 - self._mean) / self._std
        with self._lock, torch.inference_mode():
            probabilities = torch.softmax(self._model(batch), dim=1)[0]
        best = int(probabilities.argmax())
        return self.labels[best], round(float(probabilities[best]), 4)


def load_skin_type_classifier(
    weights_path: Path = WEIGHTS_PATH,
) -> tuple[SkinTypeClassifier | None, str]:
    """(classifier or None, human-readable status for the startup log)."""
    if not weights_path.is_file():
        return None, (
            f"no trained weights at {weights_path}; skin_type_prediction will be null. "
            "Train them with `python -m app.services.image_analysis.train_skin_type`."
        )
    try:
        classifier = SkinTypeClassifier(weights_path)
    except ImportError:
        return None, "PyTorch is not installed; skin_type_prediction will be null."
    chance = 1 / len(classifier.labels)
    ci = classifier.test_macro_f1_ci
    if REQUIRE_ABOVE_CHANCE and (ci is None or ci[0] <= chance):
        measured = (
            f"held-out test macro-F1 {classifier.test_macro_f1:.3f} (95% CI {ci[0]:.3f}-{ci[1]:.3f})"
            if ci
            else "no held-out test result in the checkpoint"
        )
        return None, (
            f"skin-type classifier {classifier.version} NOT served: {measured} is not credibly "
            f"above chance ({chance:.2f}), so skin_type_prediction will be null. "
            "See README.md, 'Skin-type classifier'."
        )
    return classifier, (
        f"skin-type classifier {classifier.version} loaded on {classifier.device} "
        f"(labels: {', '.join(classifier.labels)})"
    )
