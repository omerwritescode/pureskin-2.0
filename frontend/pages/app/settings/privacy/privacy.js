// Privacy page: download the user's data (GET /api/account/export) and delete the account
// (DELETE /api/account). Everything shown is set as text; nothing is logged or kept.
//
// The download goes through apiFetch, because a plain link can't send the login token: the
// JSON becomes a Blob, saved through a temporary object URL that is revoked straight after.
// Delete needs the password. A wrong one is a 403 (a 401 would log the user out); after a
// 204 the pre-signup scan keys and the login token are cleared and the page goes to /auth/.

const { el, statusMessage } = PureSkinUI;

const downloadButton = document.getElementById("download");
const downloadStatus = document.getElementById("download-status");
const deleteForm = document.getElementById("delete-form");
const deletePassword = document.getElementById("delete-password");
const deleteConfirm = document.getElementById("delete-confirm");
const deleteError = document.getElementById("delete-error");

const EXPORT_URL = "/api/account/export";
const ACCOUNT_URL = "/api/account";
const REVOKE_DELAY_MS = 1000;

const WRONG_PASSWORD = "That password isn't right. Nothing was deleted.";
const NOT_CONFIRMED =
  "We couldn't confirm the deletion. Reload this page: if your account was deleted, you'll be taken to the login page.";

// "pureskin-data-2026-10-14.json", from the export's own timestamp.
function exportFilename(data) {
  const date = data && typeof data.exported_at === "string" ? data.exported_at.slice(0, 10) : "";
  return /^\d{4}-\d{2}-\d{2}$/.test(date) ? `pureskin-data-${date}.json` : "pureskin-data.json";
}

function saveFile(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const link = el("a", { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
}

downloadButton.addEventListener("click", async () => {
  downloadButton.disabled = true;
  downloadStatus.replaceChildren(statusMessage("Preparing your file…"));
  try {
    const data = await apiFetch(EXPORT_URL);
    const name = exportFilename(data);
    saveFile(name, JSON.stringify(data, null, 2));
    downloadStatus.replaceChildren(statusMessage(`Your download has started: ${name}`));
  } catch (error) {
    if (error.status !== 401) {
      downloadStatus.replaceChildren(statusMessage(`We couldn't prepare your file. ${error.message}`, { error: true }));
    }
  } finally {
    downloadButton.disabled = false;
  }
});

function forgetThisBrowsersData() {
  const scan = window.PureSkinScan;
  scan.remove(scan.RESULT_KEY);
  scan.discardPhotoAndAnswers();
  window.PureSkinAuth.logout(); // removes the login token and goes to /auth/ (replacing this page)
}

deleteForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = deletePassword.value;
  if (!password) {
    deleteError.textContent = "Enter your password.";
    deletePassword.focus();
    return;
  }
  if (!deleteConfirm.checked) {
    deleteError.textContent = "Tick the box to confirm.";
    deleteConfirm.focus();
    return;
  }
  deleteError.textContent = "";
  const button = deleteForm.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    await apiFetch(ACCOUNT_URL, { method: "DELETE", body: { password } });
    forgetThisBrowsersData();
  } catch (error) {
    if (error.status === 401) return; // apiFetch is already logging out
    // 422: the password can't be valid (too long); 403: it's wrong. Either way nothing changed.
    deleteError.textContent = error.status === 403 || error.status === 422 ? WRONG_PASSWORD : NOT_CONFIRMED;
  } finally {
    deletePassword.value = "";
    button.disabled = false;
  }
});
