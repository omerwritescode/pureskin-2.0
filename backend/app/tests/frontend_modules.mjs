// Checks the frontend's pure logic in Node (no DOM, no npm packages). Run by
// app/tests/test_frontend_contract.py:  node frontend_modules.mjs <repo root>
// Prints "ok <n>" on success; any failed assertion exits non-zero.

import { readdirSync, readFileSync } from "node:fs";
import assert from "node:assert/strict";

const root = process.argv[2];
const source = (path) => readFileSync(`${root}/frontend/${path}`, "utf8");
globalThis.window = globalThis;
let checks = 0;
const check = (fn) => { fn(); checks += 1; };

// The scripts declare a top-level const (no modules in a plain-JS frontend): evaluate
// each one and hand back its global.
const load = (path, name) => new Function(`${source(path)}\nreturn ${name};`)();
const Bands = load("static/js/bands.js", "PureSkinBands");
globalThis.PureSkinBands = Bands;
const UI = load("static/js/ui.js", "PureSkinUI");
new Function(source("static/js/scan-api.js"))();
const Api = globalThis.PureSkinScanApi;

// ---- A top-level const is a global name in a browser but NOT a window property ----
// window = globalThis above hides that here, so check the source instead: a script that
// reads window.PureSkinBands crashes the page ("Cannot read properties of undefined").
const jsFiles = readdirSync(`${root}/frontend`, { recursive: true })
  .map((path) => path.replaceAll("\\", "/"))
  .filter((path) => path.endsWith(".js"));
const constGlobals = jsFiles.flatMap((path) =>
  [...source(path).matchAll(/^const (PureSkin\w+)/gm)].map((match) => match[1]));
check(() => assert.ok(constGlobals.includes("PureSkinBands")));  // the scan itself works
check(() => assert.deepEqual(
  jsFiles.flatMap((path) => constGlobals
    .filter((name) => source(path).includes(`window.${name}`))
    .map((name) => `${path}: window.${name} (use ${name})`)),
  []));

// ---- Bands: the shared cutoffs, never a guessed band ----
for (const [score, band] of [[1, "Low"], [30, "Low"], [31, "Moderate"], [60, "Moderate"], [61, "High"], [100, "High"]]) {
  check(() => assert.equal(Bands.bandFor(score).name, band));
}
for (const bad of [0, 101, 50.5, "50", null, undefined]) check(() => assert.equal(Bands.bandFor(bad), null));
check(() => assert.equal(Bands.legend(), "Low 1–30 · Moderate 31–60 · High 61–100"));

// ---- Skin type as shown on the Dashboard, Skin Profile and Skin Report ----
check(() => assert.deepEqual(
  UI.skinTypeText({ skin_type: "normal", score_sources: { skin_type: "default" } }),
  { text: "Normal (assumed)", assumed: true, name: "Normal" }));
check(() => assert.deepEqual(
  UI.skinTypeText({ skin_type: "oily", score_sources: { skin_type: "questionnaire" } }),
  { text: "Oily", assumed: false, name: "Oily" }));
check(() => assert.deepEqual(  // profiles saved before 7b-i have no score_sources
  UI.skinTypeText({ skin_type: "normal", score_sources: null }),
  { text: "Normal", assumed: false, name: "Normal" }));

// ---- First-login save: what each failure does (no retry loop on a rejection) ----
for (const [status, action] of [[401, "login"], [0, "retry"], [500, "retry"], [503, "retry"],
  [422, "rescan"], [400, "rescan"], [409, "rescan"]]) {
  check(() => assert.equal(Api.saveFailureAction(status), action));
}

// ---- One reading of the analysis responses ----
const respond = (status, body) => async () => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => { if (body === undefined) throw new Error("no JSON"); return body; },
});
const cases = [
  [respond(200, { acne_score: 40 }), { kind: "ok" }],
  [respond(422, { quality: { ok: false, issues: ["Too dim"] } }), { kind: "retake", issues: ["Too dim"] }],
  [respond(422, { detail: [{ loc: ["body"], msg: "x", type: "y" }] }), { kind: "error", message: Api.MESSAGES.generic }],
  [respond(422, { quality: { ok: false, issues: [] } }), { kind: "error", message: Api.MESSAGES.generic }],
  [respond(413, { detail: "too big" }), { kind: "error", message: Api.MESSAGES.tooLarge }],
  [respond(503, { detail: "model missing" }), { kind: "error", message: Api.MESSAGES.unavailable }],
  [respond(500, undefined), { kind: "error", message: Api.MESSAGES.generic }],
  [async () => { throw new TypeError("Failed to fetch"); }, { kind: "error", message: Api.MESSAGES.network }],
];
for (const [fetchImpl, expected] of cases) {
  globalThis.fetch = fetchImpl;
  const result = await Api.post("/x", { image: "data:...", answers: {} });
  check(() => assert.equal(result.kind, expected.kind));
  if (expected.message) check(() => assert.equal(result.message, expected.message));
  if (expected.issues) check(() => assert.deepEqual(result.issues, expected.issues));
}

console.log(`ok ${checks}`);
