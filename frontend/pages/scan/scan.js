// Selfie Capture: live camera preview -> capture -> photo check -> /scan/questionnaire/.
// The camera and a file upload are equal ways in, both offered from the start: a phone
// that opens PureSkin over plain HTTP gets no camera, so upload is how it scans.
//
// Every photo (camera or upload) is checked right away with POST
// /api/services/image/analyze, so an unusable photo gets a retake screen here instead
// of failing after the questionnaire. Nothing is logged; the photo is never stored on
// the server.
//
// /scan/?retake=1 is the retake screen after a photo was rejected at the questionnaire's
// final submit: the answers it kept stay, and the new photo goes straight back there.

const NEXT_URL = "/scan/questionnaire/";
const CHECK_URL = "/api/services/image/analyze";
const MAX_SIDE = 720;       // px; the analyzer works at this resolution anyway
const JPEG_QUALITY = 0.92;  // 7b-ii: up from 0.85 (see the image analysis README)

const video = document.getElementById("camera-video");
const cameraWindow = document.getElementById("camera-window");
const idle = document.getElementById("camera-idle");
const canvas = document.getElementById("capture-canvas");
const errorBox = document.getElementById("scan-error");
const checking = document.getElementById("photo-checking");
const retakeScreen = document.getElementById("retake-screen");
const retakeHeading = document.getElementById("retake-heading");
const retakeIssues = document.getElementById("retake-issues");
const retakeTips = document.getElementById("retake-tips");
const retakeKept = document.getElementById("retake-kept");
const photoTip = document.getElementById("photo-tip");
const photoTipList = document.getElementById("photo-tip-list");
const uploadOption = document.getElementById("upload-option");
const uploadInput = document.getElementById("upload-input");
const uploadButton = uploadOption.querySelector(".upload__button");
const buttons = {
  start: document.getElementById("start-camera"),
  capture: document.getElementById("capture"),
  continue: document.getElementById("continue"),
  checkAgain: document.getElementById("check-again"),
  retake: document.getElementById("retake"),
};

let stream = null;
let capturedImage = null; // base64 data URL of the photo awaiting confirmation
let photoApproved = false; // set only by a successful photo check
let source = null; // "camera" or "upload": where the current photo came from
let photo = null; // the captured photo's <img>, made once there is a photo

// The controls to show; "upload" is the file upload, offered beside the camera. It is the
// camera's equal, except while the camera is live: then Capture is the action and the
// upload steps back to the outlined style.
function show(...visible) {
  for (const [name, button] of Object.entries(buttons)) button.hidden = !visible.includes(name);
  uploadOption.hidden = !visible.includes("upload");
  uploadButton.classList.toggle("btn--secondary", visible.includes("capture"));
}

function showError(message, { offerUpload = true } = {}) {
  errorBox.textContent = message;
  errorBox.hidden = false;
  if (offerUpload) uploadOption.hidden = false;
}

// An <img> without a src draws as a broken image, so it's only made for a real photo.
function photoElement() {
  if (!photo) {
    photo = document.createElement("img");
    photo.className = "camera__view";
    photo.alt = "Your captured photo";
    cameraWindow.append(photo);
  }
  return photo;
}

function hidePhoto() {
  if (photo) photo.hidden = true;
}

function fillList(list, items) {
  list.replaceChildren(...items.map((text) => {
    const item = document.createElement("li");
    item.textContent = text;
    return item;
  }));
}

// Back to a clean slate: no error, no retake screen, no tip.
function clearMessages() {
  errorBox.hidden = true;
  checking.hidden = true;
  retakeScreen.hidden = true;
  photoTip.hidden = true;
}

function stopCamera() {
  if (stream) stream.getTracks().forEach((track) => track.stop());
  stream = null;
}

function cameraErrorMessage(error) {
  switch (error && error.name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Camera access was blocked. Allow camera access in your browser settings and try again, or upload a photo instead.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "We couldn't find a camera on this device. You can upload a photo instead.";
    case "NotReadableError":
      return "Your camera is being used by another app. Close it and try again, or upload a photo instead.";
    default:
      return "We couldn't start your camera. You can upload a photo instead.";
  }
}

async function startCamera() {
  clearMessages();
  capturedImage = null;
  photoApproved = false;
  hidePhoto();

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    // Also happens on plain-http pages other than localhost (camera needs a secure context).
    show("upload");
    showError("This browser can't open the camera here. You can upload a photo instead.");
    return;
  }

  buttons.start.disabled = true;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 960 } },
      audio: false,
    });
  } catch (error) {
    buttons.start.disabled = false;
    show("start", "upload");
    showError(cameraErrorMessage(error));
    return;
  }
  buttons.start.disabled = false;

  video.srcObject = stream;
  video.hidden = false;
  idle.hidden = true;
  show("capture", "upload"); // a file can still be chosen instead
}

