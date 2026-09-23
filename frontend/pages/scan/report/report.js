// Skin Report: renders the (mocked) scan result stored by the questionnaire page.

const SCORES = [
  ["acne_score", "Acne"],
  ["redness_score", "Redness"],
  ["wrinkle_score", "Wrinkles"],
  ["pigmentation_score", "Pigmentation"],
  ["pore_score", "Pores"],
];

const { RESULT_KEY, START_URL, read, remove } = window.PureSkinScan;

let result = null;
try {
  result = JSON.parse(read(RESULT_KEY));
} catch {
  // handled below
}

const valid =
  result && SCORES.every(([key]) => Number.isInteger(result[key]) && result[key] >= 1 && result[key] <= 100);

if (!valid) {
  // Corrupt or outdated result — start the scan again.
  remove(RESULT_KEY);
  location.replace(START_URL);
} else {
  document.getElementById("skin-type").textContent = result.skin_type;

  const list = document.getElementById("scores");
  for (const [key, label] of SCORES) {
    const score = result[key];
    const item = document.createElement("li");
    item.className = "score";
    item.innerHTML = `
      <div class="score__label"><span>${label}</span><span>${score}</span></div>
      <div class="score__track" role="meter" aria-label="${label}"
           aria-valuemin="1" aria-valuemax="100" aria-valuenow="${score}">
        <div class="score__fill" style="width: ${score}%"></div>
      </div>`;
    list.appendChild(item);
  }
}
