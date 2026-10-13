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

// ---- The market badge's label (7c-iii): only a global-market list gets one ----
check(() => assert.equal(UI.marketLabel("global"), "Global ingredient list"));
for (const market of ["india", null, undefined, "", "GLOBAL"]) {
  check(() => assert.equal(UI.marketLabel(market), null));
}

// ---- The chat's stream (7d, Unit 4): one reading of POST /api/chat ----
const Chat = load("static/js/chat-stream.js", "PureSkinChatStream");
const enc = new TextEncoder();
const lines = (...events) => events.map((e) => `${e}\n`).join("");

// As the server writes it (json.dumps, ensure_ascii=False): non-ASCII goes out as raw UTF-8,
// so a chunk boundary can fall inside a character (é 2 bytes, ₹ 3, 🌞 4).
const START = '{"type": "start", "route": "model", "request_id": "0123456789ab", "config_versions": ' +
  '{"chat": "chat-1.5.0", "kb": "kb-1.0.0", "model": "qwen3.5:4b-q4_K_M", "model_digest": "d8b0f5e9"}}';
const SAMPLE_TEXT = lines(
  START,
  '{"type": "text", "text": "Reapply sunscreen every two hours outdoors.", "cites": ["kb-sun-sunscreen-use"]}',
  '{"type": "text", "text": "", "cites": ["profile"]}',
  '{"type": "text", "text": "Your Crème Solaire (₹499) goes on last 🌞.", "cites": ["profile"]}',
  '{"type": "citations", "chunks": [{"id": "kb-sun-sunscreen-use", "title": "Using sunscreen", "sources": [' +
    '{"publisher": "MedlinePlus (National Library of Medicine, NIH)", "url": "https://medlineplus.gov/sun.html", ' +
    '"role": "support"}, {"publisher": "NHS website", "url": "https://www.nhs.uk/x/", "role": "further_reading"}]}, ' +
    '{"id": "kb-app-routine", "title": "How your routine is built", "sources": [' +
    '{"publisher": "PureSkin repository", "url": null, "role": "support"}]}]}',
  '{"type": "caution", "text": "If a product gives you a rash, talk to a pharmacist or doctor before using it again."}',
  '{"type": "end", "reason": "answered"}',
);
const SAMPLE = enc.encode(SAMPLE_TEXT);
const parseAll = (pieces) => {
  const parser = Chat.createParser();
  const events = pieces.flatMap((piece) => parser.push(piece));
  return [...events, ...parser.end()];
};
const EXPECTED = parseAll([SAMPLE]);
check(() => assert.deepEqual(EXPECTED.map((e) => e.type),
  ["start", "text", "text", "text", "citations", "caution", "end"]));
check(() => assert.equal(EXPECTED[3].text, "Your Crème Solaire (₹499) goes on last 🌞."));
check(() => assert.deepEqual(EXPECTED[0], { type: "start", route: "model" }));  // only what the page uses

// Split at every byte offset, at every pair of offsets up to 8 bytes apart (a character or a
// line break cut into three pieces, everywhere), and byte by byte: always the same events.
let singleSplits = 0;
let pairSplits = 0;
check(() => {
  for (let i = 0; i <= SAMPLE.length; i += 1) {
    assert.deepEqual(parseAll([SAMPLE.subarray(0, i), SAMPLE.subarray(i)]), EXPECTED, `split at ${i}`);
    singleSplits += 1;
  }
});
check(() => {
  for (let i = 1; i < SAMPLE.length; i += 1) {
    for (let j = i + 1; j < Math.min(SAMPLE.length, i + 9); j += 1) {
      assert.deepEqual(parseAll([SAMPLE.subarray(0, i), SAMPLE.subarray(i, j), SAMPLE.subarray(j)]), EXPECTED,
        `split at ${i} and ${j}`);
      pairSplits += 1;
    }
  }
});
check(() => assert.deepEqual(parseAll([...SAMPLE].map((byte) => Uint8Array.of(byte))), EXPECTED));
check(() => assert.deepEqual(parseAll([enc.encode(SAMPLE_TEXT.replaceAll("\n", "\r\n"))]), EXPECTED));
check(() => assert.deepEqual(parseAll([enc.encode(SAMPLE_TEXT.replaceAll("\n", "\n\n  \n"))]), EXPECTED));
check(() => assert.deepEqual(parseAll([enc.encode(SAMPLE_TEXT.trimEnd())]), EXPECTED));  // no final newline

