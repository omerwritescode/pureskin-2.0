"""Dev tool: server-side timing of POST /api/scan/analyze on this machine's CPU.

    python -m app.services.skin_profile.time_analyze [runs]     # from backend/

Sends each sample selfie (downsized as the selfie page does: 720 px, JPEG q85) with
questionnaire answers through the real endpoint in-process (ASGI, no network), and
times the parts separately. Needs the face model and photos in
image_analysis/samples/. Writes nothing.
"""

import statistics
import sys
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import scan_analyze
from app.services.image_analysis import analyze_image, load_models
from app.services.image_analysis.check_funnel_resolution import data_url
from app.services.image_analysis.tests.conftest import sample_photos
from app.services.questionnaire import score_questionnaire

from .orchestrator import build_skin_profile

ANSWERS = {
    "skin_type": "combination", "primary_concern": "acne", "sensitivities": ["fragrance"],
    "sensitivities_other": "lanolin, I have rosacea", "current_products": ["cleanser"],
    "current_products_other": "Paula's Choice 2% BHA, vitamin C serum", "sleep": "6_to_8",
    "stress": "medium", "breakouts": "most_weeks", "deep_bumps": "often", "dark_spots": "a_few",
}


def ms(samples: list[float]) -> str:
    return f"median {statistics.median(samples):.1f} ms, max {max(samples):.1f} ms"


def main(runs: int = 20) -> None:
    load_models()  # once, as the server does at startup
    app = FastAPI()
    app.include_router(scan_analyze.router)
    client = TestClient(app)
    for path in sample_photos():
        image = data_url(path, 720, 85)
        client.post("/api/scan/analyze", json={"image": image, "answers": ANSWERS})  # warm-up
        total, questionnaire, analysis, merge = [], [], [], []
        for _ in range(runs):
            t0 = time.perf_counter()
            response = client.post("/api/scan/analyze", json={"image": image, "answers": ANSWERS})
            total.append((time.perf_counter() - t0) * 1000)
            assert response.status_code == 200, response.text

            t0 = time.perf_counter()
            q = score_questionnaire(ANSWERS)
            t1 = time.perf_counter()
            img = analyze_image(image)
            t2 = time.perf_counter()
            build_skin_profile(img, q)
            t3 = time.perf_counter()
            questionnaire.append((t1 - t0) * 1000)
            analysis.append((t2 - t1) * 1000)
            merge.append((t3 - t2) * 1000)
        print(f"{path.name} ({len(image) // 1024} KB base64, {runs} runs)")
        print(f"  whole request (in-process): {ms(total)}")
        print(f"  questionnaire scorer:       {ms(questionnaire)}")
        print(f"  image analysis:             {ms(analysis)}")
        print(f"  merge:                      {ms(merge)}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20)
