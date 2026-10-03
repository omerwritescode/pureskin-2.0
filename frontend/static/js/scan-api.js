// Calls to the scan funnel's analysis endpoints, with ONE shared reading of the responses:
//   POST /api/services/image/analyze  (photo check, right after capture/upload)
//   POST /api/scan/analyze            (photo + answers, at the end of the questionnaire)
//
//   const result = await PureSkinScanApi.post(url, body);
//   result.kind === "ok"     -> result.data is the response body
//   result.kind === "retake" -> result.issues: why the photo can't be used (show a retake)
//   result.kind === "error"  -> result.message: a friendly message to show
//
// Never logs anything: the body holds the user's photo and answers. Never invents scores.

(function () {
  const MESSAGES = {
    network: "We couldn't reach the server. Check your connection and try again.",
    unavailable: "Photo analysis is temporarily unavailable. Please try again later.",
    tooLarge: "That photo is too large to send. Please take a new photo or choose a smaller one.",
    generic: "Something went wrong. Please try again.",
  };

  // Shown on the retake screen. Short and non-blaming.
  const LIGHTING_TIPS = [
    "Face a window in daylight.",
    "Avoid light from only one side.",
    "Avoid strong light behind you.",
    "Hold the phone at eye level.",
  ];

  async function post(url, body) {
    let response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch {
      return { kind: "error", message: MESSAGES.network };
    }
    const data = await response.json().catch(() => null);

    if (response.ok && data) return { kind: "ok", data };
    // A photo-quality rejection has quality.issues. Any other 422 (a validation error,
    // with "detail") is not the photo's fault, so it is a generic error, not a retake.
    const issues = data && data.quality && data.quality.issues;
    if (response.status === 422 && Array.isArray(issues) && issues.length) {
      return { kind: "retake", issues: issues.map(String) };
    }
    if (response.status === 413) return { kind: "error", message: MESSAGES.tooLarge };
    if (response.status === 503) return { kind: "error", message: MESSAGES.unavailable };
    return { kind: "error", message: MESSAGES.generic };
  }

  // What the Dashboard does when saving the pending scan result (POST /api/profile) fails:
  //   "login"  401: keep the result; apiFetch is already redirecting to /auth/
  //   "retry"  network error (status 0) or 5xx: keep the result, try again later
  //   "rescan" anything else (e.g. 422): the result was rejected; drop it, ask for a new
  //            scan. Never retried, so a bad result can't cause a loop.
  function saveFailureAction(status) {
    if (status === 401) return "login";
    if (status === 0 || status >= 500) return "retry";
    return "rescan";
  }

  window.PureSkinScanApi = { post, saveFailureAction, MESSAGES, LIGHTING_TIPS };
})();
