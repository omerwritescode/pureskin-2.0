"""Skin-type classifier plumbing and the training-data deduplication, on synthetic images.

No dataset, trained weights or real face needed.
"""

import cv2
import numpy as np
import pytest

from app.api.image_analysis import ImageAnalysisResponse
from app.services.image_analysis import skin_type_data as data
from app.services.image_analysis.analyzer import AnalysisResult
from app.services.image_analysis.face import AlignedFace
from app.services.image_analysis.scoring import SCORE_NAMES
from app.services.image_analysis.skin_type import (
    INPUT_SIZE,
    classifier_input,
    load_skin_type_classifier,
)

from .conftest import shapes_image


def _rotate(image, degrees):
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), degrees, 1.0)
    return cv2.warpAffine(image, matrix, (w, h), borderMode=cv2.BORDER_REFLECT)


def _detailed(seed):
    """Shapes plus fine detail, so ORB finds a realistic number of keypoints."""
    image = shapes_image(seed=seed)
    rng = np.random.default_rng(seed + 100)
    for _ in range(400):
        colour = tuple(int(v) for v in rng.integers(20, 235, 3))
        x, y, size = int(rng.integers(0, 640)), int(rng.integers(0, 480)), int(rng.integers(3, 14))
        if rng.random() < 0.5:
            cv2.rectangle(image, (x, y), (x + size, y + size), colour, -1)
        else:
            end = (x + int(rng.integers(-30, 30)), y + int(rng.integers(-30, 30)))
            cv2.line(image, (x, y), end, colour, 2)
    return image


def _crop(image, fraction):
    h, w = image.shape[:2]
    dy, dx = int(h * fraction / 2), int(w * fraction / 2)
    return cv2.resize(image[dy : h - dy, dx : w - dx], (w, h))


# --------------------------------------------------------------------------------------
# Deduplication
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "transform",
    [
        lambda x: x[:, ::-1],
        lambda x: np.rot90(x),
        lambda x: np.rot90(x, 3)[:, ::-1],
        lambda x: np.clip(x * 1.25, 0, 255).astype(np.uint8),
        lambda x: cv2.resize(cv2.resize(x, (640, 360)), (640, 480)),  # stretch
    ],
)
def test_phash_ignores_flips_rotations_recolouring_and_stretch(transform):
    image = shapes_image(seed=11)
    hashes = np.stack(
        [data.phash_dihedral(image), data.phash_dihedral(np.ascontiguousarray(transform(image)))]
    )
    assert data.phash_distances(hashes)[0, 1] <= data.PHASH_MAX_BITS


def test_phash_keeps_different_images_apart():
    hashes = np.stack([data.phash_dihedral(shapes_image(seed=s)) for s in (1, 2, 3)])
    distances = data.phash_distances(hashes)
    assert distances[np.triu_indices(3, k=1)].min() > data.PHASH_MAX_BITS


def test_orb_confirms_recrop_and_rotation_but_not_a_different_image():
    image = _detailed(12)
    copy = _crop(_rotate(image, 12), 0.25)[:, ::-1]  # rotated, re-cropped and mirrored
    other = _detailed(13)
    reference = data.orb_features(image)[0]
    assert data.orb_inliers(reference, data.orb_features(copy)) >= data.ORB_MIN_INLIERS
    assert data.orb_inliers(reference, data.orb_features(other)) < data.ORB_MIN_INLIERS


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "dry_10583924a54a7cbcf5d0_jpg.rf.7c4cb0ac9522f3a0faaf230527e1abe9.jpg",
            "10583924a54a7cbcf5d0",
        ),
        ("combination_-_0bc5ca1194a13cfd7b9a_jpg.rf.0c21ccb4.jpg", "0bc5ca1194a13cfd7b9a"),
        ("oily_021e826dd8fd78c2e8f5-Copy_jpg.rf.233c9ee4.jpg", "021e826dd8fd78c2e8f5"),
    ],
)
def test_filename_id_finds_the_roboflow_source_id(name, expected):
    assert data.filename_id(name) == expected


def test_split_is_stratified_and_never_shares_a_group():
    labels = {g: data.LABELS[g % len(data.LABELS)] for g in range(400)}
    split = data.split_groups(labels, seed=7)
    assert set(split) == set(labels)
    for label in data.LABELS:
        mine = [g for g, lab in labels.items() if lab == label]
        counts = {s: sum(split[g] == s for g in mine) for s in ("train", "val", "test")}
        assert counts == {"train": 70, "val": 15, "test": 15}
    assert data.split_groups(labels, seed=7) == split  # reproducible


