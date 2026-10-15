// Skin Profile: read-only view of the latest scan. Profiles come from scanning, not editing.

const {
  el, scoreBars, skinTypeText, assumedSkinTypeNote, sensitiveIndicator, formatDate, scanCta,
  statusMessage,
} = PureSkinUI;
const content = document.getElementById("content");

function renderProfile(profile) {
  const skinType = skinTypeText(profile);
  // replaceChildren() would print a null as the text "null": the optional parts (the
  // assumed-type note, the Sensitive indicator) are dropped instead, as el() does.
  content.replaceChildren(...[
    el("div", { className: "profile-type" },
      el("span", { className: "profile-type__label", text: "Skin type" }),
      el("span", { className: "profile-type__value", text: skinType.text })),
    skinType.assumed ? assumedSkinTypeNote(skinType.name) : null,
    profile.is_sensitive ? sensitiveIndicator() : null,
    el("p", { className: "profile-date", text: `From your scan on ${formatDate(profile.created_at)}` }),
    el("div", { className: "card profile-scores" },
      el("h2", { className: "card__title", text: "Scores" }),
      el("p", {
        className: "card__meta",
        text: `Higher means more noticeable. ${PureSkinBands.legend()}.`,
      }),
      scoreBars(profile)),
    el("p", { className: "profile-rescan" },
      "Want to update it? ", el("a", { href: "/scan/", text: "Take a new scan" })),
  ].filter(Boolean));
}

async function init() {
  try {
    const profile = await apiFetch("/api/profile");
    if (profile) renderProfile(profile);
    else content.replaceChildren(scanCta());
  } catch (error) {
    if (error.status !== 401) content.replaceChildren(statusMessage(error.message, { error: true }));
  }
}

init();
