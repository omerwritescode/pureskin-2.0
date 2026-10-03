// Score bands: the ONE frontend definition of Low / Moderate / High for a 1-100 score.
//
// The cutoffs MUST match SCORE_BANDS in
// backend/app/services/skin_profile/skin_profile_config.py. A backend test
// (app/tests/test_frontend_contract.py) parses the list below and fails if they drift,
// so keep each band on one line in this exact form.

const PureSkinBands = (() => {
  const SCORE_BANDS = [
    { name: "Low", min: 1, max: 30 },
    { name: "Moderate", min: 31, max: 60 },
    { name: "High", min: 61, max: 100 },
  ];

  // The band for a score, or null for anything outside 1-100 (never guess a band).
  function bandFor(score) {
    if (!Number.isInteger(score)) return null;
    return SCORE_BANDS.find((band) => score >= band.min && score <= band.max) || null;
  }

  // "Low 1–30 · Moderate 31–60 · High 61–100", built from the list above.
  function legend() {
    return SCORE_BANDS.map((band) => `${band.name} ${band.min}–${band.max}`).join(" · ");
  }

  return { SCORE_BANDS, bandFor, legend };
})();
