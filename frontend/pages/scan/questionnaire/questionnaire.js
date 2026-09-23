// Questionnaire: one step at a time, then POST image + answers to the mock analyser.

const ANALYZE_URL = "/api/scan/mock-analyze";
const NEXT_URL = "/scan/report/";
const PREVIOUS_URL = "/scan/";

const form = document.getElementById("questionnaire");
const steps = [...form.querySelectorAll("[data-step]")];
const counter = document.querySelector(".q-counter");
const progressFill = document.querySelector(".q-progress__fill");
const errorBox = document.getElementById("q-error");
const loading = document.getElementById("q-loading");
const backButton = document.getElementById("q-back");
const nextButton = document.getElementById("q-next");
const submitButton = document.getElementById("q-submit");

let current = 0;

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = !message;
}

function showStep(index) {
  current = index;
  steps.forEach((step, i) => (step.hidden = i !== index));
  const isLast = index === steps.length - 1;
  nextButton.hidden = isLast;
  submitButton.hidden = !isLast;
  backButton.textContent = index === 0 ? "Retake photo" : "Back";
  counter.textContent = `Question ${index + 1} of ${steps.length}`;
  progressFill.style.width = `${((index + 1) / steps.length) * 100}%`;
  showError("");
}

// Every radio group in the step must have an answer; checkboxes and text are optional.
function stepIsComplete(step) {
  const groups = new Set([...step.querySelectorAll("input[type=radio]")].map((r) => r.name));
  return [...groups].every((name) => step.querySelector(`input[name="${name}"]:checked`));
}

function collectAnswers() {
  const data = new FormData(form);
  return {
    skin_type: data.get("skin_type"),
    primary_concern: data.get("primary_concern"),
    sensitivities: data.getAll("sensitivities"),
    sensitivities_other: (data.get("sensitivities_other") || "").trim(),
    current_products: data.getAll("current_products"),
    current_products_other: (data.get("current_products_other") || "").trim(),
    sleep: data.get("sleep"),
    stress: data.get("stress"),
  };
}

function setLoading(isLoading) {
  loading.hidden = !isLoading;
  submitButton.disabled = isLoading;
  backButton.disabled = isLoading;
  steps[current].disabled = isLoading;
}

nextButton.addEventListener("click", () => {
  if (!stepIsComplete(steps[current])) {
    showError("Please choose an answer to continue.");
    return;
  }
  showStep(current + 1);
  steps[current].querySelector("input")?.focus();
});

backButton.addEventListener("click", () => {
  if (current === 0) location.href = PREVIOUS_URL;
  else showStep(current - 1);
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
  const body = JSON.stringify({ image, answers: collectAnswers() });
  showError("");
  setLoading(true);
  try {
    const response = await fetch(ANALYZE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    write(RESULT_KEY, JSON.stringify(result));
    location.href = NEXT_URL;
  } catch {
    setLoading(false);
    showError("Something went wrong analysing your photo. Please try again.");
  }
});

showStep(0);