# --------------------------------------------------------------------------------------
# Classifier
# --------------------------------------------------------------------------------------


def _aligned(height=380, width=300) -> AlignedFace:
    rng = np.random.default_rng(0)
    image = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
    return AlignedFace(image, np.zeros((478, 2), np.float32), np.ones((height, width), bool))


def test_classifier_input_is_square_rgb_uint8():
    crop = classifier_input(_aligned())
    assert crop.shape == (INPUT_SIZE, INPUT_SIZE, 3) and crop.dtype == np.uint8


def test_missing_weights_disable_the_classifier_with_a_reason(tmp_path):
    classifier, status = load_skin_type_classifier(tmp_path / "missing.pt")
    assert classifier is None and "train_skin_type" in status


def test_checkpoint_round_trip_on_cpu(tmp_path):
    torch = pytest.importorskip("torch")
    torchvision = pytest.importorskip("torchvision")
    from app.services.image_analysis.skin_type import SkinTypeClassifier

    labels = ["combination", "dry", "normal", "oily"]
    model = torchvision.models.efficientnet_b0(weights=None, num_classes=len(labels))
    path = tmp_path / "weights.pt"
    torch.save({"state_dict": model.state_dict(), "labels": labels, "version": "test"}, path)

    classifier = SkinTypeClassifier(path, device="cpu")
    label, confidence = classifier.predict(_aligned())
    assert label in labels and 0.0 <= confidence <= 1.0
    assert classifier.labels == labels


def test_contract_with_a_prediction_validates():
    result = AnalysisResult(
        scores={name: 40 for name in SCORE_NAMES},
        warnings=[],
        model_version="test",
        skin_type="oily",
        skin_type_confidence=0.71,
        skin_type_labels_supported=["combination", "dry", "normal", "oily"],
    )
    ImageAnalysisResponse.model_validate(result.to_response())


def _padded_rotation(image, degrees):
    """Rotate onto a larger black canvas, like Roboflow's rotated copies."""
    h, w = image.shape[:2]
    canvas = cv2.copyMakeBorder(image, h // 3, h // 3, w // 3, w // 3, cv2.BORDER_CONSTANT)
    ch, cw = canvas.shape[:2]
    matrix = cv2.getRotationMatrix2D((cw / 2, ch / 2), degrees, 1.0)
    return cv2.warpAffine(canvas, matrix, (cw, ch), borderValue=(0, 0, 0))


def test_black_padding_does_not_link_different_images():
    """Regression: padding around rotated copies used to make unrelated photos match,
    and transitive links then chained hundreds of photos into one group."""
    a = _padded_rotation(_detailed(21), 9)
    b = _padded_rotation(_detailed(22), 9)
    hashes = np.stack([data.phash_dihedral(data.content_crop(x)) for x in (a, b)])
    assert data.phash_distances(hashes)[0, 1] > data.PHASH_MAX_BITS
    assert data.orb_inliers(data.orb_features(a)[0], data.orb_features(b)) < data.ORB_MIN_INLIERS


def test_padded_rotated_copy_still_links():
    image = _detailed(23)
    copy = _padded_rotation(image, 12)
    assert (
        data.orb_inliers(data.orb_features(image)[0], data.orb_features(copy))
        >= data.ORB_MIN_INLIERS
    )


@pytest.mark.parametrize(
    ("ci", "served"), [((0.23, 0.34), False), ((0.41, 0.55), True), (None, False)]
)
def test_classifier_is_only_served_when_credibly_above_chance(tmp_path, ci, served):
    torch = pytest.importorskip("torch")
    torchvision = pytest.importorskip("torchvision")

    labels = ["combination", "dry", "normal", "oily"]  # chance = 0.25
    model = torchvision.models.efficientnet_b0(weights=None, num_classes=len(labels))
    checkpoint = {"state_dict": model.state_dict(), "labels": labels, "version": "test"}
    if ci is not None:
        checkpoint |= {"test_macro_f1": sum(ci) / 2, "test_macro_f1_ci": list(ci)}
    torch.save(checkpoint, tmp_path / "weights.pt")

    classifier, status = load_skin_type_classifier(tmp_path / "weights.pt")
    assert (classifier is not None) == served
    if not served:
        assert "NOT served" in status


@pytest.mark.parametrize(
    ("ratio", "group"),
    [(None, "unknown"), (float("nan"), "unknown"), (0.72, "lighter"), (0.44, "darker")],
)
def test_tone_group(ratio, group):
    from app.services.image_analysis.lighting import tone_group

    assert tone_group(ratio) == group
