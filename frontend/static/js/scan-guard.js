// Guard + storage helpers for the pre-signup scan funnel (/scan/ -> questionnaire -> report).
//
// Load with a plain <script> in <head>, before the page's own JS. A page that needs an
// earlier step's output declares it on the tag, and is sent back to /scan/ if it's missing:
//
//   <script src="/static/js/scan-guard.js" data-requires="pureskin_scan_image"></script>
//
// This is the ONLY place the check lives, and the only place the two
// sessionStorage keys are defined — pages use PureSkinScan.IMAGE_KEY / RESULT_KEY.
// These pages are deliberately NOT behind auth-guard.js.

(function () {
  const IMAGE_KEY = "pureskin_scan_image";
  const RESULT_KEY = "pureskin_scan_result";
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

  const required = document.currentScript && document.currentScript.dataset.requires;
  if (required && required !== IMAGE_KEY && required !== RESULT_KEY) {
    throw new Error(`scan-guard.js: unknown data-requires key "${required}"`);
  }

  function requireStep() {
    if (required && !read(required)) location.replace(START_URL);
  }

  requireStep();

  // Pages restored from the back/forward cache don't re-run scripts; re-check then too.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) requireStep();
  });

  window.PureSkinScan = { IMAGE_KEY, RESULT_KEY, START_URL, read, write, remove };
})();