// Anything that isn't a known, well-formed event, in order, stops the whole reply.
const TEXT = '{"type": "text", "text": "Hi.", "cites": []}';
const END = '{"type": "end", "reason": "answered"}';
const badStreams = {
  "not JSON": [START, "{not json"],
  "an array": [START, "[1, 2]"],
  "null": [START, "null"],
  "unknown type": [START, '{"type": "debug", "text": "x"}'],
  "no type": [START, '{"text": "x"}'],
  "unknown route": ['{"type": "start", "route": "other"}'],
  "text not a string": [START, '{"type": "text", "text": 5, "cites": []}'],
  "text without cites": [START, '{"type": "text", "text": "Hi."}'],
  "a cite not a string": [START, '{"type": "text", "text": "Hi.", "cites": [1]}'],
  "note without title": [START, '{"type": "citations", "chunks": [{"id": "kb-x", "sources": []}]}'],
  "source url a number": [START, '{"type": "citations", "chunks": [{"id": "kb-x", "title": "T", "sources": ' +
    '[{"publisher": "P", "url": 5, "role": "support"}]}]}'],
  "empty caution": [START, TEXT, '{"type": "caution", "text": " "}'],
  "end without reason": [START, TEXT, '{"type": "end"}'],
  "error without code": [START, '{"type": "error"}'],
  "text before start": [TEXT, START],
  "two starts": [START, START],
  "after the end": [START, TEXT, END, TEXT],
  "after an error": [START, '{"type": "error", "code": "stream_broken"}', TEXT],
};
for (const [name, stream] of Object.entries(badStreams)) {
  check(() => assert.throws(() => parseAll([enc.encode(lines(...stream))]), Chat.ProtocolError, name));
}
check(() => assert.throws(() => parseAll([enc.encode(lines(START)), Uint8Array.of(0xff, 0x0a)]), Chat.ProtocolError));
check(() => assert.throws(  // the stream ends inside a character
  () => parseAll([enc.encode(lines(START) + '{"type": "text", "text": "€').subarray(0, -2)]), Chat.ProtocolError));

// ---- send(): the request, and what each response becomes ----
const streamOf = (chunks, { close = true, onCancel = null, failWith = null } = {}) => new ReadableStream({
  start(controller) {
    for (const chunk of chunks) controller.enqueue(typeof chunk === "string" ? enc.encode(chunk) : chunk);
    if (failWith) controller.error(failWith);
    else if (close) controller.close();
  },
  cancel() {
    if (onCancel) onCancel();
  },
});
const ndjsonResponse = (body, type = "application/x-ndjson") =>
  new Response(body, { status: 200, headers: { "Content-Type": type } });
let lastRequest = null;
const serve = (makeResponse) => {
  globalThis.fetch = async (url, init) => {
    lastRequest = { url, init };
    return makeResponse(init);
  };
};
const chatSend = (options = {}) => Chat.send({ message: "  How often should I reapply sunscreen?  ", ...options });

