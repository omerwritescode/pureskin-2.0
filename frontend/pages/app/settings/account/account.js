// Account: the signed-in user's email, name and signup date (GET /api/account), and Log out.
// Everything from the API is set as text.

const { el, formatDate, statusMessage } = PureSkinUI;
const details = document.getElementById("account-details");

function renderAccount(account) {
  const row = (label, value) => [el("dt", { text: label }), el("dd", { text: value })];
  details.replaceChildren(
    el("dl", { className: "account-details" },
      ...row("Email", account.email),
      ...row("Name", account.full_name || "Not given"),
      ...row("Member since", formatDate(account.created_at))));
}

async function init() {
  try {
    renderAccount(await apiFetch("/api/account"));
  } catch (error) {
    if (error.status !== 401) details.replaceChildren(statusMessage(error.message, { error: true }));
  }
}

document.getElementById("logout").addEventListener("click", () => window.PureSkinAuth.logout());

init();
