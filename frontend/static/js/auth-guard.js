// Auth guard for every authenticated (/app/...) page.
//
// Load this with a plain <script> in <head>, before any other page script, so the
// redirect happens before the page renders. This is the ONLY place the token check
// lives — pages must not repeat it.
//
// It only checks that a token exists; the API rejects expired/invalid tokens (401).

(function () {
  const TOKEN_KEY = "pureskin_token";
  const LOGIN_URL = "/auth/";

  function getToken() {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null; // storage blocked (e.g. privacy mode) — treat as logged out
    }
  }

  function logout() {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      // nothing stored to clear
    }
    location.replace(LOGIN_URL);
  }

  function requireToken() {
    if (!getToken()) location.replace(LOGIN_URL);
  }

  requireToken();

  // Pages restored from the back/forward cache (e.g. Back after logging out) don't
  // re-run scripts, so re-check when they're shown again.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) requireToken();
  });

  // Shared with nav.js (logout button) and, later, page scripts that call the API.
  window.PureSkinAuth = { getToken, logout };
})();