// An answer: text joined (an empty piece only cites), the NHS source hidden, the repository
// relabelled, the caution kept apart from the text.
{
  const starts = [];
  serve(() => ndjsonResponse(streamOf([SAMPLE.subarray(0, 100), SAMPLE.subarray(100)])));
  const result = await chatSend({ token: "tok", onStart: (route) => starts.push(route),
    exchanges: [{ user: "Hi", assistant: "Hello." }] });
  check(() => assert.deepEqual(result, {
    kind: "reply",
    route: "model",
    text: "Reapply sunscreen every two hours outdoors. Your Crème Solaire (₹499) goes on last 🌞.",
    cautions: ["If a product gives you a rash, talk to a pharmacist or doctor before using it again."],
    notes: [
      { id: "kb-sun-sunscreen-use", title: "Using sunscreen", sources: [
        { label: "MedlinePlus (National Library of Medicine, NIH)", url: "https://medlineplus.gov/sun.html" }] },
      { id: "kb-app-routine", title: "How your routine is built", sources: [
        { label: "PureSkin (how the app works)", url: null }] },
    ],
    profileCited: true,
    endReason: "answered",
  }));
  check(() => assert.deepEqual(starts, ["model"]));
  check(() => assert.equal(lastRequest.url, "/api/chat"));
  check(() => assert.equal(lastRequest.init.method, "POST"));
  check(() => assert.equal(lastRequest.init.headers.Authorization, "Bearer tok"));
  check(() => assert.equal(lastRequest.init.headers["Content-Type"], "application/json"));
  check(() => assert.deepEqual(JSON.parse(lastRequest.init.body), {
    message: "How often should I reapply sunscreen?",
    history: [{ role: "user", content: "Hi" }, { role: "assistant", content: "Hello." }],
  }));
}

const TEMPLATE_STREAM = lines('{"type": "start", "route": "template"}',
  '{"type": "text", "text": "Call the number now.", "cites": []}', '{"type": "end", "reason": "template"}');
serve(() => ndjsonResponse(streamOf([TEMPLATE_STREAM])));
{
  const result = await chatSend();
  check(() => assert.equal(result.kind, "reply"));
  check(() => assert.equal(result.route, "template"));
  check(() => assert.deepEqual([result.notes, result.cautions, result.profileCited], [[], [], false]));
}

serve(() => ndjsonResponse(streamOf([lines('{"type": "start", "route": "no_answer"}',
  '{"type": "text", "text": "I don\'t know.", "cites": []}', '{"type": "caution", "text": "Caution."}',
  '{"type": "end", "reason": "no_answer_line"}')])));
{
  const result = await chatSend();
  check(() => assert.deepEqual([result.kind, result.route, result.text, result.cautions, result.endReason],
    ["reply", "no_answer", "I don't know.", ["Caution."], "no_answer_line"]));
}

// A link that isn't https is never kept.
for (const url of ["http://medlineplus.gov/x.html", "javascript:alert(1)", "//evil.example/x"]) {
  serve(() => ndjsonResponse(streamOf([lines(START, TEXT, '{"type": "citations", "chunks": [{"id": "kb-x", ' +
    `"title": "T", "sources": [{"publisher": "P", "url": ${JSON.stringify(url)}, "role": "support"}]}]}`, END)])));
  const result = await chatSend();
  check(() => assert.equal(result.notes[0].sources[0].url, null));
}

// Fail closed: nothing from a stream that didn't end properly.
const ERROR_STREAM = lines(START, '{"type": "error", "code": "stream_broken"}');
{
  let clock = [0, 2000];
  serve(() => ndjsonResponse(streamOf([ERROR_STREAM])));
  let result = await chatSend({ now: () => clock.shift() });
  check(() => assert.deepEqual(result, { kind: "error", code: "stream_broken", elapsedMs: 2000 }));
  check(() => assert.equal(Chat.messageFor(result), Chat.MESSAGES.error));
  clock = [0, 50000];  // the first answer after the model loads can pass the server's 60 s timeout
  serve(() => ndjsonResponse(streamOf([ERROR_STREAM])));
  result = await chatSend({ now: () => clock.shift() });
  check(() => assert.equal(Chat.messageFor(result), Chat.MESSAGES.coldStart));
}
for (const [name, response, kind] of [
  ["no end", () => ndjsonResponse(streamOf([lines(START, TEXT)])), "cut"],
  ["nothing at all", () => ndjsonResponse(streamOf([])), "cut"],
  ["dropped mid-stream", () => ndjsonResponse(streamOf([lines(START, TEXT)], { failWith: new TypeError("network") })), "cut"],
  ["an end with no text", () => ndjsonResponse(streamOf([lines(START, END)])), "protocol"],
  ["a bad line", () => ndjsonResponse(streamOf([lines(START, TEXT, "{oops", END)])), "protocol"],
  ["not NDJSON", () => ndjsonResponse(streamOf(["<html>"]), "text/html"), "protocol"],
]) {
  serve(response);
  const result = await chatSend();
  check(() => assert.equal(result.kind, kind, name));
}
{
  let cancelled = 0;  // a bad line, or a wrong content type, releases the body (and the server's slot)
  serve(() => ndjsonResponse(streamOf([lines(START, "{oops")], { close: false, onCancel: () => { cancelled += 1; } })));
  await chatSend();
  serve(() => ndjsonResponse(streamOf(["<html>"], { close: false, onCancel: () => { cancelled += 1; } }), "text/html"));
  await chatSend();
  check(() => assert.equal(cancelled, 2));
}

