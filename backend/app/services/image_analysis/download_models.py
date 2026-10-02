"""Download the MediaPipe Face Landmarker model into models/ (gitignored).

Run from backend/:
    python -m app.services.image_analysis.download_models

The model (~3.7 MB, Apache-2.0, Google) is pinned to version 1 and checked against a
SHA-256, so every machine gets exactly the file the service was built and tested with.
"""

import hashlib
import sys
import urllib.request

from .analyzer import FACE_MODEL_PATH

FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
FACE_MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    if FACE_MODEL_PATH.is_file() and _sha256(FACE_MODEL_PATH.read_bytes()) == FACE_MODEL_SHA256:
        print(f"Already present and verified: {FACE_MODEL_PATH}")
        return 0

    print(f"Downloading {FACE_MODEL_URL}")
    with urllib.request.urlopen(FACE_MODEL_URL, timeout=60) as response:
        data = response.read()
    if _sha256(data) != FACE_MODEL_SHA256:
        print("Checksum mismatch: the downloaded file is not the expected model. Not saved.")
        return 1

    FACE_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    FACE_MODEL_PATH.write_bytes(data)
    print(f"Saved {len(data) / 1e6:.1f} MB to {FACE_MODEL_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
