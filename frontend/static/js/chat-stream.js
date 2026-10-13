// POST /api/chat and its stream of events, with ONE reading of every response. Pure: no
// DOM, no storage, and it never logs anything (the body holds the user's own words).
//
//   const result = await PureSkinChatStream.send({ message, exchanges, token, signal, onStart });
//   result.kind === "reply" -> show it: result.route, .text, .cautions, .notes, .profileCited
//   any other kind          -> show PureSkinChatStream.messageFor(result), nothing from the stream
//
// Fail closed: a reply exists only once its "end" event has arrived. The caution line comes
// after the answer, so an answer cut short (an error event, a dropped connection, Stop, a
// line that isn't a known event) is never shown, not even in part.
//
// The event shapes are app/api/chat.py's. test_frontend_contract.py checks the names and
// limits below against the backend; frontend_modules.mjs checks the logic in Node.

const PureSkinChatStream = (() => {
  const CHAT_URL = "/api/chat";

  // The server's limits (chat_config.py).
  const MAX_MESSAGE_CHARS = 500;
  const MAX_HISTORY_TURNS = 6; // 3 exchanges
  const MAX_ASSISTANT_CHARS = 3000;

  // chat_config.EMERGENCY_NUMBER: the same sourced number as the router templates.
  const EMERGENCY_NUMBER = "112";

  const EVENT_TYPES = ["start", "text", "citations", "caution", "end", "error"];
  const ROUTES = ["model", "template", "no_answer"];

  // A 503's reason (chat_config.STATUS_REASONS, and "busy") -> the kind of result. The page
  // shows the reason code only, never the server's detail text.
  const REASONS = {
    busy: "busy",
    unreachable: "unavailable",
    non_loopback_host: "setup",
    cloud_tag: "setup",
    unpinned_model: "setup",
    missing_model: "setup",
    moved_tag: "setup",
  };

  // The notes about how the app works cite this repository (no link); shown as the label.
  const REPOSITORY_PUBLISHER = "PureSkin repository";
  const REPOSITORY_LABEL = "PureSkin (how the app works)";

  const STILL_THINKING_MS = 10000; // then the "first answer can take up to a minute" hint
  const COLD_START_MS = 45000; // an error this late: the model was probably still loading
  const RETRY_FALLBACK = { busy: 10, rate_limited: 60 }; // seconds, when Retry-After is unusable

  const MESSAGES = {
    thinking: "Thinking…",
    stillThinking: "Still thinking. The first answer after the chat starts up can take up to a minute.",
    stopped: "Stopped. Your question is back in the box.",
    offline: "We couldn't reach PureSkin. Check your connection and try again.",
    login: "Your session has expired. Please log in again.",
    tooLarge: "That message couldn't be sent. Please shorten it and try again.",
    invalid: "That message couldn't be sent. Please try again.",
    rateLimited: (wait) => `You've sent a lot of messages. You can send another in ${wait}. ` +
      `If you need urgent help, call ${EMERGENCY_NUMBER}, India's emergency number.`,
    busy: (wait) => `Another question is being answered right now. Try again in ${wait}.`,
    ready: "You can send again.",
    unavailable: "The chat isn't available right now: its model isn't running. Please try again later.",
    setup: "The chat is switched off: it isn't set up correctly on this server.",
    error: "The answer couldn't be finished. Please try again.",
    coldStart: "The chat's model may still have been starting up. Wait a minute, then ask again.",
    cut: "The connection dropped before the answer finished. Please try again.",
    protocol: "The chat sent something unexpected, so nothing was shown. Please try again.",
    failed: "Something went wrong. Please try again.",
  };

  // Never carries any text from the stream (it could hold the answer).
  class ProtocolError extends Error {
    constructor(message) {
      super(message);
      this.name = "ProtocolError";
    }
  }

  const isString = (value) => typeof value === "string";
  const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const isSource = (s) => isObject(s) && isString(s.publisher) && (s.url === null || isString(s.url)) &&
    isString(s.role);
  const isNote = (c) => isObject(c) && isString(c.id) && isString(c.title) && Array.isArray(c.sources) &&
    c.sources.every(isSource);

  // One line -> a checked event. Only the fields the page uses are kept.
  function toEvent(line) {
    let data;
    try {
      data = JSON.parse(line);
    } catch {
      throw new ProtocolError("a line is not JSON");
    }
    if (!isObject(data)) throw new ProtocolError("a line is not an object");
    const bad = () => new ProtocolError(`a malformed ${data.type} event`);
    switch (data.type) {
      case "start":
        if (!ROUTES.includes(data.route)) throw bad();
        return { type: "start", route: data.route };
      case "text":
        if (!isString(data.text) || !Array.isArray(data.cites) || !data.cites.every(isString)) throw bad();
        return { type: "text", text: data.text, cites: data.cites };
      case "citations":
        if (!Array.isArray(data.chunks) || !data.chunks.every(isNote)) throw bad();
        return { type: "citations", chunks: data.chunks };
      case "caution":
        if (!isString(data.text) || !data.text.trim()) throw bad();
        return { type: "caution", text: data.text };
      case "end":
        if (!isString(data.reason)) throw bad();
        return { type: "end", reason: data.reason };
      case "error":
        if (!isString(data.code)) throw bad();
        return { type: "error", code: data.code };
      default:
        throw new ProtocolError("an unknown event type");
    }
  }

  // NDJSON from bytes, in whatever pieces they arrive: a line, or a UTF-8 character, can be
  // split across chunks. "start" comes first, once; nothing may follow "end" or "error".
  function createParser() {
    const decoder = new TextDecoder("utf-8", { fatal: true });
    let pending = "";
    let stage = "before"; // "before" the start, "open", "closed" after end or error

    function decode(bytes) {
      try {
        return bytes ? decoder.decode(bytes, { stream: true }) : decoder.decode();
      } catch {
        throw new ProtocolError("the stream is not UTF-8");
      }
    }

    function take(final) {
      const lines = pending.split("\n");
      pending = final ? "" : lines.pop();
      const events = [];
      for (const raw of lines) {
        const line = raw.endsWith("\r") ? raw.slice(0, -1) : raw;
        if (!line.trim()) continue;
        if (stage === "closed") throw new ProtocolError("an event after the end");
        const event = toEvent(line);
        if ((stage === "before") !== (event.type === "start")) throw new ProtocolError("start must come first, once");
        stage = event.type === "end" || event.type === "error" ? "closed" : "open";
        events.push(event);
      }
      return events;
    }

    return {
      push(bytes) {
        pending += decode(bytes);
        return take(false);
      },
      end() {
        pending += decode(null);
        return take(true);
      },
    };
  }

  // The citations event's notes, as shown under a reply: each note's title and its
  // supporting sources. Further-reading sources (the NHS pages) are never shown: they must
  // not read as the source of a sentence. A link is kept only if it is https.
  function notesFrom(chunks) {
    const seen = new Set();
    return chunks.filter((chunk) => !seen.has(chunk.id) && seen.add(chunk.id)).map((chunk) => ({
      id: chunk.id,
      title: chunk.title,
      sources: chunk.sources.filter((source) => source.role === "support").map((source) => ({
        label: source.publisher === REPOSITORY_PUBLISHER ? REPOSITORY_LABEL : source.publisher,
        url: isString(source.url) && source.url.startsWith("https://") ? source.url : null,
      })),
    }));
  }

  async function readReply(response, { signal, onStart, startedAt, now }) {
    const reader = response.body.getReader();
    const release = () => {
      reader.cancel().catch(() => {});
    };
    if (signal && signal.aborted) {
      release();
      return { kind: "stopped" };
    }
    // Stop cancels the body as well as the fetch, so the connection closes and the server
    // frees its generation slot.
    if (signal) signal.addEventListener("abort", release, { once: true });

    const parser = createParser();
    const reply = { route: null, sentences: [], cites: new Set(), chunks: [], cautions: [] };
    let last = null; // the end or error event
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (signal && signal.aborted) return { kind: "stopped" };
        for (const event of done ? parser.end() : parser.push(value)) {
          if (event.type === "start") {
            reply.route = event.route;
            if (onStart) onStart(event.route);
          } else if (event.type === "text") {
            if (event.text.trim()) reply.sentences.push(event.text.trim());
            event.cites.forEach((cite) => reply.cites.add(cite));
          } else if (event.type === "citations") {
            reply.chunks.push(...event.chunks);
          } else if (event.type === "caution") {
            reply.cautions.push(event.text);
          } else {
            last = event;
          }
        }
        if (done) break;
      }
    } catch (error) {
      if (signal && signal.aborted) return { kind: "stopped" };
      if (error instanceof ProtocolError) {
        release();
        return { kind: "protocol" };
      }
      return { kind: "cut" }; // the connection broke mid-stream
    } finally {
      if (signal) signal.removeEventListener("abort", release);
    }

    if (!last) return { kind: "cut" };
    if (last.type === "error") return { kind: "error", code: last.code, elapsedMs: now() - startedAt };
    if (!reply.sentences.length) return { kind: "protocol" }; // an end with nothing to show
    return {
      kind: "reply",
      route: reply.route,
      text: reply.sentences.join(" "),
      cautions: reply.cautions,
      notes: notesFrom(reply.chunks),
      profileCited: reply.cites.has("profile"),
      endReason: last.reason,
    };
  }

  // Seconds from a Retry-After header (the server sends whole seconds).
  function retryAfter(value, fallback) {
    const text = isString(value) ? value.trim() : "";
    return /^\d{1,6}$/.test(text) ? Math.max(1, Number(text)) : fallback;
  }

  async function classify(response) {
    const { status, headers } = response;
    if (status === 401) return { kind: "login" };
    if (status === 413) return { kind: "too_large" };
    if (status === 422) return { kind: "invalid" };
    if (status === 429) {
      return { kind: "rate_limited", wait: retryAfter(headers.get("Retry-After"), RETRY_FALLBACK.rate_limited) };
    }
    if (status === 503) {
      const data = await response.json().catch(() => null);
      const reason = isObject(data) && isString(data.reason) && Object.hasOwn(REASONS, data.reason)
        ? data.reason : null;
      if (reason === "busy") {
        return { kind: "busy", wait: retryAfter(headers.get("Retry-After"), RETRY_FALLBACK.busy) };
      }
      return { kind: reason ? REASONS[reason] : "unavailable", reason };
    }
    return { kind: "failed", status };
  }

  // Characters as the server counts them (code points), so a clip never splits an emoji.
  function clip(text, max) {
    const chars = Array.from(text);
    return chars.length <= max ? text : chars.slice(0, max).join("");
  }

  function canSend(message) {
    const text = isString(message) ? message.trim() : "";
    return text.length > 0 && Array.from(text).length <= MAX_MESSAGE_CHARS;
  }

  // The body: the message and the last 3 exchanges. An exchange is { user, assistant }, where
  // assistant is the reply's text only, never its caution lines.
  function buildRequest(message, exchanges) {
    const history = exchanges
      .filter((e) => isString(e.user) && e.user.trim() && isString(e.assistant) && e.assistant.trim())
      .slice(-MAX_HISTORY_TURNS / 2)
      .flatMap((e) => [
        { role: "user", content: clip(e.user.trim(), MAX_MESSAGE_CHARS) },
        { role: "assistant", content: clip(e.assistant, MAX_ASSISTANT_CHARS) },
      ]);
    return { message: message.trim(), history };
  }

  async function send({ message, exchanges = [], token = null, signal = null, onStart = null, now = Date.now }) {
    const startedAt = now();
    const headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    let response;
    try {
      response = await fetch(CHAT_URL, {
        method: "POST", headers, body: JSON.stringify(buildRequest(message, exchanges)), signal, cache: "no-store",
      });
    } catch {
      return { kind: signal && signal.aborted ? "stopped" : "offline" };
    }
    if (response.status !== 200) return classify(response);
    const type = (response.headers.get("Content-Type") || "").toLowerCase();
    if (!type.startsWith("application/x-ndjson") || !response.body) {
      if (response.body) response.body.cancel().catch(() => {});
      return { kind: "protocol" };
    }
    return readReply(response, { signal, onStart, startedAt, now });
  }

  // "42 s", "4 min", "about 3 h 10 min": the daily limit's wait can be hours.
  function formatWait(seconds) {
    const s = Math.max(0, Math.ceil(seconds));
    if (s < 60) return `${s} s`;
    const minutes = Math.ceil(s / 60);
    if (minutes < 60) return `${minutes} min`;
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return m ? `about ${h} h ${m} min` : `about ${h} h`;
  }

  const FIXED = {
    stopped: MESSAGES.stopped, offline: MESSAGES.offline, login: MESSAGES.login,
    too_large: MESSAGES.tooLarge, invalid: MESSAGES.invalid, unavailable: MESSAGES.unavailable,
    setup: MESSAGES.setup, cut: MESSAGES.cut, protocol: MESSAGES.protocol,
  };

  // What to tell the user for any result but a reply. secondsLeft: for a countdown.
  function messageFor(result, secondsLeft = result.wait) {
    if (result.kind === "rate_limited") return MESSAGES.rateLimited(formatWait(secondsLeft));
    if (result.kind === "busy") return MESSAGES.busy(formatWait(secondsLeft));
    if (result.kind === "error") return result.elapsedMs >= COLD_START_MS ? MESSAGES.coldStart : MESSAGES.error;
    return Object.hasOwn(FIXED, result.kind) ? FIXED[result.kind] : MESSAGES.failed;
  }

  return {
    CHAT_URL, MAX_MESSAGE_CHARS, MAX_HISTORY_TURNS, MAX_ASSISTANT_CHARS, EMERGENCY_NUMBER, EVENT_TYPES,
    ROUTES, REASONS, REPOSITORY_LABEL, STILL_THINKING_MS, COLD_START_MS, MESSAGES, ProtocolError,
    createParser, send, buildRequest, canSend, retryAfter, formatWait, messageFor,
  };
})();
