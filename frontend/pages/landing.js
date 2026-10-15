// Landing page (/): its two videos, the hero film and the "How a scan works" swatch, each
// in a [data-video-box] with its own button. The page has no autoplay attribute: this
// script plays a video only when reduced motion isn't set and the browser isn't saving
// data. Under reduced motion a video stays paused on its first frame and never starts.
// While data saving holds a video back, its button offers to play it; otherwise the
// button shows once the video is actually playing (until a file is in /static/media/,
// nothing plays and the chip colour stays). Each button's label says what it will do; its
// icon matches. The fan deck opens by CSS alone (landing.css), so the page works without
// this script.

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const saveData = Boolean(navigator.connection && navigator.connection.saveData);

for (const box of document.querySelectorAll("[data-video-box]")) {
  const video = box.querySelector("video");
  const toggle = box.querySelector(".video-toggle");
  const toggleLabel = toggle.querySelector(".video-toggle__label");
  const pauseIcon = toggle.querySelector(".icon--pause");
  const playIcon = toggle.querySelector(".icon--play");

  function showState() {
    const playing = !video.paused;
    toggleLabel.textContent = playing ? "Pause video" : "Play video";
    pauseIcon.toggleAttribute("hidden", !playing);
    playIcon.toggleAttribute("hidden", playing);
  }

  function play() {
    // Rejected when there's no playable file yet, or the browser blocks it: it stays paused.
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

  // Turning reduced motion on while a video plays stops it.
  reducedMotion.addEventListener("change", () => {
    if (reducedMotion.matches) video.pause();
  });

  if (!reducedMotion.matches && !saveData) play();
  else if (!reducedMotion.matches) {
    // Saving data: nothing downloads unasked; once the first frame is in, offer to play.
    video.addEventListener("loadeddata", () => {
      toggle.hidden = false;
      showState();
    }, { once: true });
  }
}
