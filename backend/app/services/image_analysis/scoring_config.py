"""Every threshold and raw-feature -> score mapping used by the Image Analysis service.

HEURISTIC AND TUNABLE. None of these numbers were fitted to ground-truth labels — there
is no dermatologist-labelled data behind them. They were set by measuring a handful of
public portraits, the same faces with synthetic lesions/blur/lighting changes applied,
and our own selfies (see README.md, "Calibration"). Change them here, nowhere else.

Units used below:
- "canonical px": pixels after the face is rotated level and rescaled so the face-oval
  width is CANONICAL_FACE_WIDTH_PX. Every spatial size is in these units, so features
  don't depend on how far the camera was from the face.
- "log units": natural-log differences of linear-light values. 0.10 ~ 10% darker/redder
  than the comparison skin. Working in log ratios is what makes the features insensitive
  to exposure and skin tone (a uniform gain cancels out of every difference).
"""

SCORING_VERSION = "heuristic-1"

# --------------------------------------------------------------------------------------
# Input limits
# --------------------------------------------------------------------------------------
MAX_REQUEST_BYTES = 5_000_000  # whole HTTP body; funnel JPEGs (<=720px) are ~100-300 KB
# An oversized body is still read (and thrown away, never buffered) up to this size before
# answering 413; answering mid-upload makes the server drop the connection, and browsers
# then report a network error instead of the 413. Bigger uploads are cut off at once.
MAX_DRAINED_BYTES = 20_000_000
MAX_IMAGE_PIXELS = 25_000_000  # declared width*height, checked before decoding (bomb guard)
# Canonical resolution: before ANY quality check or measurement, the decoded photo is
# downscaled in memory so its longest side is at most this (never enlarged), with
# cv2.INTER_AREA (deterministic). Every threshold here was calibrated on 720 px photos,
# and without this the client's resize became part of the model: the same photo passed
# at 720 px but was rejected as too dim at 960 and 1080 px (README, "Canonical resolution").
CANONICAL_MAX_SIDE = 720
CANONICAL_INTERPOLATION = "INTER_AREA"
# Training pipeline only (train_skin_type.py pre-shrinks dataset images with it before
# calling the analyzer, which then applies CANONICAL_MAX_SIDE as above).
WORKING_MAX_SIDE = 1600
ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")

# --------------------------------------------------------------------------------------
# Whole-image checks (run before face detection, so a black or smeared photo gets a
# useful message instead of "no face found")
# --------------------------------------------------------------------------------------
GLOBAL_CHECK_SIDE = 512  # image is downscaled to this longest side for these checks
GLOBAL_DARK_P99 = 40  # 8-bit gray: if even the brightest 1% is below this -> too dark
GLOBAL_BRIGHT_MEDIAN = 245  # 8-bit gray: median above this -> overexposed (washed out)
# Sharpness = share of gradient energy lost when the photo is blurred once more (sigma
# below, in GLOBAL_CHECK_SIDE pixels). A sharp photo loses a lot (~0.5-0.65); one that
# is already blurred loses little. A ratio, so it doesn't depend on exposure or contrast.
GLOBAL_BLUR_REBLUR_SIGMA = 1.5
GLOBAL_BLUR_MIN_SHARPNESS = 0.12  # ~ a Gaussian blur of sigma 5 px on a 720 px photo

