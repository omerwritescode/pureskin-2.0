// Routine: AM/PM steps from GET /api/routine, with ingredient-conflict warnings on top.

const { el, scanCta, statusMessage, capitalize } = PureSkinUI;
const content = document.getElementById("content");

function stepItem(step) {
  const { product } = step;
  const notes = [];
  if (step.matched_keyword) notes.push(`Chosen for: ${step.matched_keyword}`);
  if (step.note) notes.push(step.note);

  return el("li", { className: "routine-step" },
    el("span", { className: "routine-step__number", "aria-hidden": "true", text: String(step.step) }),
    el("div", { className: "routine-step__body" },
      el("span", { className: "routine-step__category", text: capitalize(product.category) }),
      el("a", { className: "routine-step__name", href: `/app/catalog/${product.id}/`, text: product.name }),
      el("span", { className: "routine-step__brand", text: product.brand }),
      notes.length ? el("span", { className: "routine-step__note", text: notes.join(" · ") }) : null));
}

function session(title, steps) {
  return el("section", { className: "card routine-session" },
    el("h2", { className: "card__title", text: title }),
    steps.length
      ? el("ol", { className: "routine-steps" }, ...steps.map(stepItem))
      : el("p", { className: "status", text: "No steps for this session." }));
}

function renderRoutine(routine) {
  const parts = [
    el("p", { className: "routine-intro" },
      "Built for ", el("strong", { text: `${routine.skin_type} skin` }),
      " from your latest scan, using products in our catalog."),
  ];
  if (routine.warnings.length) {
    parts.push(el("div", { className: "warning-box", role: "note" },
      el("h2", { className: "warning-box__title", text: "Heads up" }),
      el("ul", {}, ...routine.warnings.map((w) => el("li", { text: w })))));
  }
  parts.push(el("div", { className: "routine-grid" },
    session("Morning (AM)", routine.am_routine),
    session("Evening (PM)", routine.pm_routine)));
  content.replaceChildren(...parts);
}

async function init() {
  try {
    const routine = await apiFetch("/api/routine");
    if (!routine.skin_type) content.replaceChildren(scanCta("Complete your skin scan first"));
    else renderRoutine(routine);
  } catch (error) {
    if (error.status !== 401) content.replaceChildren(statusMessage(error.message, { error: true }));
  }
}

init();
