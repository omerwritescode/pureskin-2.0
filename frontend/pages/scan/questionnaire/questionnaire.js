// Questionnaire: one step at a time, then POST photo + answers to /api/scan/analyze.
//
// Input names and values in index.html are the API's field names and values (a backend
// test checks them against the scorer). "not_sure" means "no evidence" and is left out.
//
// If the photo is rejected at the final submit, the form state is kept in sessionStorage
// (ANSWERS_KEY) while the visitor retakes it on /scan/, then restored here once and
// removed, landing back on the final step. Answers are never logged.

const ANALYZE_URL = "/api/scan/analyze";
const NEXT_URL = "/scan/report/";
const PREVIOUS_URL = "/scan/";
const RETAKE_URL = "/scan/?retake=1";
const NOT_SURE = "not_sure";

const form = document.getElementById("questionnaire");
const steps = [...form.querySelectorAll("[data-step]")];
const counter = document.querySelector(".q-counter");
const progressFill = document.querySelector(".q-progress__fill");
const errorBox = document.getElementById("q-error");
const loading = document.getElementById("q-loading");
const backButton = document.getElementById("q-back");
const nextButton = document.getElementById("q-next");
const submitButton = document.getElementById("q-submit");
const resumed = document.getElementById("q-resumed");

let current = 0;

function showError(message, ...extra) {
  errorBox.replaceChildren();
  if (message) {
    const text = document.createElement("p");
    text.textContent = message;
    errorBox.append(text, ...extra);
  }
  errorBox.hidden = !message;
}

function showStep(index, { focus = true } = {}) {
  current = index;
  steps.forEach((step, i) => (step.hidden = i !== index));
  const isLast = index === steps.length - 1;
  nextButton.hidden = isLast;
  submitButton.hidden = !isLast;
  backButton.textContent = index === 0 ? "Retake photo" : "Back";
  counter.textContent = `Step ${index + 1} of ${steps.length}`;
  progressFill.style.width = `${((index + 1) / steps.length) * 100}%`;
  showError("");
  resumed.hidden = true;
  // Move focus to the new step's heading so keyboard and screen-reader users land on it.
  if (focus) steps[index].querySelector(":scope > legend")?.focus();
}

// Every radio group in the step needs an answer ("Not sure" counts); checkboxes and
// text fields are optional.
function stepIsComplete(step) {
  const groups = new Set([...step.querySelectorAll("input[type=radio]")].map((r) => r.name));
  return [...groups].every((name) => step.querySelector(`input[name="${name}"]:checked`));
}

// Build the answers object straight from the form: names are the API's field names.
function collectAnswers() {
  const data = new FormData(form);
  const answers = {};
  for (const name of new Set(data.keys())) {
    const type = form.querySelector(`input[name="${name}"]`).type;
    if (type === "checkbox") {
      answers[name] = data.getAll(name);
    } else if (type === "text") {
      answers[name] = String(data.get(name) || "").trim();
    } else if (data.get(name) !== NOT_SURE) {
      answers[name] = data.get(name);
    }
  }
  // Unticked checkbox groups don't appear in FormData: send them as empty lists.
  for (const box of form.querySelectorAll("input[type=checkbox]")) {
    if (!(box.name in answers)) answers[box.name] = [];
  }
  return answers;
}

// Every field's current state, "not_sure" included, to restore after a retake.
function formSnapshot() {
  const snapshot = {};
  for (const input of form.querySelectorAll("input")) {
    if (input.type === "radio") {
      if (input.checked) snapshot[input.name] = input.value;
    } else if (input.type === "checkbox") {
      snapshot[input.name] = snapshot[input.name] || [];
      if (input.checked) snapshot[input.name].push(input.value);
    } else {
      snapshot[input.name] = input.value;
    }
  }
  return snapshot;
}

function restoreSnapshot(snapshot) {
  for (const input of form.querySelectorAll("input")) {
    const saved = snapshot[input.name];
    if (input.type === "radio") input.checked = saved === input.value;
    else if (input.type === "checkbox") input.checked = Array.isArray(saved) && saved.includes(input.value);
    else if (typeof saved === "string") input.value = saved;
  }
}

