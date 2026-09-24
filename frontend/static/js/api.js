// Authenticated fetch for /app pages. Load after auth-guard.js (uses PureSkinAuth.getToken).
//
//   const profile = await apiFetch("/api/profile");
//   await apiFetch("/api/profile", { method: "POST", body: { ... } });  // objects are sent as JSON
//
// Throws ApiError (with .status) on failure. A 401 logs the user out and redirects to /auth/.

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = "ApiError";
    this.status = status; // 0 = network error
  }
}

async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = window.PureSkinAuth.getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let body = options.body;
  if (body !== undefined && typeof body !== "string") {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(path, { ...options, headers, body });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError(0, "Couldn't reach the server. Check your connection and try again.");
  }

  if (response.status === 401) {
    window.PureSkinAuth.logout(); // clears the token and redirects to /auth/
    throw new ApiError(401, "Your session has expired. Please log in again.");
  }

  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data.detail === "string" ? data.detail : null;
    throw new ApiError(response.status, detail || `Request failed (${response.status}).`);
  }
  return data;
}
