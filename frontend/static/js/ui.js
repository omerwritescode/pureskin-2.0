// Small DOM helpers shared by the /app pages and /scan/report/. Everything user- or
// DB-provided is set via textContent, never innerHTML.

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

  // Labelled score strips, shared by /scan/report/, the Dashboard, the Skin Profile and
  // Progress. The band name is the main label (as text, never colour alone); the 1–100
  // number is smaller. Under it, one chip per band from bands.js, each as wide as its
  // range, the current one filled. Needs /static/js/bands.js loaded first.
  function scoreBars(profile, { compact = false } = {}) {
    return el("ul", { className: compact ? "scores scores--compact" : "scores" },
      ...SCORE_FIELDS.map(([key, label]) => {
        const score = profile[key];
        const band = PureSkinBands.bandFor(score);
        const bandName = band ? band.name : "Unknown";
        const chips = PureSkinBands.SCORE_BANDS.map((each) => {
          const chip = el("span", {
            className: each === band ? "score__chip score__chip--current" : "score__chip",
            text: each.name,
          });
          chip.style.flexGrow = String(each.max - each.min + 1);
          return chip;
        });
        return el("li", { className: "score" },
          el("div", { className: "score__label" },
            el("span", { text: label }),
            el("span", { className: "score__band" },
              el("span", { className: "score__band-name", text: bandName }),
              el("span", { className: "score__value", text: `${score}/100` }))),
          el("div", {
            className: "score__strip", role: "meter", "aria-label": label,
            "aria-valuemin": "1", "aria-valuemax": "100", "aria-valuenow": String(score),
            "aria-valuetext": `${bandName}, ${score} out of 100`,
          }, ...chips));
      }));
  }

  // The skin type as shown to the user. A default (the questionnaire had no oil/dry
  // answer: score_sources.skin_type "default") is never presented as a finding.
  function skinTypeText(profile) {
    const name = capitalize(profile.skin_type) || "Unknown";
    const assumed = Boolean(profile.score_sources && profile.score_sources.skin_type === "default");
    return { text: assumed ? `${name} (assumed)` : name, assumed, name };
  }

  function assumedSkinTypeNote(name) {
    return el("p", {
      className: "skin-type-note",
      text: `We couldn't tell your skin type from your answers, so we assumed ${name.toLowerCase()} skin. ` +
        "Answering the questions about how your skin feels by midday in a new scan gives a better result.",
    });
  }

  // A product whose ingredient list was copied from the brand's non-India website (the
  // catalog's market "global"). India rows get no badge. The label is text, not colour alone.
  function marketLabel(market) {
    return market === "global" ? "Global ingredient list" : null;
  }

  function marketBadge(market) {
    const label = marketLabel(market);
    return label ? el("span", { className: "market-badge", text: label }) : null;
  }

  function sensitiveIndicator() {
    return el("p", { className: "sensitive-indicator" },
      el("strong", { text: "Sensitive skin" }),
      el("span", { text: " · based on your answers about how your skin reacts" }));
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

  return {
    SCORE_FIELDS, el, scoreBars, skinTypeText, assumedSkinTypeNote, sensitiveIndicator,
    formatDate, scanCta, statusMessage, capitalize, marketLabel, marketBadge,
  };
})();
