const els = {
  refreshBtn: document.querySelector("#refreshBtn"),
  minPrice: document.querySelector("#minPrice"),
  maxPrice: document.querySelector("#maxPrice"),
  maxMileage: document.querySelector("#maxMileage"),
  manualForm: document.querySelector("#manualForm"),
  manualMake: document.querySelector("#manualMake"),
  manualModel: document.querySelector("#manualModel"),
  manualTitle: document.querySelector("#manualTitle"),
  manualUrl: document.querySelector("#manualUrl"),
  manualPrice: document.querySelector("#manualPrice"),
  manualMileage: document.querySelector("#manualMileage"),
  manualYear: document.querySelector("#manualYear"),
  manualBattery: document.querySelector("#manualBattery"),
  manualTrim: document.querySelector("#manualTrim"),
  count: document.querySelector("#count"),
  bestPrice: document.querySelector("#bestPrice"),
  bestScore: document.querySelector("#bestScore"),
  marketCoverage: document.querySelector("#marketCoverage"),
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

function buildUrl() {
  const params = new URLSearchParams({
    min_price: els.minPrice.value || "5000",
    max_price: els.maxPrice.value || "12000",
    sources: "manual,autoscout24",
    refresh: "false",
  });
  if (els.maxMileage.value) {
    params.set("max_mileage", els.maxMileage.value);
  }
  return `/api/search?${params.toString()}`;
}

async function load() {
  els.refreshBtn.disabled = true;
  els.refreshBtn.textContent = "Loading...";
  try {
    const response = await fetch(buildUrl());
    const data = await response.json();
    render(data);
  } catch (error) {
    els.statuses.innerHTML = `<div class="status bad">Request failed: ${error.message}</div>`;
  } finally {
    els.refreshBtn.disabled = false;
    els.refreshBtn.textContent = "Refresh market prices";
  }
}

async function refreshMarket() {
  els.refreshBtn.disabled = true;
  els.refreshBtn.textContent = "Checking AutoScout24...";
  try {
    const response = await fetch("/api/market-refresh", { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Market refresh failed");
    }
    await load();
  } catch (error) {
    els.statuses.innerHTML = `<div class="status bad">Market refresh failed: ${escapeHtml(error.message)}</div>`;
  } finally {
    els.refreshBtn.disabled = false;
    els.refreshBtn.textContent = "Refresh market prices";
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
  els.marketCoverage.textContent = listings.length
    ? `${listings.filter((item) => item.market_status === "ok").length}/${listings.length}`
    : "-";
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
    els.listings.innerHTML = `<div class="empty">No ranked listings yet. Add a manual car, then refresh market prices.</div>`;
    return;
  }

  els.listings.innerHTML = listings.map((item) => listingTemplate(item)).join("");
}

function listingTemplate(item) {
  const reasons = item.reasons.slice(0, 3).map(escapeHtml).join(" ");
  const market = marketTemplate(item);
  const details = [
    item.make && item.model ? `${escapeHtml(item.make)} ${escapeHtml(item.model)}` : labelSource(item.source),
    item.year || null,
    item.battery_kwh ? `${item.battery_kwh} kWh` : null,
    item.trim ? escapeHtml(item.trim) : null,
  ].filter(Boolean).join(" · ");
  return `
    <article class="listing">
      <div class="rank">${item.rank}</div>
      <div>
        <a class="title" href="${item.url}" target="_blank" rel="noreferrer">${escapeHtml(item.title)}</a>
        <div class="meta">
          ${details}
        </div>
        <div class="meta">${eur.format(item.price_eur)} · ${km.format(item.mileage_km)} km</div>
        <div class="reasons">${reasons}</div>
      </div>
      <div>
        <div class="score">${item.score}</div>
        <div class="meta">deal score</div>
      </div>
      ${market}
      <div class="money">
        <span>Opening offer <strong>${eur.format(item.negotiation_open_eur)}</strong></span>
        <span>Walk-away ceiling <strong>${eur.format(item.negotiation_ceiling_eur)}</strong></span>
      </div>
    </article>
  `;
}

function marketTemplate(item) {
  if (item.market_status !== "ok") {
    return `
      <div class="market muted-market">
        <span>Market</span>
        <strong>${escapeHtml(marketStatusLabel(item.market_status))}</strong>
        ${item.market_source_url ? `<a href="${item.market_source_url}" target="_blank" rel="noreferrer">AutoScout24 search</a>` : ""}
      </div>
    `;
  }
  const delta = item.market_delta_eur || 0;
  const deltaClass = delta <= 0 ? "good" : "bad";
  const deltaLabel = delta <= 0 ? "under market" : "over market";
  return `
    <div class="market">
      <span>Median <strong>${eur.format(item.market_median_price_eur)}</strong></span>
      <span>Average <strong>${eur.format(item.market_average_price_eur)}</strong></span>
      <span class="${deltaClass}">${eur.format(Math.abs(delta))} ${deltaLabel}</span>
      <a href="${item.market_source_url}" target="_blank" rel="noreferrer">${item.market_sample_size} samples</a>
    </div>
  `;
}

function labelSource(source) {
  return {
    njuskalo: "Njuškalo",
    index_oglasi: "Index Oglasi",
    manual: "Manual",
    autoscout24: "AutoScout24",
  }[source] || source;
}

function marketStatusLabel(status) {
  return {
    not_checked: "Not checked",
    needs_refresh: "Needs refresh",
    missing_make_model_year: "Missing make/model/year",
    no_market_listings: "No listings found",
    request_failed: "Request failed",
  }[status] || status.replaceAll("_", " ");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

els.refreshBtn.addEventListener("click", () => refreshMarket());
els.manualForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    make: els.manualMake.value,
    model: els.manualModel.value,
    year: Number(els.manualYear.value),
    title: els.manualTitle.value || null,
    url: els.manualUrl.value,
    price_eur: Number(els.manualPrice.value),
    mileage_km: Number(els.manualMileage.value),
    battery_kwh: els.manualBattery.value ? Number(els.manualBattery.value) : null,
    trim: els.manualTrim.value || null,
  };
  const response = await fetch("/api/manual-listings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (response.ok) {
    els.manualForm.reset();
    await load();
  } else {
    const data = await response.json();
    els.statuses.innerHTML = `<div class="status bad">Manual listing failed: ${escapeHtml(data.detail || "Invalid input")}</div>`;
  }
});
for (const input of [els.minPrice, els.maxPrice, els.maxMileage]) {
  input.addEventListener("change", () => load());
}

load();