# --------------------------------------------------------------------------------------
# Face detection and framing (MediaPipe Face Landmarker)
# --------------------------------------------------------------------------------------
FACE_DETECTION_CONFIDENCE = 0.5
FACE_PRESENCE_CONFIDENCE = 0.5
MAX_FACES_TO_DETECT = 4
# A second face only counts if it is at least this wide relative to the largest face, so
# a tiny face on a poster in the background doesn't reject an otherwise good selfie.
SECONDARY_FACE_MIN_RELATIVE_WIDTH = 0.4
MIN_FACE_WIDTH_PX = 150  # face-oval width in the (working) image; below -> hard reject
SOFT_MIN_FACE_WIDTH_PX = 220  # below -> warning: texture scores (pores, wrinkles) less reliable
FACE_OUT_OF_FRAME_TOLERANCE = 0.03  # landmarks may sit this fraction of face width outside
MAX_YAW_DEG = 30.0  # head turned left/right: hard reject above
SOFT_MAX_YAW_DEG = 15.0
MAX_PITCH_DEG = 30.0  # head tilted up/down: hard reject above
SOFT_MAX_PITCH_DEG = 20.0
SOFT_MAX_SMILE = 0.5  # MediaPipe smile blendshape; smiling deepens lines around the eyes

# --------------------------------------------------------------------------------------
# Normalisation (alignment + skin mask)
# --------------------------------------------------------------------------------------
CANONICAL_FACE_WIDTH_PX = 300
ALIGN_MARGIN_FRACTION = 0.06  # canvas margin around the face oval
FEATURE_MARGIN_PX = 4  # eyes/brows/lips are excluded with this margin (canonical px)
# Low-frequency "illumination" layer = masked Gaussian blur of the skin at this sigma.
# Subtracting it removes shading gradients (side light, shadows from the nose/brow ridge)
# before looking for spots and lines.
ILLUMINATION_SIGMA_PX = 24
# Skin mask: a pixel inside the face oval counts as skin only if it resembles the face's
# own median skin. All tests are relative to that face, so they behave the same on light
# and dark skin. They are deliberately one-sided where it matters: redder or browner
# than average is exactly what we measure, so it must never be masked out.
SKIN_MAX_DARKER_LOG = 1.1  # > ~3x darker than median skin: hair, deep shadow, nostril
SKIN_MAX_BRIGHTER_LOG = 0.8  # > ~2.2x brighter: background, reflections
# "Warmth" = r - b chromaticity (r = R/(R+G+B)). Grey/blue/green things (glasses, grey
# hair, background) and white specular glare are much less warm than skin of any tone.
SKIN_MIN_WARMTH_RATIO = 0.5  # pixel warmth below half the face's median -> not skin
HIGHLIGHT_LOG = 0.5  # > ~65% brighter than surrounding skin: specular shine, excluded
HIGHLIGHT_MARGIN_PX = 2  # highlights are excluded with this margin (their halos fool filters)
CLIPPED_LEVEL = 250  # 8-bit value treated as saturated
# A region whose skin mask covers less than this fraction of its polygon (hair, glasses,
# shadow) is skipped, with a warning. If a score has no usable region left -> hard reject.
REGION_MIN_SKIN_FRACTION = 0.35

