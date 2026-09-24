// Dashboard: save any pending onboarding scan, then show the latest Skin Profile summary.

const { el, scoreBars, formatDate, scanCta, statusMessage, capitalize, SCORE_FIELDS } = PureSkinUI;
const summary = document.getElementById("summary");

// A visitor who scanned before signing up has their result in sessionStorage
// (step 5). Save it to their account once, then clear it.
async function savePendingScan() {
  const { RESULT_KEY, IMAGE_KEY, read, write, remove } = window.PureSkinScan;
  const raw = read(RESULT_KEY);
  if (!raw) return;

  let result;
  try {
    result = JSON.parse(raw);
  } catch {
    remove(RESULT_KEY);
    remove(IMAGE_KEY);
    return; // unreadable — nothing worth saving
  }

  // Clear before the request so a refresh mid-request can't save it twice.
  remove(RESULT_KEY);
  remove(IMAGE_KEY);

  const body = { skin_type: result.skin_type };
  for (const [key] of SCORE_FIELDS) body[key] = result[key];

  try {
    await apiFetch("/api/profile", { method: "POST", body });
  } catch (error) {
    // Network/server error or expired session: put it back so the next visit retries.
    // A 4xx means the data itself was rejected, so retrying wouldn't help.
    if (error.status === 0 || error.status === 401 || error.status >= 500) {
      try {
        write(RESULT_KEY, raw);
      } catch {
        // storage unavailable — nothing more we can do
      }
    }
  }
}

function renderProfile(profile) {
  summary.replaceChildren(
    el("div", { className: "card" },
      el("h2", { className: "card__title", text: "Your skin at a glance" }),
      el("p", { className: "card__meta" },
        "Skin type: ", el("strong", { text: capitalize(profile.skin_type) || "Unknown" }),
        ` · Last scan ${formatDate(profile.created_at)}`),
      scoreBars(profile, { compact: true }),
      el("a", { href: "/app/profile/", text: "See full Skin Profile" })));
}

async function init() {
  await savePendingScan();
  try {
    const profile = await apiFetch("/api/profile");
    if (profile) renderProfile(profile);
    else summary.replaceChildren(scanCta());
  } catch (error) {
    if (error.status !== 401) summary.replaceChildren(statusMessage(error.message, { error: true }));
  }
}

init();
