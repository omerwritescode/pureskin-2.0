// Progress: the user's saved scans (GET /api/progress, oldest first) as a table, no chart.
//   0 scans: the scan call to action.
//   1 scan:  that scan's scores, and how to add another.
//   2+:      one row per scan, each score as "Moderate (42)": the band from PureSkinBands
//            (the shared cutoffs), never a band of its own.
// Everything from the API is set as text.

const { el, SCORE_FIELDS, scoreBars, formatDate, scanCta, statusMessage } = PureSkinUI;
const content = document.getElementById("progress");

const PROGRESS_URL = "/api/progress";

function scanTime(iso) {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// "Moderate (42)"; a score outside 1-100 gets no band ("Unknown (0)"), never a guessed one.
function bandCell(score) {
  const band = PureSkinBands.bandFor(score);
  return `${band ? band.name : "Unknown"} (${score})`;
}

function legend() {
  return el("p", { className: "progress-legend", text: `Higher means more noticeable. ${PureSkinBands.legend()}.` });
}

function rescanLink(text) {
  return el("p", { className: "progress-rescan" },
    el("a", { href: "/scan/", text }),
    " · after the scan, log in from the report page to save it to your account.");
}

function renderOne(scan) {
  content.replaceChildren(
    el("div", { className: "card" },
      el("h2", { className: "card__title", text: "One scan so far" }),
      el("p", {
        className: "card__meta",
        text: `From ${formatDate(scan.created_at)}. Take another scan to see how your scores change.`,
      }),
      legend(),
      scoreBars(scan)),
    rescanLink("Take a new scan"));
}

function renderTable(scans) {
  const head = el("tr", {},
    el("th", { scope: "col", text: "Scan" }),
    ...SCORE_FIELDS.map(([, label]) => el("th", { scope: "col", text: label })));
  const rows = scans.map((scan) => el("tr", {},
    el("th", { scope: "row", text: scanTime(scan.created_at) }),
    ...SCORE_FIELDS.map(([key]) => el("td", { text: bandCell(scan[key]) }))));
  content.replaceChildren(
    el("h2", { className: "progress-heading", text: `Your ${scans.length} scans, oldest first` }),
    legend(),
    el("div", { className: "progress-table-wrap", role: "region", "aria-label": "Your scores at each scan", tabIndex: 0 },
      el("table", { className: "progress-table" },
        el("caption", { text: "Your scores at each scan" }),
        el("thead", {}, head),
        el("tbody", {}, ...rows))),
    rescanLink("Take a new scan"));
}

async function init() {
  try {
    const { scans } = await apiFetch(PROGRESS_URL);
    if (scans.length === 0) content.replaceChildren(scanCta());
    else if (scans.length === 1) renderOne(scans[0]);
    else renderTable(scans);
  } catch (error) {
    if (error.status !== 401) content.replaceChildren(statusMessage(error.message, { error: true }));
  }
}

init();
