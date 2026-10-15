// Public pages (/, /about/, /contact/): marks <html data-account="member"> when this browser
// holds a login token, so CSS shows "Go to your dashboard" in place of Log in and Sign up
// (main.css, .if-member / .if-guest). A presence check only: the Dashboard deals with an
// expired token. Load it in <head>, before the stylesheets, so the right links show on first
// paint. It only reads the token: it writes nothing, adds no links and never navigates.

(function () {
  const TOKEN_KEY = "pureskin_token"; // the key auth-guard.js and auth.js use

  function hasToken() {
    try {
      return Boolean(localStorage.getItem(TOKEN_KEY));
    } catch {
      return false; // storage blocked (e.g. privacy mode): treat as logged out
    }
  }

  function mark() {
    if (hasToken()) document.documentElement.dataset.account = "member";
    else delete document.documentElement.dataset.account;
  }

  mark();

  // A page restored by Back (say, after logging out) doesn't run scripts again: check again.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) mark();
  });
})();
