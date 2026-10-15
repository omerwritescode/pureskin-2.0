// Persistent app nav, rendered into <nav id="app-nav"> on every /app page.
// Single source of truth for the Tier-1 links (docs/spec.md §5) — add pages here only.
// Requires auth-guard.js to have run first (for PureSkinAuth.logout).

(function () {
  const NAV_ITEMS = [
    { href: "/app/", label: "Dashboard" },
    { href: "/app/profile/", label: "Profile" },
    { href: "/app/routine/", label: "Routine" },
    { href: "/app/catalog/", label: "Catalog" },
    { href: "/app/chat/", label: "Chat" },
    { href: "/app/progress/", label: "Progress" },
    { href: "/app/settings/", label: "Settings" },
  ];

  const nav = document.getElementById("app-nav");
  if (!nav) return;

  // The current section is the longest nav href the path starts with, so future
  // detail pages (e.g. /app/catalog/42/) still highlight their parent.
  const path = location.pathname.endsWith("/") ? location.pathname : location.pathname + "/";
  const current = NAV_ITEMS.filter((item) => path.startsWith(item.href))
    .sort((a, b) => b.href.length - a.href.length)[0];

  const links = NAV_ITEMS.map((item) => {
    const active = item === current ? ' aria-current="page"' : "";
    return `<li><a class="app-nav__link" href="${item.href}"${active}>${item.label}</a></li>`;
  }).join("");

  // The wordmark's lowercase and chip strip are CSS (.wordmark); the text stays "PureSkin".
  // It links to the landing page (/), which offers "Go to your dashboard" when logged in.
  nav.innerHTML = `
    <div class="app-nav__inner">
      <a class="app-nav__brand wordmark" href="/">PureSkin</a>
      <ul class="app-nav__links">${links}</ul>
      <button type="button" class="app-nav__logout">Log out</button>
    </div>
  `;

  nav.querySelector(".app-nav__logout").addEventListener("click", () => {
    window.PureSkinAuth.logout();
  });

  const main = document.querySelector("main");

  // The footer: the way to About and Contact from every /app page (docs/spec.md §5).
  const footer = document.createElement("footer");
  footer.className = "site-footer";
  footer.innerHTML = `
    <div class="site-footer__inner">
      <p class="site-footer__note">PureSkin is a student project (MSc Data Science, NMIMS).</p>
      <ul class="site-footer__links">
        <li><a href="/about/">About</a></li>
        <li><a href="/contact/">Contact</a></li>
      </ul>
    </div>
  `;
  if (main) main.after(footer);
  else document.body.append(footer);

  // Keyboard users can jump past the nav's nine stops (WCAG 2.4.1).
  if (main) {
    if (!main.id) main.id = "main";
    const skip = document.createElement("a");
    skip.className = "skip-link";
    skip.href = `#${main.id}`;
    skip.textContent = "Skip to main content";
    document.body.prepend(skip);
  }
})();