// Stop: mid-stream (the answer still being generated) and before the response arrives.
{
  let cancelled = 0;
  const controller = new AbortController();
  serve(() => ndjsonResponse(streamOf([lines(START)], { close: false, onCancel: () => { cancelled += 1; } })));
  const result = await chatSend({ signal: controller.signal, onStart: () => controller.abort() });
  check(() => assert.deepEqual(result, { kind: "stopped" }));
  check(() => assert.equal(cancelled, 1));  // the body is cancelled, so the connection closes
}
{
  const controller = new AbortController();
  controller.abort();
  globalThis.fetch = async () => { throw new DOMException("The operation was aborted.", "AbortError"); };
  const result = await chatSend({ signal: controller.signal });
  check(() => assert.deepEqual(result, { kind: "stopped" }));
}
globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
{
  const result = await chatSend();
  check(() => assert.deepEqual(result, { kind: "offline" }));
  check(() => assert.equal(Chat.messageFor(result), Chat.MESSAGES.offline));
}

// ---- Status codes before the stream ----
const jsonResponse = (status, body, headers = {}) => new Response(body === undefined ? "oops" : JSON.stringify(body),
  { status, headers: { "Content-Type": "application/json", ...headers } });
const statusCases = [
  [jsonResponse(401, { detail: "Not authenticated" }), { kind: "login" }],
  [jsonResponse(413, { detail: "The chat request is over 16 KB." }), { kind: "too_large" }],
  [jsonResponse(422, { detail: [{ loc: ["message"], msg: "x", type: "y" }] }), { kind: "invalid" }],
  [jsonResponse(429, { detail: "Too many" }, { "Retry-After": "17" }), { kind: "rate_limited", wait: 17 }],
  [jsonResponse(429, { detail: "Too many" }, { "Retry-After": "43200" }), { kind: "rate_limited", wait: 43200 }],
  [jsonResponse(429, { detail: "Too many" }), { kind: "rate_limited", wait: 60 }],
  [jsonResponse(429, { detail: "Too many" }, { "Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT" }),
    { kind: "rate_limited", wait: 60 }],
  [jsonResponse(429, { detail: "Too many" }, { "Retry-After": "0" }), { kind: "rate_limited", wait: 1 }],
  [jsonResponse(503, { detail: "x", reason: "busy" }, { "Retry-After": "10" }), { kind: "busy", wait: 10 }],
  [jsonResponse(503, { detail: "x", reason: "busy" }), { kind: "busy", wait: 10 }],
  [jsonResponse(503, { detail: "x", reason: "unreachable" }), { kind: "unavailable", reason: "unreachable" }],
  ...["non_loopback_host", "cloud_tag", "unpinned_model", "missing_model", "moved_tag"].map((reason) =>
    [jsonResponse(503, { detail: "x", reason }), { kind: "setup", reason }]),
  [jsonResponse(503, { detail: "x", reason: "constructor" }), { kind: "unavailable", reason: null }],
  [jsonResponse(503, { detail: "x" }), { kind: "unavailable", reason: null }],
  [jsonResponse(503, undefined), { kind: "unavailable", reason: null }],
  [jsonResponse(500, undefined), { kind: "failed", status: 500 }],
];
for (const [response, expected] of statusCases) {
  serve(() => response);
  const result = await chatSend();
  check(() => assert.deepEqual(result, expected));
}