// Keep the answers and the photo's issues, drop the rejected photo, and go to the
// retake screen. Returns false if this browser can't store them.
function goRetake(issues) {
  const { IMAGE_KEY, ANSWERS_KEY, RETAKE_KEY, write, remove } = window.PureSkinScan;
  try {
    write(ANSWERS_KEY, JSON.stringify(formSnapshot()));
    write(RETAKE_KEY, JSON.stringify(issues));
  } catch {
    remove(ANSWERS_KEY);
    remove(RETAKE_KEY);
    return false;
  }
  remove(IMAGE_KEY);
  location.href = RETAKE_URL;
  return true;
}

function setLoading(isLoading) {
  loading.hidden = !isLoading;
  submitButton.disabled = isLoading;
  backButton.disabled = isLoading;
  steps[current].disabled = isLoading;
}

function retakeButton() {
  const link = document.createElement("a");
  link.href = PREVIOUS_URL;
  link.className = "btn";
  link.textContent = "Retake your photo";
  return link;
}

function tipsList() {
  const list = document.createElement("ul");
  for (const tip of window.PureSkinScanApi.LIGHTING_TIPS) {
    const item = document.createElement("li");
    item.textContent = tip;
    list.append(item);
  }
  return list;
}

nextButton.addEventListener("click", () => {
  if (!stepIsComplete(steps[current])) {
    showError("Please choose an answer for each question to continue. \"Not sure\" is fine.");
    return;
  }
  showStep(current + 1);
});

backButton.addEventListener("click", () => {
  if (current === 0) location.href = PREVIOUS_URL;
  else showStep(current - 1); // answers on every step are kept: steps are only hidden
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (submitButton.disabled) return; // already submitting
  if (current < steps.length - 1) {
    nextButton.click(); // Enter pressed in a text field on an earlier step
    return;
  }
  if (!stepIsComplete(steps[current])) {
    showError("Please answer both questions to continue.");
    return;
  }

  const { IMAGE_KEY, RESULT_KEY, START_URL, read, write } = window.PureSkinScan;
  const image = read(IMAGE_KEY);
  if (!image) {
    location.replace(START_URL);
    return;
  }

  // Collect before setLoading: FormData skips disabled fields.
  const answers = collectAnswers();
  showError("");
  setLoading(true);
  const result = await window.PureSkinScanApi.post(ANALYZE_URL, { image, answers });

  if (result.kind === "ok") {
    try {
      write(RESULT_KEY, JSON.stringify(result.data));
      window.PureSkinScan.discardPhotoAndAnswers(); // the funnel is complete
    } catch {
      setLoading(false);
      showError("We couldn't save your results in this browser. Please try again.");
      return;
    }
    location.href = NEXT_URL;
    return;
  }

  setLoading(false);
  if (result.kind === "retake" && goRetake(result.issues)) return;
  if (result.kind === "retake") {
    // This browser can't keep the answers for a retake: explain here instead.
    const issues = document.createElement("ul");
    for (const issue of result.issues) {
      const item = document.createElement("li");
      item.textContent = issue;
      issues.append(item);
    }
    showError("We couldn't use this photo:", issues, tipsList(), retakeButton());
  } else {
    // Validation errors, 413, 503, network: a message, answers stay in the form.
    showError(result.message);
  }
  errorBox.focus();
});

errorBox.tabIndex = -1;

// Back from a retake: restore the answers once, then remove them from storage.
(function resumeAfterRetake() {
  const { ANSWERS_KEY, read, remove } = window.PureSkinScan;
  const saved = read(ANSWERS_KEY);
  remove(ANSWERS_KEY);
  let snapshot = null;
  try {
    snapshot = saved && JSON.parse(saved);
  } catch {
    snapshot = null;
  }
  if (snapshot && typeof snapshot === "object") {
    restoreSnapshot(snapshot);
    showStep(steps.length - 1, { focus: false });
    resumed.hidden = false;
    submitButton.focus();
  } else {
    showStep(0, { focus: false });
  }
})();
