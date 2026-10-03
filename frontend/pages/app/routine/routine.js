// Routine: AM/PM steps from GET /api/routine, with what was left out (and why) and other
// notes on top.

const { el, scanCta, statusMessage, capitalize, sensitiveIndicator } = PureSkinUI;
const content = document.getElementById("content");
const SESSION_LABELS = { am: "morning", pm: "evening" };

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
      notes.length ? el("span", { className: "routine-step__note", text: notes.join(" · ") }) : null,
      step.caution ? el("span", { className: "routine-step__caution", role: "note", text: step.caution }) : null));
}

function session(title, steps) {
  return el("section", { className: "card routine-session" },
    el("h2", { className: "card__title", text: title }),
    steps.length
      ? el("ol", { className: "routine-steps" }, ...steps.map(stepItem))
      : el("p", { className: "status", text: "No steps for this session." }));
}

// Every product the rules would have used but didn't, with the reason.
function leftOut(items) {
  return el("section", { className: "card routine-left-out" },
    el("h2", { className: "card__title", text: "Left out" }),
    el("ul", { className: "routine-left-out__list" },
      ...items.map((item) => {
        const when = item.sessions.map((s) => SESSION_LABELS[s] || s).join(" and ");
        return el("li", {},
          el("a", { href: `/app/catalog/${item.product_id}/`, text: item.product_name }),
          el("span", { className: "routine-left-out__when", text: ` (${when})` }),
          el("span", { text: ` — ${item.reason}` }));
      })));
}

// A stored profile can have no skin type (NULL): the routine then uses the normal steps.
function intro(routine) {
  if (routine.skin_type) {
    return el("p", { className: "routine-intro" },
      "Built for ", el("strong", { text: `${routine.skin_type} skin` }),
      " from your latest scan, using products in our catalog.");
  }
  return el("p", { className: "routine-intro" }, "Built from your latest scan, using products in our catalog.");
}

function renderRoutine(routine) {
  const parts = [intro(routine)];
  if (routine.is_sensitive) parts.push(sensitiveIndicator());
  // The profile has no questionnaire tags (saved before they existed, or dropped at signup).
  if (!routine.current_products_considered) {
    parts.push(el("p", { className: "routine-note", role: "note",
      text: "This routine doesn't take your current products into account." }));
  }
  if (routine.warnings.length) {
    parts.push(el("div", { className: "warning-box", role: "note" },
      el("h2", { className: "warning-box__title", text: "Heads up" }),
      el("ul", {}, ...routine.warnings.map((w) => el("li", { text: w })))));
  }
  parts.push(el("div", { className: "routine-grid" },
    session("Morning (AM)", routine.am_routine),
    session("Evening (PM)", routine.pm_routine)));
  if (routine.left_out.length) parts.push(leftOut(routine.left_out));
  content.replaceChildren(...parts);
}

async function init() {
  try {
    const routine = await apiFetch("/api/routine");
    // The API sets `message` only when there is no Skin Profile yet.
    if (routine.message) content.replaceChildren(scanCta("Complete your skin scan first"));
    else renderRoutine(routine);
  } catch (error) {
    if (error.status !== 401) content.replaceChildren(statusMessage(error.message, { error: true }));
  }
}

init();
