// Landing page (/): the "How a scan works" video. The page has no autoplay attribute: this
// script plays the video only when reduced motion isn't set, and shows its button once it
// is actually playing (until the files are in /static/media/, nothing plays and the chip
// colour stays). The button's label says what it will do; its icon matches. The fan deck
// opens by CSS alone (landing.css), so the page works without this script.

const video = document.querySelector(".how__video");
const toggle = document.querySelector(".how__toggle");
const toggleLabel = toggle.querySelector(".how__toggle-label");
const pauseIcon = toggle.querySelector(".icon--pause");
const playIcon = toggle.querySelector(".icon--play");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

function showState() {
  const playing = !video.paused;
  toggleLabel.textContent = playing ? "Pause video" : "Play video";
  pauseIcon.toggleAttribute("hidden", !playing);
  playIcon.toggleAttribute("hidden", playing);
}

function play() {
  // Rejected when there's no playable file yet, or the browser blocks it: the poster stays.
  video.play().catch(() => {});
}

video.addEventListener("playing", () => {
  toggle.hidden = false;
  showState();
});
video.addEventListener("pause", showState);

toggle.addEventListener("click", () => {
  if (video.paused) play();
  else video.pause();
});

// Turning reduced motion on while the video plays stops it.
reducedMotion.addEventListener("change", () => {
  if (reducedMotion.matches) video.pause();
});

if (!reducedMotion.matches) play();
