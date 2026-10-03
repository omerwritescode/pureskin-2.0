// Dashboard: save any pending onboarding scan, then show the latest Skin Profile summary.

const {
  el, scoreBars, skinTypeText, assumedSkinTypeNote, sensitiveIndicator, formatDate, scanCta,
  statusMessage, SCORE_FIELDS,
} = PureSkinUI;
const summary = document.getElementById("summary");
const saveNotice = document.getElementById("save-notice");

const RETRY_DELAY_MS = 2000;
const SAVE_LATER =
  "We couldn't save your latest scan yet. We'll try again next time you visit this page.";
const RESCAN = "We couldn't save your latest scan. Please scan again.";
const TAGS_DROPPED =
  "Your scan was saved, but not your current products and the ingredients you avoid, " +
  "so your routine won't take them into account.";

function showSaveNotice(text, { rescan = false } = {}) {
  saveNotice.replaceChildren(
    el("p", { text }),
    rescan ? el("a", { href: "/scan/", text: "Start a new scan" }) : null);
  saveNotice.hidden = false;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// A visitor who scanned before signing up has the /api/scan/analyze result in
// sessionStorage. Save it to their account once, then clear it.
//   422 (or any other rejection): no retry. Drop the result, ask for a new scan.
//   5xx / network error: keep the result, retry at most once on this page load.
//   401: keep the result; apiFetch is already redirecting to /auth/.
async function savePendingScan() {
  const { RESULT_KEY, read, write, remove, discardPhotoAndAnswers } = window.PureSkinScan;
  const raw = read(RESULT_KEY);
  if (!raw) return;

  let result;
  try {
    result = JSON.parse(raw);
  } catch {
    remove(RESULT_KEY);
    discardPhotoAndAnswers();
    showSaveNotice(RESCAN, { rescan: true });
    return;
  }

  // Exactly the fields POST /api/profile stores. Never the photo, and not the
  // display-only "sources" / "quality". questionnaire_tags is a fixed vocabulary (never
  // free text); the server saves the scan without it if it's missing or invalid.
  const body = {
    skin_type: result.skin_type,
    is_sensitive: result.is_sensitive,
    score_sources: result.score_sources,
    questionnaire_tags: result.questionnaire_tags,
  };
  for (const [key] of SCORE_FIELDS) body[key] = result[key];

  function keep() {
    try {
      write(RESULT_KEY, raw);
    } catch {
      // storage unavailable: nothing more we can do
    }
  }

  for (let attempt = 1; attempt <= 2; attempt += 1) {
    // Cleared before each request, so a refresh mid-request can't save it twice.
    remove(RESULT_KEY);
    try {
      const saved = await apiFetch("/api/profile", { method: "POST", body });
      if (saved && saved.questionnaire_tags_dropped) showSaveNotice(TAGS_DROPPED);
      return;
    } catch (error) {
      const action = window.PureSkinScanApi.saveFailureAction(error.status);
      if (action === "login") {
        keep();
        return;
      }
      if (action === "rescan") {
        discardPhotoAndAnswers();
        showSaveNotice(RESCAN, { rescan: true });
        return;
      }
      keep(); // "retry": kept between attempts too, in case the page is closed
      if (attempt === 1) await sleep(RETRY_DELAY_MS);
    }
  }
  showSaveNotice(SAVE_LATER);
}

function renderProfile(profile) {
  const skinType = skinTypeText(profile);
  summary.replaceChildren(
    el("div", { className: "card" },
      el("h2", { className: "card__title", text: "Your skin at a glance" }),
      el("p", { className: "card__meta" },
        "Skin type: ", el("strong", { text: skinType.text }),
        ` · Last scan ${formatDate(profile.created_at)}`),
      skinType.assumed ? assumedSkinTypeNote(skinType.name) : null,
      profile.is_sensitive ? sensitiveIndicator() : null,
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
