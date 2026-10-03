// Skin Report: renders the /api/scan/analyze result stored by the questionnaire page.

const { SCORE_FIELDS, scoreBars, skinTypeText, assumedSkinTypeNote, sensitiveIndicator } = PureSkinUI;
const { RESULT_KEY, START_URL, read, remove } = window.PureSkinScan;

let result = null;
try {
  result = JSON.parse(read(RESULT_KEY));
} catch {
  // handled below
}

const valid =
  result &&
  SCORE_FIELDS.every(([key]) => Number.isInteger(result[key]) && result[key] >= 1 && result[key] <= 100) &&
  typeof result.skin_type === "string" &&
  typeof result.is_sensitive === "boolean";

if (!valid) {
  // Corrupt or outdated result: start the scan again. Never show made-up scores.
  remove(RESULT_KEY);
  location.replace(START_URL);
} else {
  const skinType = skinTypeText(result);
  document.getElementById("skin-type").textContent = skinType.text;
  const extra = document.getElementById("skin-type-extra");
  if (skinType.assumed) extra.append(assumedSkinTypeNote(skinType.name));
  if (result.is_sensitive) extra.append(sensitiveIndicator());

  // Soft warnings from the photo check: the photo was used, but could be better.
  const tips = (result.quality && Array.isArray(result.quality.issues) && result.quality.issues) || [];
  if (tips.length) {
    document.getElementById("photo-tip-list").append(...tips.map((tip) => {
      const item = document.createElement("li");
      item.textContent = String(tip);
      return item;
    }));
    document.getElementById("photo-tips").hidden = false;
  }

  document.getElementById("scores-help").textContent =
    `Higher means more noticeable. ${window.PureSkinBands.legend()}.`;
  document.getElementById("scores").replaceChildren(scoreBars(result));
}