// Draw a video frame or image onto the canvas, scaled down to MAX_SIDE, and return a JPEG data URL.
function toDataUrl(source, width, height) {
  const scale = Math.min(1, MAX_SIDE / Math.max(width, height));
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", JPEG_QUALITY);
}

function showCaptured(dataUrl) {
  capturedImage = dataUrl;
  photoApproved = false;
  const img = photoElement();
  img.src = dataUrl;
  img.hidden = false;
  video.hidden = true;
  idle.hidden = true;
  checkPhoto();
}

// Ask the Image Analysis service whether this photo is usable, before the questionnaire.
async function checkPhoto() {
  const image = capturedImage;
  clearMessages();
  show();
  checking.hidden = false;
  const result = await window.PureSkinScanApi.post(CHECK_URL, { image });
  if (image !== capturedImage) return; // a newer photo replaced this one meanwhile
  checking.hidden = true;

  if (result.kind === "ok") {
    photoApproved = true;
    const tips = (result.data.quality && result.data.quality.issues) || [];
    if (tips.length) {
      fillList(photoTipList, tips.map(String));
      photoTip.hidden = false;
    }
    show("continue", "retake");
    buttons.continue.focus();
  } else if (result.kind === "retake") {
    fillList(retakeIssues, result.issues);
    retakeScreen.hidden = false;
    show("retake");
    retakeHeading.focus();
  } else {
    showError(result.message, { offerUpload: false });
    show("checkAgain", "retake");
  }
}

function capture() {
  if (!video.videoWidth) return; // camera not ready yet
  const dataUrl = toDataUrl(video, video.videoWidth, video.videoHeight);
  stopCamera();
  source = "camera";
  showCaptured(dataUrl);
}

function useUploadedFile(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    showError("That file isn't an image. Please choose a photo.");
    return;
  }
  const url = URL.createObjectURL(file);
  const img = new Image();
  img.onload = () => {
    clearMessages();
    stopCamera();
    source = "upload";
    showCaptured(toDataUrl(img, img.naturalWidth, img.naturalHeight));
    URL.revokeObjectURL(url);
  };
  img.onerror = () => {
    showError("We couldn't read that image. Please try a different photo.");
    URL.revokeObjectURL(url);
  };
  img.src = url;
}

function continueToQuestionnaire() {
  if (!photoApproved) return; // only a photo that passed the check goes forward
  const { IMAGE_KEY, RESULT_KEY, write, remove } = window.PureSkinScan;
  try {
    write(IMAGE_KEY, capturedImage);
  } catch {
    showError("We couldn't save your photo in this browser. Try again, or use a different browser.", { offerUpload: false });
    return;
  }
  remove(RESULT_KEY); // a new photo invalidates any earlier result
  location.href = NEXT_URL;
}

function retake() {
  clearMessages();
  capturedImage = null;
  photoApproved = false;
  if (source === "camera") {
    startCamera();
  } else {
    // An uploaded photo: back to the start, with both ways in.
    hidePhoto();
    idle.hidden = false;
    uploadInput.value = "";
    show("start", "upload");
  }
}

// A new scan discards any earlier photo, result and kept answers. A retake after the
// final submit keeps the answers (the questionnaire restores them) and shows why the
// photo was rejected. Returns those issues, or null for a new scan.
function startScan() {
  const { IMAGE_KEY, RESULT_KEY, ANSWERS_KEY, RETAKE_KEY, read, remove, discardPhotoAndAnswers } =
    window.PureSkinScan;
  remove(RESULT_KEY);
  const isRetake = new URLSearchParams(location.search).get("retake") === "1" && Boolean(read(ANSWERS_KEY));
  if (!isRetake) {
    discardPhotoAndAnswers();
    return null;
  }
  remove(IMAGE_KEY);
  let issues = [];
  try {
    issues = JSON.parse(read(RETAKE_KEY)) || [];
  } catch {
    issues = [];
  }
  remove(RETAKE_KEY);
  return Array.isArray(issues) ? issues.map(String) : [];
}

fillList(retakeTips, window.PureSkinScanApi.LIGHTING_TIPS);
const retakeIssuesFromSubmit = startScan();
if (retakeIssuesFromSubmit) {
  fillList(retakeIssues, retakeIssuesFromSubmit);
  retakeScreen.hidden = false;
  retakeKept.hidden = false;
  show("start", "upload"); // camera or upload, whichever they like
  retakeHeading.focus();
}
buttons.start.addEventListener("click", startCamera);
buttons.capture.addEventListener("click", capture);
buttons.retake.addEventListener("click", retake);
buttons.checkAgain.addEventListener("click", checkPhoto);
buttons.continue.addEventListener("click", continueToQuestionnaire);
uploadInput.addEventListener("change", () => useUploadedFile(uploadInput.files[0]));

// Release the camera when leaving the page.
window.addEventListener("pagehide", stopCamera);
