// Renders the Skin Profile page (profile.js) in Node with a stub DOM, once per branch, and
// fails if null or undefined reaches replaceChildren, append or textContent (the DOM turns
// them into the text "null" / "undefined"). Run by app/tests/test_frontend_profile.py:
//   node frontend_profile_render.mjs <repo root>
// Prints "ok <n>" on success; any failed assertion exits non-zero. No npm packages.

import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const root = process.argv[2];
const source = (path) => readFileSync(`${root}/frontend/${path}`, "utf8");
const nullish = (value) => value === null || value === undefined;

// Every null/undefined handed to the DOM is recorded (not thrown: profile.js's init() would
// catch a throw and show it as an error message), then the case fails if any were recorded.
let violations = [];
const refuse = (where, value) => {
  if (nullish(value)) violations.push(`${where} got ${value}`);
  return nullish(value);
};

// Just enough of a DOM node for ui.js and profile.js. Every way in refuses null/undefined.
class StubNode {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.ownText = "";
    this.attributes = {};
    this.style = {};
  }

  set textContent(value) {
    if (refuse(`<${this.tag}>.textContent`, value)) return;
    this.ownText = String(value);
    this.children = [];
  }

  get textContent() {
    return this.ownText + this.children.map((child) => (typeof child === "string" ? child : child.textContent)).join("");
  }

  append(...nodes) {
    this.children.push(...nodes.filter((node) => !refuse(`<${this.tag}>.append()`, node)));
  }

  replaceChildren(...nodes) {
    this.ownText = "";
    this.children = nodes.filter((node) => !refuse(`<${this.tag}>.replaceChildren()`, node));
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }
}

globalThis.window = globalThis;
const load = (path, name) => new Function(`${source(path)}\nreturn ${name};`)();
globalThis.PureSkinBands = load("static/js/bands.js", "PureSkinBands");
globalThis.PureSkinUI = load("static/js/ui.js", "PureSkinUI");

const PROFILE = {
  acne_score: 38, redness_score: 22, wrinkle_score: 12, pigmentation_score: 64, pore_score: 47,
  skin_type: "combination", is_sensitive: false, score_sources: { skin_type: "questionnaire" },
  created_at: "2026-10-12T10:30:00Z",
};

// Each case: what GET /api/profile gives (a value, or an error to throw).
const CASES = {
  "skin type from the answers, not sensitive": { profile: PROFILE },
  "assumed skin type, sensitive": {
    profile: { ...PROFILE, is_sensitive: true, score_sources: { skin_type: "default" } },
  },
  "no profile yet": { profile: null },
  "server error": { error: Object.assign(new Error("Request failed (500)."), { status: 500 }) },
};

let checks = 0;
for (const [name, { profile, error }] of Object.entries(CASES)) {
  violations = [];
  const content = new StubNode("section");
  globalThis.document = {
    createElement: (tag) => new StubNode(tag),
    getElementById: (id) => (id === "content" ? content : null),
  };
  const apiFetch = async () => {
    if (error) throw error;
    return profile;
  };
  new Function("apiFetch", source("pages/app/profile/profile.js"))(apiFetch);
  await new Promise((resolve) => setTimeout(resolve, 0)); // let init() finish
  assert.deepEqual(violations, [], `${name}: null or undefined reached the DOM`);
  assert.ok(content.children.length > 0, `${name}: nothing rendered`);
  const text = content.textContent;
  assert.ok(!/\bnull\b|\bundefined\b/.test(text), `${name}: rendered text contains null/undefined: ${text}`);
  checks += 1;
}

console.log(`ok ${checks}`);
