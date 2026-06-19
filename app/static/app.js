const els = {
  refreshBtn: document.querySelector("#refreshBtn"),
  minPrice: document.querySelector("#minPrice"),
  maxPrice: document.querySelector("#maxPrice"),
  maxMileage: document.querySelector("#maxMileage"),
  srcNjuskalo: document.querySelector("#srcNjuskalo"),
  srcIndex: document.querySelector("#srcIndex"),
  manualForm: document.querySelector("#manualForm"),
  manualTitle: document.querySelector("#manualTitle"),
  manualUrl: document.querySelector("#manualUrl"),
  manualPrice: document.querySelector("#manualPrice"),
  manualMileage: document.querySelector("#manualMileage"),
  manualYear: document.querySelector("#manualYear"),
  count: document.querySelector("#count"),
  bestPrice: document.querySelector("#bestPrice"),
  bestScore: document.querySelector("#bestScore"),
  statuses: document.querySelector("#statuses"),
  listings: document.querySelector("#listings"),
};

const eur = new Intl.NumberFormat("hr-HR", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
});

const km = new Intl.NumberFormat("hr-HR", {
  maximumFractionDigits: 0,
});

function selectedSources() {
  const sources = [];
  if (els.srcNjuskalo.checked) sources.push("njuskalo");
  if (els.srcIndex.checked) sources.push("index_oglasi");
  return sources.join(",");
}

function buildUrl(refresh = false) {
  const params = new URLSearchParams({
    min_price: els.minPrice.value || "5000",
    max_price: els.maxPrice.value || "12000",
    sources: selectedSources(),
    refresh: String(refresh),
  });
  if (els.maxMileage.value) {
    params.set("max_mileage", els.maxMileage.value);
  }
  return `/api/search?${params.toString()}`;
}

async function load(refresh = false) {
  els.refreshBtn.disabled = true;
  els.refreshBtn.textContent = refresh ? "Scraping..." : "Loading...";
  try {
    const response = await fetch(buildUrl(refresh));
    const data = await response.json();
    render(data);
  } catch (error) {
    els.statuses.innerHTML = `<div class="status bad">Request failed: ${error.message}</div>`;
  } finally {
    els.refreshBtn.disabled = false;
    els.refreshBtn.textContent = "Refresh scrape";
  }
}

function render(data) {
  renderSummary(data.listings);
  renderStatuses(data.statuses);
  renderListings(data.listings);
}

function renderSummary(listings) {
  els.count.textContent = listings.length;
  els.bestPrice.textContent = listings.length
    ? eur.format(Math.min(...listings.map((item) => item.price_eur)))
    : "-";
  els.bestScore.textContent = listings.length ? `${listings[0].score}` : "-";
}

function renderStatuses(statuses) {
  els.statuses.innerHTML = statuses
    .map((status) => {
      const klass = status.ok ? "status" : "status bad";
      return `<div class="${klass}"><strong>${labelSource(status.source)}</strong>: ${escapeHtml(status.message)} (${status.fetched} fetched)</div>`;
    })
    .join("");
}

function renderListings(listings) {
  if (!listings.length) {
    els.listings.innerHTML = `<div class="empty">No ranked listings yet. Try Refresh scrape; if sources are blocked, the status panel will say why.</div>`;
    return;
  }

  els.listings.innerHTML = listings.map((item) => listingTemplate(item)).join("");
}

function listingTemplate(item) {
  const reasons = item.reasons.slice(0, 2).map(escapeHtml).join(" ");
  return `
    <article class="listing">
      <div class="rank">${item.rank}</div>
      <div>
        <a class="title" href="${item.url}" target="_blank" rel="noreferrer">${escapeHtml(item.title)}</a>
        <div class="meta">
          ${labelSource(item.source)} · ${eur.format(item.price_eur)} · ${km.format(item.mileage_km)} km${item.year ? ` · ${item.year}` : ""}
        </div>
        <div class="reasons">${reasons}</div>
      </div>
      <div>
        <div class="score">${item.score}</div>
        <div class="meta">deal score</div>
      </div>
      <div class="money">
        <span>Opening offer <strong>${eur.format(item.negotiation_open_eur)}</strong></span>
        <span>Walk-away ceiling <strong>${eur.format(item.negotiation_ceiling_eur)}</strong></span>
      </div>
    </article>
  `;
}

function labelSource(source) {
  return {
    njuskalo: "Njuškalo",
    index_oglasi: "Index Oglasi",
    manual: "Cache",
  }[source] || source;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

els.refreshBtn.addEventListener("click", () => load(true));
els.manualForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    title: els.manualTitle.value,
    url: els.manualUrl.value,
    price_eur: Number(els.manualPrice.value),
    mileage_km: Number(els.manualMileage.value),
    year: els.manualYear.value ? Number(els.manualYear.value) : null,
  };
  const response = await fetch("/api/manual-listings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (response.ok) {
    els.manualForm.reset();
    await load(false);
  } else {
    const data = await response.json();
    els.statuses.innerHTML = `<div class="status bad">Manual listing failed: ${escapeHtml(data.detail || "Invalid input")}</div>`;
  }
});
for (const input of [els.minPrice, els.maxPrice, els.maxMileage, els.srcNjuskalo, els.srcIndex]) {
  input.addEventListener("change", () => load(false));
}

load(false);
