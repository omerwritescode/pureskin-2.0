// Chat (7d, Unit 4): one question at a time to POST /api/chat, the reply shown whole once it
// has ended (reading the response: /static/js/chat-stream.js). The conversation lives only in
// this script's memory: nothing is stored, and leaving the page (even into the back/forward
// cache) clears it. Everything from the user or the server is set as text (PureSkinUI.el),
// never as HTML.

const { el } = PureSkinUI;
const Chat = PureSkinChatStream;

const log = document.getElementById("chat-log");
const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");
const counter = document.getElementById("chat-count");
const sendButton = document.getElementById("chat-send");
const stopButton = document.getElementById("chat-stop");
const clearButton = document.getElementById("chat-clear");
const notice = document.getElementById("chat-notice");
const announcer = document.getElementById("chat-announce");
const alerter = document.getElementById("chat-alert");

let exchanges = []; // { user, assistant }: answered exchanges only; the last 3 are sent
let pending = null; // the question being answered: { controller, question, userItem, thinking, slowTimer }
let countdown = null; // { timer, rateLimited }

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---- Announcements: shown in the notice, spoken once by a live region ----
const speakTimers = new Map();

// Emptied first, so the same text twice in a row is still announced; a newer call (or "")
// cancels one not yet spoken, so a fast reply is never followed by a stale "Thinking…".
function speak(region, text) {
  clearTimeout(speakTimers.get(region));
  region.textContent = "";
  if (text) speakTimers.set(region, setTimeout(() => { region.textContent = text; }, 50));
}

function showNotice(text, { error = false, detail = null } = {}) {
  notice.replaceChildren(...[el("p", { className: "chat-notice__text", text }), detail].filter(Boolean));
  notice.classList.toggle("chat-notice--error", error);
  speak(error ? alerter : announcer, text);
}

function clearNotice() {
  stopCountdown();
  notice.replaceChildren();
  notice.classList.remove("chat-notice--error");
}

// Only the reason code: the server's detail text is for whoever runs it.
function technicalDetail(reason) {
  return el("details", { className: "chat-notice__detail" },
    el("summary", { text: "Technical detail" }),
    el("p", { text: `Reason code: ${reason || "unknown"}` }));
}

// ---- Countdowns: a 429 and a busy 503 only advise, and Send stays enabled: the server still
// serves red-flag templates (a 429 has its own, larger limit for them) and, while busy, the fixed reply ----
function startCountdown(result) {
  const until = Date.now() + result.wait * 1000;
  const rateLimited = result.kind === "rate_limited";
  const text = notice.querySelector(".chat-notice__text");
  const tick = () => {
    const left = Math.ceil((until - Date.now()) / 1000);
    if (left > 0) {
      text.textContent = Chat.messageFor(result, left);
      return;
    }
    stopCountdown();
    showNotice(Chat.MESSAGES.ready);
  };
  countdown = { timer: setInterval(tick, 1000), rateLimited };
  updateControls();
}

function stopCountdown() {
  if (!countdown) return;
  clearInterval(countdown.timer);
  countdown = null;
  updateControls();
}

// ---- The conversation ----
function author(name) {
  return el("p", { className: "chat-msg__author", text: name });
}

function addUserMessage(question) {
  const item = el("li", { className: "chat-msg chat-msg--user" }, author("You"),
    el("p", { className: "chat-msg__text", text: question }));
  log.append(item);
  return item;
}