# --------------------------------------------------------------------------------------
# Face-level exposure, sharpness and lighting checks (on the aligned face)
# --------------------------------------------------------------------------------------
# Exposure is judged from a WHITE REFERENCE in the photo (eye whites, or teeth when
# smiling), not from skin brightness: skin brightness would call darker skin "dim" under
# exactly the same light. With no usable reference, the scene's highlights are used.
# (Measured in lighting.py.)
REFERENCE_PERCENTILES = (85, 98)  # brightest 15% of the eye/mouth area, minus catchlights
REFERENCE_MAX_CHROMA = 0.25  # a white reference is near-neutral (rejects lips, lashes)
REFERENCE_MIN_PIXELS = 30
REFERENCE_CLIPPED = 0.98  # linear; a saturated reference can't give a skin/white ratio
SCENE_HIGHLIGHT_PERCENTILE = 98  # fallback exposure reference: the whole photo's highlights
# Too dim (hard reject, HTTP 422) when the exposure reference is darker than this L*.
# Derived by calibrate_dim_threshold.py on 40 public dataset photos (20 lighter-, 20
# darker-skinned; none of the project's own or the rated photos): darkened step by step,
# 0.15x exposure (median reference L* 38.8) was the dimmest step at which, in BOTH groups,
# the median largest change among the redness/wrinkle/pigmentation/pore scores stayed
# <= 10 points. The darker group was the limiting one. Acne is left out of the criterion:
# it drifts at any exposure change (median 5-9 points at just 0.7x) and is documented as
# unreliable; including it made every photo short of perfect exposure fail.
DIM_MIN_EXPOSURE_L = 38.0
FACE_CLIPPED_FRACTION = 0.25  # share of skin pixels saturated -> overexposed
SOFT_FACE_CLIPPED_FRACTION = 0.06
FACE_BLUR_MIN_SHARPNESS = 15.0  # variance of Laplacian, contrast-normalised face box
SOFT_FACE_BLUR_MIN_SHARPNESS = 50.0
# Even lighting: brighter / darker cheek luminance (linear light). Both cheeks are the
# same person's skin, so skin tone cancels. Above 2:1 (one photographic stop between the
# two sides; the conventional limit of "flat" portrait lighting) -> hard reject.
UNEVEN_LIGHT_MAX_RATIO = 2.0
# Coarse skin-tone buckets for subgroup reporting (training script, evaluation scripts):
# skin luminance / white-reference luminance. Set between the two development faces
# (light skin 0.72, dark skin 0.44). A rough proxy, never used to score anyone.
TONE_LIGHTER_AT_LEAST = 0.55

# --------------------------------------------------------------------------------------
# Per-attribute features. Region weights are renormalised over usable regions.
# --------------------------------------------------------------------------------------
# Redness: erythema index EI = ln(R/G) (linear light). Compared with a low percentile of
# the face's own skin, so it measures redness relative to the person's baseline.
REDNESS_REGIONS = {"right_cheek": 1.0, "left_cheek": 1.0, "nose": 0.6}
REDNESS_BASELINE_PERCENTILE = 30
# Smoothing before measuring. Without it, pixel noise alone raises a "mean excess"
# statistic, and noise is larger (in log units) on darker skin and in dim photos, which
# would bias the score by skin tone.
REDNESS_SMOOTH_SIGMA_PX = 2.0

# Acne: small, compact, red blobs in the local erythema map.
# (Acne pools its lesion count over these regions, so the weights only mark membership.)
ACNE_REGIONS = {"right_cheek": 1.0, "left_cheek": 1.0, "forehead": 1.0, "chin": 1.0}
ACNE_BACKGROUND_SIGMA_PX = 10  # local redness baseline
ACNE_BLOB_SIGMAS_PX = (1.5, 2.5, 3.5)  # lesion diameters ~4-10 canonical px (~2-5 mm)
ACNE_MIN_RESPONSE = 0.04  # scale-normalised LoG response on the erythema map...
ACNE_MIN_RESPONSE_Z = 8.0  # ...and this many robust SDs of the face's own response
ACNE_MIN_RED_EXCESS = 0.06  # log units redder than surrounding skin at the blob centre
ACNE_MAX_DARK_TO_RED = 1.0  # blob must be redder than it is dark (else it's pigment)
ACNE_PEAK_WINDOW_PX = 9  # non-maximum suppression window, about one lesion across
ACNE_EDGE_MARGIN_PX = 3  # ignore blobs this close to a mask edge
ACNE_DENSITY_AREA_PX = 10_000  # density reported per this many canonical px of skin

