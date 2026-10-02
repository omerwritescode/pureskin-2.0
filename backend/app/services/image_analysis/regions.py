"""Facial regions, defined by MediaPipe Face Landmarker mesh indices (478-point topology).

"Right"/"left" are the subject's own sides, so on an unmirrored photo the subject's right
cheek appears on the image's left. Every polygon below was checked by drawing it over
real faces (see visualize_regions.py); mirror pairs use MediaPipe's symmetric indices.
"""

import cv2
import numpy as np

FACE_OVAL = [
    10,
    338,
    297,
    332,
    284,
    251,
    389,
    356,
    454,
    323,
    361,
    288,
    397,
    365,
    379,
    378,
    400,
    377,
    152,
    148,
    176,
    149,
    150,
    136,
    172,
    58,
    132,
    93,
    234,
    127,
    162,
    21,
    54,
    103,
    67,
    109,
]

# Features that are not skin; removed (with a margin) from every region.
RIGHT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
LEFT_EYE = [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466]
RIGHT_BROW = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]
LEFT_BROW = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]
LIPS = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
# Opening between the lips (teeth when smiling) and iris centre + ring, used only to find
# a white reference for the training script's skin-tone breakdown.
INNER_MOUTH = [
    78,
    191,
    80,
    81,
    82,
    13,
    312,
    311,
    310,
    415,
    308,
    324,
    318,
    402,
    317,
    14,
    87,
    178,
    88,
    95,
]
IRISES = ((468, (469, 470, 471, 472)), (473, (474, 475, 476, 477)))

# Analysis regions. Bottom edge of the forehead follows the brow tops; top edge stops at
# the mesh's hairline row (hair that still falls inside is removed by the skin mask).
REGIONS: dict[str, list[int]] = {
    "forehead": [103, 67, 109, 10, 338, 297, 332, 333, 334, 296, 336, 9, 107, 66, 105, 104],
    "right_cheek": [117, 118, 119, 100, 142, 203, 206, 207, 187, 147, 123, 116],
    "left_cheek": [346, 347, 348, 329, 371, 423, 426, 427, 411, 376, 352, 345],
    # Lower nose (bridge below the eyes, tip, upper alae); stops above the nostrils.
    "nose": [
        196,
        197,
        419,
        456,
        420,
        360,
        279,
        278,
        344,
        440,
        275,
        1,
        45,
        220,
        115,
        48,
        49,
        131,
        198,
        236,
    ],
    # Below the lower lip down to just above the jawline edge.
    "chin": [182, 83, 18, 313, 406, 418, 262, 369, 396, 175, 171, 140, 32, 194],
    # Starts one landmark ring below the lower lid, so lashes and the lid margin (a strong
    # dark line on everyone) aren't mistaken for wrinkles.
    "right_under_eye": [31, 228, 229, 230, 231, 232, 233, 128, 121, 120, 119, 118, 117, 111],
    "left_under_eye": [261, 448, 449, 450, 451, 452, 453, 357, 350, 349, 348, 347, 346, 340],
    # Lateral to the outer eye corner (crow's feet).
    "right_crows_feet": [226, 113, 124, 156, 139, 34, 143, 111, 31],
    "left_crows_feet": [446, 342, 353, 383, 368, 264, 372, 340, 261],
}

# Landmarks used for alignment and pose.
RIGHT_EYE_CORNERS = (33, 133)
LEFT_EYE_CORNERS = (263, 362)
RIGHT_FACE_EDGE = 234
LEFT_FACE_EDGE = 454


def polygon_mask(shape: tuple[int, int], points: np.ndarray, indices: list[int]) -> np.ndarray:
    """Filled polygon over the given landmark indices, as a bool mask of `shape`."""
    mask = np.zeros(shape, dtype=np.uint8)
    poly = np.round(points[indices]).astype(np.int32)
    cv2.fillPoly(mask, [poly], 1)
    return mask.astype(bool)


def non_skin_feature_mask(shape: tuple[int, int], points: np.ndarray, margin_px: int) -> np.ndarray:
    """Eyes, brows and lips, dilated by `margin_px` so lashes and lip edges are excluded."""
    mask = np.zeros(shape, dtype=np.uint8)
    for indices in (RIGHT_EYE, LEFT_EYE, RIGHT_BROW, LEFT_BROW, LIPS):
        cv2.fillPoly(mask, [np.round(points[indices]).astype(np.int32)], 1)
    if margin_px > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * margin_px + 1,) * 2)
        mask = cv2.dilate(mask, kernel)
    return mask.astype(bool)
