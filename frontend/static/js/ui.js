// Small DOM helpers shared by the /app pages. Everything user- or DB-provided is set
// via textContent, never innerHTML.

const PureSkinUI = (() => {
  const SCORE_FIELDS = [
    ["acne_score", "Acne"],
    ["redness_score", "Redness"],
    ["wrinkle_score", "Wrinkles"],
    ["pigmentation_score", "Pigmentation"],
    ["pore_score", "Pores"],
  ];

  // el("p", { className: "x", text: "hi" }, child1, child2)
  function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value === undefined || value === null) continue;
      if (key === "text") node.textContent = value;
      else if (key === "className") node.className = value;
      else if (key.startsWith("aria-") || key === "role" || key === "href") node.setAttribute(key, value);
      else node[key] = value;
    }
    node.append(...children.filter(Boolean));
    return node;
  }

  // Labelled 1–100 bars, same markup/style as the Skin Report page.
  function scoreBars(profile, { compact = false } = {}) {
    return el("ul", { className: compact ? "scores scores--compact" : "scores" },
      ...SCORE_FIELDS.map(([key, label]) => {
        const score = profile[key];
        const fill = el("div", { className: "score__fill" });
        fill.style.width = `${score}%`;
        return el("li", { className: "score" },
          el("div", { className: "score__label" }, el("span", { text: label }), el("span", { text: String(score) })),
          el("div", {
            className: "score__track", role: "meter", "aria-label": label,
            "aria-valuemin": "1", "aria-valuemax": "100", "aria-valuenow": String(score),
          }, fill));
      }));
  }

  function formatDate(iso) {
    return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
  }

  // "You haven't scanned yet" empty state with a CTA to the scan funnel.
  function scanCta(message = "You haven't scanned yet") {
    return el("div", { className: "empty-state" },
      el("h2", { className: "empty-state__title", text: message }),
      el("p", { text: "Take a quick selfie and answer a few questions to get your Skin Profile and routine." }),
      el("a", { className: "btn", href: "/scan/", text: "Start your skin scan" }));
  }

  function statusMessage(text, { error = false } = {}) {
    return el("p", { className: error ? "status status--error" : "status", role: error ? "alert" : "status", text });
  }

  function capitalize(text) {
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
  }

  return { SCORE_FIELDS, el, scoreBars, formatDate, scanCta, statusMessage, capitalize };
})();