# Pigmentation: dark spots in the red channel (melanin absorbs red light; haemoglobin
# barely does, so red acne/flushing doesn't register here) + overall tone unevenness.
PIGMENT_REGIONS = {"right_cheek": 1.0, "left_cheek": 1.0, "forehead": 1.0, "chin": 0.5}
PIGMENT_SMOOTH_SIGMA_PX = 1.2  # suppress pores/noise before thresholding
PIGMENT_BACKGROUND_SIGMA_PX = 10  # spots are compared with skin within ~this radius
PIGMENT_SPOT_LOG = 0.08  # >~8% darker (red channel) than local skin -> spot pixel
PIGMENT_MIN_SPOT_AREA_PX = 6
PIGMENT_MAX_SPOT_AREA_PX = 300
PIGMENT_MAX_SPOT_ELONGATION = 3.5  # longer, thinner dark marks are folds/lines, not spots
PIGMENT_MAX_RED_TO_DARK = 0.6  # spot must be clearly darker than it is red
PIGMENT_SPOT_WEIGHT = 0.6  # score = weighted mix of the spot and unevenness sub-scores
PIGMENT_UNEVEN_WEIGHT = 0.4

# Pores: fine-scale dark texture (difference of Gaussians on log luminance).
PORE_REGIONS = {"nose": 1.0, "right_cheek": 0.7, "left_cheek": 0.7}
PORE_DOG_SIGMAS_PX = (0.8, 2.0)

# Wrinkles: dark lines with one dominant orientation (oriented Gabor filter bank on log
# luminance; strength = best orientation minus the mean over all orientations).
WRINKLE_REGIONS = {
    "forehead": 1.0,
    "right_crows_feet": 0.5,
    "left_crows_feet": 0.5,
    "right_under_eye": 0.4,
    "left_under_eye": 0.4,
}
WRINKLE_PRESMOOTH_SIGMA_PX = 0.8
WRINKLE_GABOR_ORIENTATIONS = 8
WRINKLE_GABOR_SIGMA_PX = 2.2
WRINKLE_GABOR_WAVELENGTH_PX = 6.0
WRINKLE_GABOR_ASPECT = 0.4  # < 1 = elongated kernel, i.e. line-shaped
WRINKLE_GABOR_KERNEL_PX = 21
# Forehead lines run roughly horizontally; restricting orientation there stops stray
# hair strands and the vertical frown area from counting.
WRINKLE_FOREHEAD_MAX_TILT_DEG = 35
WRINKLE_LINE_LOG = 0.05  # oriented contrast: line ~5% darker than the texture around it
WRINKLE_MIN_AREA_PX = 6  # smaller detections are noise

# --------------------------------------------------------------------------------------
# Raw feature -> 1-100 score. Piecewise-linear through these anchors (np.interp), then
# clamped to 1-100 and rounded. Higher = more of that concern.
#
# How the anchors were chosen (README.md, "Calibration"): two public portraits with no
# visible acne/rosacea (one light, one dark skin tone) land in the low-to-moderate band;
# the upper anchors are where synthetic lesions/spots injected into those faces push the
# raw feature. The acne anchors loosely follow lesion-count severity bands (Hayashi et
# al., 2008) scaled to the area we measure. None of this is fitted to labelled data.
# --------------------------------------------------------------------------------------
SCORE_ANCHORS = {
    # mean erythema excess over the face's own baseline (log units)
    "redness": ([0.0, 0.06, 0.12, 0.25], [1, 20, 45, 100]),
    # acne-like blobs per ACNE_DENSITY_AREA_PX; clear skin in sharp photos already shows
    # ~1-4 (follicles, small vessels), so that band maps to a low score
    "acne": ([0.0, 2.0, 6.0, 12.0], [1, 15, 50, 100]),
    # share of skin covered by dark spots
    "pigment_spots": ([0.0, 0.01, 0.04, 0.10], [1, 20, 60, 100]),
    # robust SD of red-channel darkness (log units)
    "pigment_unevenness": ([0.0, 0.03, 0.06, 0.12], [1, 20, 50, 100]),
    # mean fine-scale darkness (log units)
    "pores": ([0.0, 0.005, 0.015, 0.03], [1, 20, 55, 100]),
    # share of the forehead/eye areas covered by oriented lines
    "wrinkles": ([0.0, 0.03, 0.15, 0.40], [1, 20, 60, 100]),
}