// ---- What the user is told: never the server's detail text ----
check(() => assert.equal(Chat.messageFor({ kind: "busy", wait: 10 }),
  "Another question is being answered right now. Try again in 10 s."));
check(() => assert.equal(Chat.messageFor({ kind: "rate_limited", wait: 60 }, 42),
  "You've sent a lot of messages. You can send another in 42 s. " +
  "If you need urgent help, call 112, India's emergency number."));
check(() => assert.ok(Chat.messageFor({ kind: "rate_limited", wait: 9 }).includes(`call ${Chat.EMERGENCY_NUMBER},`)));
for (const kind of ["stopped", "offline", "login", "too_large", "invalid", "rate_limited", "busy", "unavailable",
  "setup", "error", "cut", "protocol", "failed"]) {
  const message = Chat.messageFor({ kind, wait: 5, elapsedMs: 0, reason: "unreachable", status: 500 });
  check(() => assert.ok(typeof message === "string" && message.length > 10 && !message.includes("undefined"), kind));
  check(() => assert.ok(!message.includes("OLLAMA") && !message.includes("CHAT_MODEL"), kind));
}
check(() => assert.equal(Chat.messageFor({ kind: "anything else" }), Chat.MESSAGES.failed));

// ---- The request: the last 3 exchanges, the reply text only, clipped as the server counts ----
const exchange = (n) => ({ user: `Question ${n}`, assistant: `Answer ${n}.` });
check(() => assert.deepEqual(Chat.buildRequest(" Next? ", [1, 2, 3, 4].map(exchange)), {
  message: "Next?",
  history: [2, 3, 4].flatMap((n) => [{ role: "user", content: `Question ${n}` },
    { role: "assistant", content: `Answer ${n}.` }]),
}));
check(() => assert.deepEqual(Chat.buildRequest("Hi", []), { message: "Hi", history: [] }));
check(() => assert.equal(Chat.buildRequest("Hi", [1, 2, 3, 4, 5, 6, 7].map(exchange)).history.length,
  Chat.MAX_HISTORY_TURNS));
check(() => assert.deepEqual(  // an exchange with no reply text is never sent
  Chat.buildRequest("Hi", [exchange(1), { user: "Lost", assistant: "" }, { user: " ", assistant: "x" }]).history.length, 2));
{
  const long = Chat.buildRequest("Hi", [{ user: "é".repeat(600), assistant: "🌞".repeat(3001) }]).history;
  check(() => assert.equal(Array.from(long[0].content).length, Chat.MAX_MESSAGE_CHARS));
  check(() => assert.equal(Array.from(long[1].content).length, Chat.MAX_ASSISTANT_CHARS));
  check(() => assert.ok(!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])/.test(long[1].content)));  // no half emoji
}
for (const [message, ok] of [["", false], ["   ", false], ["a", true], ["x".repeat(500), true],
  ["x".repeat(501), false], ["🌞".repeat(500), true], [` ${"x".repeat(500)} `, true], [null, false]]) {
  check(() => assert.equal(Chat.canSend(message), ok, String(message).slice(0, 10)));
}

// ---- Waits ----
for (const [seconds, text] of [[0, "0 s"], [1, "1 s"], [59, "59 s"], [60, "1 min"], [61, "2 min"],
  [3540, "59 min"], [3599, "about 1 h"], [3600, "about 1 h"], [3661, "about 1 h 2 min"], [86400, "about 24 h"]]) {
  check(() => assert.equal(Chat.formatWait(seconds), text));
}
for (const [value, seconds] of [["17", 17], [" 5 ", 5], ["", 60], [null, 60], ["-3", 60], ["1.5", 60], ["9999999", 60]]) {
  check(() => assert.equal(Chat.retryAfter(value, 60), seconds));
}

console.log(`ok ${checks}`);
console.log(`chat parser: the same ${EXPECTED.length} events from ${SAMPLE.length} bytes at every one of ` +
  `${singleSplits} single split points, ${pairSplits} two-way splits (up to 8 bytes apart) and byte by byte`);
