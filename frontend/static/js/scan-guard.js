// Guard + storage helpers for the pre-signup scan funnel (/scan/ -> questionnaire -> report).
//
// Load with a plain <script> in <head>, before the page's own JS. A page that needs an
// earlier step's output declares it on the tag, and is sent back to /scan/ if it's missing:
//
//   <script src="/static/js/scan-guard.js" data-requires="pureskin_scan_image"></script>
//
// Pages outside the photo steps (the report, login, Dashboard) add data-outside-funnel:
// the photo, and any answers kept for a retake, are then dropped as soon as the page
// loads, so they never linger in the tab. The scan result itself is kept until it has
// been saved after login.
//
// This is the ONLY place the check lives, and the only place the sessionStorage keys
// are defined: pages use PureSkinScan.IMAGE_KEY etc. Nothing here logs anything.
// These pages are deliberately NOT behind auth-guard.js.

(function () {
  const IMAGE_KEY = "pureskin_scan_image";
  const RESULT_KEY = "pureskin_scan_result";
  // Kept ONLY while a visitor retakes a photo that failed at the final submit, and
  // removed as soon as they are read back: the questionnaire form state (including the
  // free text) and the photo issues to show on the retake screen.
  const ANSWERS_KEY = "pureskin_scan_answers";
  const RETAKE_KEY = "pureskin_scan_retake";
  const START_URL = "/scan/";

  function read(key) {
    try {
      return sessionStorage.getItem(key);
    } catch {
      return null; // storage blocked — treat as missing
    }
  }

  // Throws on failure (e.g. QuotaExceededError) so the caller can tell the user.
  function write(key, value) {
    sessionStorage.setItem(key, value);
  }

  function remove(key) {
    try {
      sessionStorage.removeItem(key);
    } catch {
      // nothing to clear
    }
  }

  // The photo and anything kept for a retake; never the result awaiting its save.
  function discardPhotoAndAnswers() {
    remove(IMAGE_KEY);
    remove(ANSWERS_KEY);
    remove(RETAKE_KEY);
  }

  const script = document.currentScript;
  const required = script && script.dataset.requires;
  if (required && required !== IMAGE_KEY && required !== RESULT_KEY) {
    throw new Error(`scan-guard.js: unknown data-requires key "${required}"`);
  }
  if (script && "outsideFunnel" in script.dataset) discardPhotoAndAnswers();

  function requireStep() {
    if (required && !read(required)) location.replace(START_URL);
  }

  requireStep();

  // Pages restored from the back/forward cache don't re-run scripts; re-check then too.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) requireStep();
  });

  window.PureSkinScan = {
    IMAGE_KEY, RESULT_KEY, ANSWERS_KEY, RETAKE_KEY, START_URL,
    read, write, remove, discardPhotoAndAnswers,
  };
})();
