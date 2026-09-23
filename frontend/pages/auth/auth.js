// Auth page: toggles between Log in / Sign up views and talks to /api/auth/*.

const TOKEN_KEY = "pureskin_token";
const REDIRECT_TO = "/app/";
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PASSWORD_MIN_LENGTH = 8;
const PASSWORD_MAX_BYTES = 72; // bcrypt limit, enforced by the API too

const FIELD_LABELS = { email: "Email", password: "Password", full_name: "Full name" };

// ---- View toggling -------------------------------------------------------

const tabs = document.querySelectorAll(".auth__tab");

function showView(name) {
  tabs.forEach((tab) => {
    const selected = tab.dataset.view === name;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    document.getElementById(tab.getAttribute("aria-controls")).hidden = !selected;
  });
  history.replaceState(null, "", name === "signup" ? "#signup" : "#login");
}

document.querySelectorAll("[data-view]").forEach((el) => {
  el.addEventListener("click", (event) => {
    event.preventDefault();
    showView(el.dataset.view);
  });
});

// Arrow keys move between tabs (WAI-ARIA tabs pattern).
document.querySelector(".auth__tabs").addEventListener("keydown", (event) => {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  const next = [...tabs].find((tab) => tab.getAttribute("aria-selected") !== "true");
  showView(next.dataset.view);
  next.focus();
});

showView(location.hash === "#signup" ? "signup" : "login");

// ---- Helpers -------------------------------------------------------------

function setError(form, message, invalidInputs = []) {
  form.querySelector(".auth__error").textContent = message;
  form.querySelectorAll("input").forEach((input) => {
    input.setAttribute("aria-invalid", String(invalidInputs.includes(input)));
  });
}

// FastAPI returns `detail` as a string for HTTPExceptions and as a list for validation errors.
function describeError(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    const field = FIELD_LABELS[first.loc?.[first.loc.length - 1]];
    const msg = (first.msg || "").replace(/^Value error, /, "");
    return field ? `${field}: ${msg}` : msg;
  }
  return "Something went wrong. Please try again.";
}

async function submitAuth(form, url, payload) {
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      setError(form, describeError(data.detail));
      return;
    }
    localStorage.setItem(TOKEN_KEY, data.access_token);
    location.href = REDIRECT_TO;
  } catch {
    setError(form, "Couldn't reach the server. Check your connection and try again.");
  } finally {
    button.disabled = false;
  }
}

// ---- Log in --------------------------------------------------------------

const loginForm = document.getElementById("login-form");

loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const email = loginForm.email.value.trim();
  const password = loginForm.password.value;

  if (!EMAIL_PATTERN.test(email)) {
    return setError(loginForm, "Enter a valid email address.", [loginForm.email]);
  }
  if (!password) {
    return setError(loginForm, "Enter your password.", [loginForm.password]);
  }
  setError(loginForm, "");
  submitAuth(loginForm, "/api/auth/login", { email, password });
});

// ---- Sign up -------------------------------------------------------------

const signupForm = document.getElementById("signup-form");

signupForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const fullName = signupForm.full_name.value.trim();
  const email = signupForm.email.value.trim();
  const password = signupForm.password.value;
  const confirm = signupForm.confirm_password.value;

  if (!fullName) {
    return setError(signupForm, "Enter your full name.", [signupForm.full_name]);
  }
  if (!EMAIL_PATTERN.test(email)) {
    return setError(signupForm, "Enter a valid email address.", [signupForm.email]);
  }
  if (password.length < PASSWORD_MIN_LENGTH) {
    return setError(signupForm, `Password must be at least ${PASSWORD_MIN_LENGTH} characters.`, [signupForm.password]);
  }
  if (new TextEncoder().encode(password).length > PASSWORD_MAX_BYTES) {
    return setError(signupForm, "Password is too long.", [signupForm.password]);
  }
  if (password !== confirm) {
    return setError(signupForm, "Passwords don't match.", [signupForm.confirm_password]);
  }
  setError(signupForm, "");
  submitAuth(signupForm, "/api/auth/register", { full_name: fullName, email, password });
});