// Visual only: the live region says "Thinking…" instead.
function addThinking() {
  const item = el("li", { className: "chat-msg chat-msg--reply chat-msg--thinking", "aria-hidden": "true" },
    author("PureSkin"), el("p", { className: "chat-thinking", text: Chat.MESSAGES.thinking }));
  log.append(item);
  item.scrollIntoView({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
  return item;
}

function sourceLink(source) {
  if (!source.url) return el("span", { className: "chat-source__label", text: source.label });
  const link = el("a", { className: "chat-source__label", href: source.url, text: source.label },
    el("span", { className: "visually-hidden", text: " (opens in a new tab)" }));
  // A new tab: following the link here would clear the conversation.
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function sources(result) {
  const items = result.notes.map((note) => {
    const item = el("li", { className: "chat-source" },
      el("span", { className: "chat-source__title", text: note.title }), ...note.sources.map(sourceLink));
    item.dataset.noteId = note.id;
    return item;
  });
  if (result.profileCited) {
    items.push(el("li", { className: "chat-source" },
      el("span", { className: "chat-source__title", text: "Your Skin Profile" })));
  }
  if (!items.length) return null;
  return el("div", { className: "chat-sources" },
    el("p", { className: "chat-sources__title", text: "Sources" }), el("ul", {}, ...items));
}

function addReply(result) {
  const safety = result.route === "template";
  const item = el("li", { className: safety ? "chat-msg chat-msg--reply chat-msg--safety" : "chat-msg chat-msg--reply" },
    author("PureSkin"),
    safety ? el("p", { className: "chat-msg__label", text: "Safety information" }) : null,
    el("p", { className: "chat-msg__text", text: result.text }),
    ...result.cautions.map((text) => el("p", { className: "chat-msg__caution" },
      el("strong", { text: "Caution: " }), text)),
    sources(result));
  log.append(item);
  item.scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" });
}

// ---- Controls ----
function updateControls() {
  counter.textContent = `${input.value.length}/${Chat.MAX_MESSAGE_CHARS}`;
  sendButton.hidden = Boolean(pending);
  stopButton.hidden = !pending;
  sendButton.disabled = !Chat.canSend(input.value);
  clearButton.disabled = !pending && !log.children.length;
}

async function ask() {
  const question = input.value.trim();
  if (pending || !Chat.canSend(question)) return;
  const keepFocus = document.activeElement === sendButton || document.activeElement === input;
  clearNotice();
  const request = {
    controller: new AbortController(), question, userItem: addUserMessage(question), thinking: null, slowTimer: null,
  };
  request.thinking = addThinking();
  pending = request;
  input.value = "";
  updateControls();
  if (keepFocus) input.focus(); // the Send button is hidden while the answer is coming
  speak(announcer, Chat.MESSAGES.thinking);

  const result = await Chat.send({
    message: question,
    exchanges,
    token: window.PureSkinAuth.getToken(),
    signal: request.controller.signal,
    onStart: (route) => {
      if (route === "model") request.slowTimer = setTimeout(() => stillThinking(request), Chat.STILL_THINKING_MS);
    },
  });
  finish(request, result);
}

function stillThinking(request) {
  if (pending !== request) return;
  request.thinking.querySelector(".chat-thinking").textContent = Chat.MESSAGES.stillThinking;
  speak(announcer, Chat.MESSAGES.stillThinking);
}

function finish(request, result) {
  if (pending !== request) return; // cleared, or the page was left, while it was coming
  clearTimeout(request.slowTimer);
  request.thinking.remove();
  pending = null;
  speak(announcer, ""); // a reply is read out by the log; anything else by showNotice
  if (document.activeElement === stopButton) input.focus();

  if (result.kind === "reply") {
    addReply(result);
    exchanges.push({ user: request.question, assistant: result.text }); // the text only, no caution lines
    updateControls();
    return;
  }

  // No reply: nothing from the stream is shown, and the question goes back in the box.
  request.userItem.remove();
  if (result.kind === "login") {
    window.PureSkinAuth.logout(); // clears the token and goes to /auth/
    return;
  }
  if (!input.value.trim()) input.value = request.question;
  const error = result.kind !== "stopped";
  const detail = result.kind === "setup" || result.kind === "unavailable" ? technicalDetail(result.reason) : null;
  showNotice(Chat.messageFor(result), { error, detail });
  if (result.kind === "rate_limited" || result.kind === "busy") startCountdown(result);
  updateControls();
}

function stop() {
  if (pending) pending.controller.abort();
}

// Cancels any answer in progress and forgets everything (Clear, and leaving the page).
function reset() {
  if (pending) {
    clearTimeout(pending.slowTimer);
    pending.controller.abort();
    pending = null;
  }
  exchanges = [];
  log.replaceChildren();
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  ask();
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    ask();
  }
});

input.addEventListener("input", updateControls);

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && pending) {
    event.preventDefault();
    stop();
  }
});

stopButton.addEventListener("click", stop);

clearButton.addEventListener("click", () => {
  reset();
  if (!countdown || !countdown.rateLimited) clearNotice(); // a 429 still holds on the server for ordinary questions
  updateControls();
  input.focus();
  speak(announcer, "Conversation cleared.");
});

// Nothing survives leaving the page: a Back from the back/forward cache shows it empty.
window.addEventListener("pagehide", () => {
  reset();
  clearNotice();
  input.value = "";
  updateControls();
});

updateControls();
