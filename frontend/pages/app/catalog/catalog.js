// Product Catalog: debounced search, category filter, Previous/Next pagination.
// Filters are mirrored into the URL (?search=&category=&page=) so Back from a
// product page returns to the same results.

const { el, statusMessage, capitalize } = PureSkinUI;

const PAGE_SIZE = 12;
const SEARCH_DEBOUNCE_MS = 300;

const form = document.getElementById("catalog-filters");
const searchInput = document.getElementById("catalog-search");
const categorySelect = document.getElementById("catalog-category");
const grid = document.getElementById("catalog-grid");
const count = document.getElementById("catalog-count");
const prevButton = document.getElementById("page-prev");
const nextButton = document.getElementById("page-next");
const pageInfo = document.getElementById("page-info");

const params = new URLSearchParams(location.search);
const state = {
  search: params.get("search") || "",
  category: params.get("category") || "",
  page: Math.max(1, parseInt(params.get("page"), 10) || 1),
};
searchInput.value = state.search;

let latestRequest = 0; // responses from superseded requests are ignored

function syncUrl() {
  const query = new URLSearchParams();
  if (state.search) query.set("search", state.search);
  if (state.category) query.set("category", state.category);
  if (state.page > 1) query.set("page", String(state.page));
  const qs = query.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

function productCard(product) {
  return el("li", {},
    el("a", { className: "product-card", href: `/app/catalog/${product.id}/` },
      el("span", { className: "product-card__category", text: capitalize(product.category) }),
      el("span", { className: "product-card__name", text: product.name }),
      el("span", { className: "product-card__brand", text: product.brand }),
      el("span", { className: "product-card__description", text: product.description || "" })));
}

function renderPage(data) {
  const totalPages = Math.max(1, Math.ceil(data.total / data.page_size));
  count.textContent = data.total === 1 ? "1 product" : `${data.total} products`;
  grid.replaceChildren(...data.items.map(productCard));
  if (!data.items.length) {
    grid.replaceChildren(el("li", { className: "catalog-empty" },
      statusMessage("No products match your search. Try a different name, brand or category.")));
  }
  pageInfo.textContent = `Page ${data.page} of ${totalPages}`;
  prevButton.disabled = data.page <= 1;
  nextButton.disabled = data.page >= totalPages;
}

async function load() {
  const requestId = ++latestRequest;
  syncUrl();
  const query = new URLSearchParams({ page: String(state.page), page_size: String(PAGE_SIZE) });
  if (state.search) query.set("search", state.search);
  if (state.category) query.set("category", state.category);

  grid.setAttribute("aria-busy", "true");
  try {
    const data = await apiFetch(`/api/catalog?${query}`);
    if (requestId !== latestRequest) return;
    // Page past the end (e.g. stale URL) — jump to the last page instead of showing nothing.
    const lastPage = Math.max(1, Math.ceil(data.total / data.page_size));
    if (state.page > lastPage) {
      state.page = lastPage;
      load();
      return;
    }
    renderPage(data);
  } catch (error) {
    if (requestId !== latestRequest || error.status === 401) return;
    count.textContent = "";
    grid.replaceChildren(el("li", { className: "catalog-empty" }, statusMessage(error.message, { error: true })));
    prevButton.disabled = nextButton.disabled = true;
  } finally {
    if (requestId === latestRequest) grid.removeAttribute("aria-busy");
  }
}

async function loadCategories() {
  try {
    const categories = await apiFetch("/api/catalog/categories");
    categorySelect.append(...categories.map((c) => el("option", { value: c, text: capitalize(c) })));
  } catch {
    // Filter just stays at "All categories"; the grid itself reports errors.
  }
  categorySelect.value = state.category; // restore from URL once options exist
}

let debounceTimer;
searchInput.addEventListener("input", () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    const search = searchInput.value.trim();
    if (search === state.search) return;
    state.search = search;
    state.page = 1;
    load();
  }, SEARCH_DEBOUNCE_MS);
});

categorySelect.addEventListener("change", () => {
  state.category = categorySelect.value;
  state.page = 1;
  load();
});

prevButton.addEventListener("click", () => {
  state.page -= 1;
  load();
});

nextButton.addEventListener("click", () => {
  state.page += 1;
  load();
});

form.addEventListener("submit", (event) => event.preventDefault()); // Enter in search shouldn't reload

loadCategories();
load();
