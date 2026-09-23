// Selfie Capture: live camera preview -> capture -> confirm -> /scan/questionnaire/.
// Falls back to a file upload if the camera is unavailable or permission is denied.

const NEXT_URL = "/scan/questionnaire/";
const MAX_SIDE = 720;       // px; keeps the base64 image small enough for sessionStorage
const JPEG_QUALITY = 0.85;

const video = document.getElementById("camera-video");
const photo = document.getElementById("camera-photo");
const idle = document.getElementById("camera-idle");
const canvas = document.getElementById("capture-canvas");
const errorBox = document.getElementById("scan-error");
const fallback = document.getElementById("upload-fallback");
const uploadInput = document.getElementById("upload-input");
const buttons = {
  start: document.getElementById("start-camera"),
  capture: document.getElementById("capture"),
  continue: document.getElementById("continue"),
  retake: document.getElementById("retake"),
};

let stream = null;
let capturedImage = null; // base64 data URL of the photo awaiting confirmation

function show(...visible) {
  for (const [name, button] of Object.entries(buttons)) button.hidden = !visible.includes(name);
}

function showError(message, { offerUpload = true } = {}) {
  errorBox.textContent = message;
  errorBox.hidden = false;
  if (offerUpload) fallback.hidden = false;
}

function clearError() {
  errorBox.hidden = true;
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
  clearError();
  capturedImage = null;
  photo.hidden = true;

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    // Also happens on plain-http pages other than localhost (camera needs a secure context).
    show();
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
    show("start");
    showError(cameraErrorMessage(error));
    return;
  }
  buttons.start.disabled = false;

  video.srcObject = stream;
  video.hidden = false;
  idle.hidden = true;
  show("capture");
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
  photo.src = dataUrl;
  photo.hidden = false;
  video.hidden = true;
  idle.hidden = true;
  show("continue", "retake");
}

function capture() {
  if (!video.videoWidth) return; // camera not ready yet
  const dataUrl = toDataUrl(video, video.videoWidth, video.videoHeight);
  stopCamera();
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
    clearError();
    stopCamera();
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

buttons.start.addEventListener("click", startCamera);
buttons.capture.addEventListener("click", capture);
buttons.retake.addEventListener("click", () => {
  if (fallback.hidden) {
    startCamera();
  } else {
    // Came from the upload path — let them pick another file.
    capturedImage = null;
    photo.hidden = true;
    idle.hidden = false;
    uploadInput.value = "";
    show("start");
  }
});
buttons.continue.addEventListener("click", continueToQuestionnaire);
uploadInput.addEventListener("change", () => useUploadedFile(uploadInput.files[0]));

// Release the camera when leaving the page.
window.addEventListener("pagehide", stopCamera);
