const MARKETS_DISPLAY_LIMIT = 200;

const state = {
  quote: "USDT",
  mode: "live",
  portfolio: null,
  markets: [],
  groups: [],
  selectedCoins: new Set(),
  activeBuyGroupId: null,
  activeSellGroupId: null,
  activeAllocGroupId: null,
  sellSelected: new Set(),
  sellAmounts: {},
  transactions: [],
  historyFilter: "all",
  displayInINR: false,
  inrRate: null,
  inrSource: null,
  coinAnalysis: null,
  activeCoin: null,
  activeEditCoinsGroupId: null,
  editCoinsSelected: new Set(),
  editCoinsFilter: "",
  groupAnalysis: null,
  activeGroupAnalysisId: null,
  marketFilter: "",
  activeTab: "portfolio",
};

const COIN_COLORS = [
  "#4d9fff", "#6366f1", "#2dd4a0", "#f59e0b", "#f87171",
  "#a78bfa", "#38bdf8", "#fb923c", "#34d399", "#e879f9",
];

const PAGE_META = {
  portfolio: { title: "Portfolio", sub: "Your spot wallet & allocation" },
  markets: { title: "All Coins", sub: "Browse Gate.io markets & build groups" },
  groups: { title: "Groups", sub: "Set % per coin, buy split, or sell" },
  history: { title: "History", sub: "Spot trades — bot vs Gate website" },
};

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

async function api(path, opts = {}) {
  const { signal: optSignal, ...restOpts } = opts;
  const controller = optSignal ? null : new AbortController();
  const signal = optSignal || controller.signal;
  const timeout = controller ? setTimeout(() => controller.abort(), 120000) : null;
  try {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...restOpts,
      signal,
    });
    const text = await res.text();
    let data = {};
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        throw new Error("Invalid response from server");
      }
    }
    if (!res.ok) {
      const msg = data.detail || res.statusText || "Request failed";
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return data;
  } catch (e) {
    if (e.name === "AbortError") {
      if (optSignal) throw e;
      throw new Error("Request timed out — Gate.io may be slow. Try Refresh.");
    }
    throw e;
  } finally {
    if (timeout) clearTimeout(timeout);
  }
}

function showError(msg) {
  const el = $("#error-banner");
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("hidden");
}

function clearError() {
  $("#error-banner")?.classList.add("hidden");
}

function safe(v, fallback = "—") {
  if (v == null || v === "null" || v === "undefined" || v === "") return fallback;
  return v;
}

function toast(msg, type = "info") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = `toast ${type === "ok" ? "ok" : type === "err" ? "err" : ""}`;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 4200);
}

function fmtNum(n, decimals = 2) {
  if (n == null || n === "" || isNaN(parseFloat(n))) return "—";
  const v = parseFloat(n);
  if (v >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (v >= 1e3) return v.toLocaleString(undefined, { maximumFractionDigits: decimals });
  if (v < 0.0001 && v > 0) return v.toPrecision(4);
  return v.toLocaleString(undefined, { maximumFractionDigits: decimals });
}

function formatMoney(amount, quote = state.quote, useINR = state.displayInINR) {
  const v = parseFloat(amount);
  if (isNaN(v)) return "—";
  if (useINR && state.inrRate) {
    return `₹${fmtNum(v * state.inrRate, 2)}`;
  }
  return `${fmtNum(v, 2)} ${quote}`;
}

function fmtPnl(change, changePct, label) {
  if (change == null || changePct == null) {
    return `<span class="pnl na muted">${label}: no data yet</span>`;
  }
  const ch = parseFloat(change);
  const pct = parseFloat(changePct);
  const cls = ch >= 0 ? "pos" : "neg";
  const sign = ch >= 0 ? "+" : "";
  return `<span class="pnl ${cls}">${label}: ${sign}${formatMoney(ch)} (${sign}${pct.toFixed(2)}%)</span>`;
}

function renderPortfolioChart(analytics) {
  const wrap = $("#portfolio-chart-wrap");
  const svg = $("#portfolio-chart");
  if (!wrap || !svg) return;
  const inner = buildPortfolioChartSvg(analytics, 280, 72);
  if (!inner) {
    wrap.classList.add("hidden");
    return;
  }
  svg.innerHTML = inner;
  wrap.classList.remove("hidden");
}

function buildChartSvgFromPoints(
  points,
  width = 280,
  height = 72,
  color = null
) {
  if (!points || points.length < 2) return "";
  const vals = points.map((p) => parseFloat(p.value));
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const pad = (max - min) * 0.08 || max * 0.02 || 1;
  const lo = min - pad;
  const hi = max + pad;
  const coords = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * width;
    const y = height - ((v - lo) / (hi - lo)) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const line = coords.join(" ");
  const area = `0,${height} ${line} ${width},${height}`;
  const last = vals[vals.length - 1];
  const first = vals[0];
  const up = last >= first;
  const stroke = color || (up ? "#2dd4a0" : "#f87171");
  const fill = color
    ? `${color}22`
    : up
      ? "rgba(45,212,160,0.15)"
      : "rgba(248,113,113,0.15)";
  return `
    <polyline points="${line}" fill="none" stroke="${stroke}" stroke-width="2" vector-effect="non-scaling-stroke"/>
    <polygon points="${area}" fill="${fill}"/>`;
}

function buildPortfolioChartSvg(analytics, width = 280, height = 72) {
  const points = analytics?.chart || [];
  if (points.length < 2) return "";
  return buildChartSvgFromPoints(points, width, height);
}

function renderTopAssetsSection(topAssets, quote) {
  if (!topAssets?.length) {
    return `<p class="muted analysis-note">No chart data for top assets yet.</p>`;
  }
  return `
    <div class="top-assets-grid">
      ${topAssets
        .map((asset) => {
          const color = coinColor(asset.coin);
          const svg = buildChartSvgFromPoints(asset.chart, 168, 52, color);
          return `
        <div class="top-asset-card">
          <div class="top-asset-head">
            ${coinAvatar(asset.coin, "sm")}
            <div>
              <strong>${asset.coin}</strong>
              <span class="muted top-asset-share">${asset.allocation_pct || "—"}%</span>
            </div>
            ${fmtPct(asset.change_pct)}
          </div>
          <div class="top-asset-value">${formatMoney(asset.value_quote, quote)}</div>
          <div class="top-asset-range muted">
            24h: ${formatMoney(asset.low_value, quote)} – ${formatMoney(asset.high_value, quote)}
          </div>
          <svg class="top-asset-chart" viewBox="0 0 168 52" preserveAspectRatio="none">
            ${svg}
          </svg>
        </div>`;
        })
        .join("")}
    </div>`;
}

function renderCoinAnalysisModal(a) {
  const body = $("#coin-analysis-body");
  const title = $("#coin-analysis-title");
  if (!body || !a) return;
  const q = a.quote || state.quote;
  const coin = a.coin || "—";
  if (title) {
    title.innerHTML = `${coinAvatar(coin, "sm")} <span>${coin} analysis</span>`;
  }
  const day = a.day || {};
  const chartNote =
    a.chart_source === "live"
      ? "hourly candles (24h)"
      : a.chart_source === "stable"
        ? "stable asset"
        : "estimated from 24h change";

  const priceChart = buildChartSvgFromPoints(a.price_chart, 560, 100, coinColor(coin));
  const valueChart = buildChartSvgFromPoints(a.value_chart, 560, 100, coinColor(coin));

  body.innerHTML = `
    <div class="coin-analysis-hero">
      <div class="coin-analysis-hero-main">
        <div class="analysis-current-label">Your holding value</div>
        <div class="analysis-current-value">${formatMoney(a.value_quote, q)}</div>
        <div class="coin-analysis-meta">
          ${fmtPct(a.change_pct)}
          <span class="muted">· ${safe(a.allocation_pct, "—")}% of portfolio</span>
        </div>
      </div>
      <div class="coin-analysis-pair muted">${safe(a.pair || `${coin}_${q}`)}</div>
    </div>
    <div class="analysis-grid">
      <div class="analysis-card">
        <div class="analysis-card-label">Balance</div>
        <div class="analysis-card-value">${safe(a.total)}</div>
        <div class="analysis-card-sub muted">Avail ${safe(a.available)} · Locked ${safe(a.locked)}</div>
      </div>
      <div class="analysis-card">
        <div class="analysis-card-label">Price</div>
        <div class="analysis-card-value">${a.price ? fmtNum(a.price, 4) + " " + q : "—"}</div>
        ${a.quote_volume ? `<div class="analysis-card-sub muted">24h vol ${fmtNum(a.quote_volume, 0)} ${q}</div>` : ""}
      </div>
      <div class="analysis-card">
        <div class="analysis-card-label">Day high</div>
        <div class="analysis-card-value pos">${day.high_price ? fmtNum(day.high_price, 4) + " " + q : "—"}</div>
        <div class="analysis-card-sub muted">${day.high_value ? formatMoney(day.high_value, q) : "—"} holding</div>
      </div>
      <div class="analysis-card">
        <div class="analysis-card-label">Day low</div>
        <div class="analysis-card-value neg">${day.low_price ? fmtNum(day.low_price, 4) + " " + q : "—"}</div>
        <div class="analysis-card-sub muted">${day.low_value ? formatMoney(day.low_value, q) : "—"} holding</div>
      </div>
    </div>
  ${
    a.highest_bid || a.lowest_ask
      ? `<div class="coin-analysis-book muted">
          Bid ${a.highest_bid ? fmtNum(a.highest_bid, 4) : "—"} ${q}
          · Ask ${a.lowest_ask ? fmtNum(a.lowest_ask, 4) : "—"} ${q}
        </div>`
      : ""
  }
    <div class="analysis-pnl-block">
      <h4>Profit / loss</h4>
      <div class="analysis-pnl-rows">
        ${fmtPnl(a.vs_24h?.change, a.vs_24h?.change_pct, "vs 24h ago")}
      </div>
      <p class="muted analysis-note">24h range uses Gate.io ticker and hourly candles when available (${chartNote}).</p>
    </div>
    <div class="analysis-chart-block">
      <h4>Price <span class="muted">(24h · ${chartNote})</span></h4>
      <div class="analysis-chart-large">
        <svg class="portfolio-chart portfolio-chart-lg" viewBox="0 0 560 100" preserveAspectRatio="none">
          ${priceChart || ""}
        </svg>
        ${!priceChart ? "<p class='muted analysis-note'>No price chart data.</p>" : ""}
      </div>
    </div>
    <div class="analysis-chart-block">
      <h4>Your holding value <span class="muted">(24h)</span></h4>
      <div class="analysis-chart-large">
        <svg class="portfolio-chart portfolio-chart-lg" viewBox="0 0 560 100" preserveAspectRatio="none">
          ${valueChart || ""}
        </svg>
        ${!valueChart ? "<p class='muted analysis-note'>No holding value chart.</p>" : ""}
      </div>
    </div>`;
}

async function openCoinAnalysisModal(coin) {
  if (!coin) return;
  hideAssetTip();
  state.activeCoin = coin;
  state.coinAnalysis = null;
  const body = $("#coin-analysis-body");
  if (body) body.innerHTML = "<p class='muted split-preview-loading'>Loading analysis…</p>";
  openModal("coin-analysis-modal");
  try {
    const data = await api(
      `/api/portfolio/asset/${encodeURIComponent(coin)}?quote=${encodeURIComponent(state.quote)}`
    );
    state.coinAnalysis = data;
    if (data.inr_rate && !state.inrRate) {
      state.inrRate = parseFloat(data.inr_rate);
      state.inrSource = data.inr_source || null;
    }
    renderCoinAnalysisModal(data);
  } catch (e) {
    if (body) body.innerHTML = `<p class="neg">${safe(e.message)}</p>`;
    toast(e.message, "err");
  }
}

function renderGroupAnalysisModal(a) {
  const body = $("#group-analysis-body");
  const title = $("#group-analysis-title");
  if (!body || !a) return;
  const q = a.quote || state.quote;
  if (title) title.textContent = `${safe(a.group_name, "Group")} — analysis`;
  const day = a.day || {};
  const chartSvg =
    a.chart?.length >= 2 ? buildChartSvgFromPoints(a.chart, 560, 120) : "";

  const breakdownRows = (a.coins_breakdown || [])
    .map(
      (row) => `
    <tr class="group-coin-row asset-hover-row" data-coin-click="${safe(row.coin)}">
      <td><div class="coin-cell">${coinAvatar(row.coin, "sm")}<strong>${safe(row.coin)}</strong></div></td>
      <td>${row.has_balance ? safe(row.total) : "<span class='muted'>—</span>"}</td>
      <td>${fmtPct(row.change_pct)}</td>
      <td>${row.value_quote ? formatMoney(row.value_quote, q) : "—"}</td>
      <td>${safe(row.allocation_pct, 0)}%</td>
    </tr>`
    )
    .join("");

  body.innerHTML = `
    <div class="analysis-current">
      <div class="analysis-current-label">Group holdings value</div>
      <div class="analysis-current-value">${formatMoney(a.current_value, q)}</div>
      <div class="coin-analysis-meta muted">${a.coins_count} coins in watchlist · ${a.holdings_count} with balance</div>
    </div>
    <div class="analysis-grid">
      <div class="analysis-card">
        <div class="analysis-card-label">24h high</div>
        <div class="analysis-card-value pos">${formatMoney(day.high_value, q)}</div>
      </div>
      <div class="analysis-card">
        <div class="analysis-card-label">24h low</div>
        <div class="analysis-card-value neg">${formatMoney(day.low_value, q)}</div>
      </div>
      <div class="analysis-card">
        <div class="analysis-card-label">Watchlist</div>
        <div class="analysis-card-value">${safe(a.coins_count, 0)}</div>
        <div class="analysis-card-sub muted">${safe(a.holdings_count, 0)} held</div>
      </div>
      <div class="analysis-card">
        <div class="analysis-card-label">Quote</div>
        <div class="analysis-card-value">${q}</div>
      </div>
    </div>
    <div class="analysis-pnl-block">
      <h4>Profit / loss</h4>
      <div class="analysis-pnl-rows">
        ${fmtPnl(a.vs_24h?.change, a.vs_24h?.change_pct, "vs 24h ago")}
      </div>
      <p class="muted analysis-note">Combined value from your balances in this group. 24h chart uses hourly candles when available.</p>
    </div>
    <div class="analysis-chart-block">
      <h4>Combined holdings value <span class="muted">(24h)</span></h4>
      <div class="analysis-chart-large">
        <svg class="portfolio-chart portfolio-chart-lg" viewBox="0 0 560 120" preserveAspectRatio="none">
          ${chartSvg}
        </svg>
        ${!chartSvg ? "<p class='muted analysis-note'>No chart — add balances or wait for market data.</p>" : ""}
      </div>
    </div>
    <div class="analysis-top-assets-block">
      <h4>Top holdings <span class="muted">(24h value chart)</span></h4>
      ${renderTopAssetsSection(a.top_assets, q)}
    </div>
    <div class="analysis-coins-table-block">
      <h4>All group coins <span class="muted">(click row for coin analysis)</span></h4>
      <div class="table-wrap table-sticky">
        <table class="data-table group-breakdown-table">
          <thead>
            <tr>
              <th>Coin</th>
              <th>Balance</th>
              <th>24h</th>
              <th>Value</th>
              <th>Share</th>
            </tr>
          </thead>
          <tbody>${breakdownRows || "<tr><td colspan='5' class='muted'>No coins</td></tr>"}</tbody>
        </table>
      </div>
    </div>`;

  body.querySelectorAll("[data-coin-click]").forEach((row) => {
    row.addEventListener("click", () => {
      const coin = row.dataset.coinClick;
      if (coin) openCoinAnalysisModal(coin);
    });
  });
}

async function openGroupAnalysisModal(groupId) {
  if (!groupId) return;
  state.activeGroupAnalysisId = groupId;
  state.groupAnalysis = null;
  const body = $("#group-analysis-body");
  if (body) body.innerHTML = "<p class='muted split-preview-loading'>Loading group analysis…</p>";
  openModal("group-analysis-modal");
  try {
    const data = await api(`/api/groups/${encodeURIComponent(groupId)}/analysis`);
    state.groupAnalysis = data;
    if (data.inr_rate && !state.inrRate) {
      state.inrRate = parseFloat(data.inr_rate);
      state.inrSource = data.inr_source || null;
    }
    renderGroupAnalysisModal(data);
  } catch (e) {
    if (body) body.innerHTML = `<p class="neg">${safe(e.message)}</p>`;
    toast(e.message, "err");
  }
}

function renderPortfolioAnalysisModal() {
  const body = $("#portfolio-analysis-body");
  const a = state.portfolioAnalytics;
  if (!body || !a) return;
  const q = a.quote || state.quote;
  const day = a.day || {};
  const srcLabel =
    day.start_source === "snapshot"
      ? "from first snapshot today"
      : day.start_source === "estimated_24h"
        ? "estimated from 24h price change"
        : "estimated";

  body.innerHTML = `
    <div class="analysis-current">
      <div class="analysis-current-label">Current value</div>
      <div class="analysis-current-value">${formatMoney(a.current_value, q)}</div>
    </div>
    <div class="analysis-grid">
      <div class="analysis-card">
        <div class="analysis-card-label">Start of day</div>
        <div class="analysis-card-value">${day.start_value ? formatMoney(day.start_value, q) : "—"}</div>
        <div class="analysis-card-sub muted">${srcLabel}</div>
      </div>
      <div class="analysis-card">
        <div class="analysis-card-label">End of day (now)</div>
        <div class="analysis-card-value">${formatMoney(day.end_value || a.current_value, q)}</div>
      </div>
      <div class="analysis-card">
        <div class="analysis-card-label">Day high</div>
        <div class="analysis-card-value pos">${formatMoney(day.high_value, q)}</div>
      </div>
      <div class="analysis-card">
        <div class="analysis-card-label">Day low</div>
        <div class="analysis-card-value neg">${formatMoney(day.low_value, q)}</div>
      </div>
    </div>
    <div class="analysis-pnl-block">
      <h4>Profit / loss</h4>
      <div class="analysis-pnl-rows">
        ${fmtPnl(a.vs_yesterday?.change, a.vs_yesterday?.change_pct, "vs yesterday")}
        ${fmtPnl(a.vs_week_ago?.change, a.vs_week_ago?.change_pct, "vs 1 week ago")}
      </div>
      <p class="muted analysis-note">Week comparison uses saved snapshots when available; otherwise only 24h estimate is shown. History builds as you use the dashboard.</p>
    </div>
    <div class="analysis-chart-block">
      <h4>Total portfolio value</h4>
      <div class="analysis-chart-large">
        <svg class="portfolio-chart portfolio-chart-lg" viewBox="0 0 560 120" preserveAspectRatio="none">
          ${buildPortfolioChartSvg(a, 560, 120)}
        </svg>
      </div>
    </div>
    <div class="analysis-top-assets-block">
      <h4>Top holdings <span class="muted">(24h value chart)</span></h4>
      ${renderTopAssetsSection(a.top_assets, q)}
    </div>`;
}

function openPortfolioAnalysisModal() {
  if (!state.portfolioAnalytics) return;
  renderPortfolioAnalysisModal();
  const inrLabel = $("#inr-rate-label");
  if (inrLabel) {
    if (state.inrRate) {
      const src =
        state.inrSource === "env"
          ? "manual .env rate"
          : state.inrSource === "gate"
            ? "Gate.io"
            : state.inrSource || "live FX";
      inrLabel.textContent = `1 USDT ≈ ₹${fmtNum(state.inrRate, 2)} (${src})`;
    } else {
      inrLabel.textContent = "INR rate loading failed — set INR_PER_USDT in .env";
    }
  }
  const toggle = $("#inr-display-toggle");
  if (toggle) toggle.checked = state.displayInINR;
  openModal("portfolio-analysis-modal");
}

function applyInrDisplay(on) {
  state.displayInINR = on;
  if (state.portfolio) renderPortfolio(state.portfolio);
  if (state.portfolioAnalytics) renderPortfolioAnalysisModal();
  if (state.coinAnalysis) renderCoinAnalysisModal(state.coinAnalysis);
  if (state.groupAnalysis) renderGroupAnalysisModal(state.groupAnalysis);
}

function coinColor(sym) {
  let h = 0;
  for (let i = 0; i < sym.length; i++) h = sym.charCodeAt(i) + ((h << 5) - h);
  return COIN_COLORS[Math.abs(h) % COIN_COLORS.length];
}

function coinAvatar(sym, size = "md") {
  const sz = size === "sm" ? 28 : 32;
  return `<span class="coin-avatar" style="width:${sz}px;height:${sz}px;background:${coinColor(sym)}">${sym.slice(0, 3)}</span>`;
}

let assetTipCoin = null;

function ensureAssetTipEl() {
  let el = document.getElementById("asset-tip");
  if (!el) {
    el = document.createElement("div");
    el.id = "asset-tip";
    el.className = "asset-tip hidden";
    el.setAttribute("role", "tooltip");
    document.body.appendChild(el);
  }
  return el;
}

function buildAssetTipContent(asset, quote) {
  const coin = asset.currency || asset.coin || "—";
  const q = quote || state.quote;
  const hasRange = asset.high_24h || asset.low_24h || asset.value_high_24h || asset.value_low_24h;
  if (!hasRange) {
    return `<div class="asset-tip-title">${coinAvatar(coin, "sm")}<strong>${coin}</strong></div>
      <p class="muted asset-tip-empty">Day range unavailable</p>`;
  }
  const priceHigh = asset.high_24h ? `${fmtNum(asset.high_24h, 4)} ${q}` : "—";
  const priceLow = asset.low_24h ? `${fmtNum(asset.low_24h, 4)} ${q}` : "—";
  const valHigh = asset.value_high_24h ? formatMoney(asset.value_high_24h, q) : "—";
  const valLow = asset.value_low_24h ? formatMoney(asset.value_low_24h, q) : "—";
  return `
    <div class="asset-tip-title">${coinAvatar(coin, "sm")}<strong>${coin}</strong></div>
    <div class="asset-tip-row">
      <span class="muted">Day high</span>
      <span class="pos asset-tip-val">${valHigh}</span>
    </div>
    <div class="asset-tip-sub muted">${priceHigh}</div>
    <div class="asset-tip-row">
      <span class="muted">Day low</span>
      <span class="neg asset-tip-val">${valLow}</span>
    </div>
    <div class="asset-tip-sub muted">${priceLow}</div>`;
}

function positionAssetTip(x, y) {
  const el = ensureAssetTipEl();
  const pad = 14;
  const w = el.offsetWidth;
  const h = el.offsetHeight;
  let left = x + pad;
  let top = y + pad;
  if (left + w > window.innerWidth - 10) left = Math.max(8, x - w - pad);
  if (top + h > window.innerHeight - 10) top = Math.max(8, y - h - pad);
  el.style.left = `${left}px`;
  el.style.top = `${top}px`;
}

function showAssetTip(asset, quote, x, y) {
  const coin = asset.currency || asset.coin;
  if (assetTipCoin === coin) {
    positionAssetTip(x, y);
    return;
  }
  assetTipCoin = coin;
  const el = ensureAssetTipEl();
  el.innerHTML = buildAssetTipContent(asset, quote);
  el.classList.remove("hidden");
  positionAssetTip(x, y);
}

function hideAssetTip() {
  assetTipCoin = null;
  const el = document.getElementById("asset-tip");
  if (el) el.classList.add("hidden");
}

const assetTipMap = new Map();

function updateAssetTipMap(assets) {
  assetTipMap.clear();
  for (const a of assets || []) {
    if (a.currency) assetTipMap.set(a.currency, a);
  }
}

function bindAssetClickHandlers() {
  const roots = ["#portfolio-table tbody", "#allocation-bars"];
  roots.forEach((sel) => {
    const root = document.querySelector(sel);
    if (!root || root.dataset.assetClickBound) return;
    root.dataset.assetClickBound = "1";
    root.addEventListener("click", (e) => {
      const row = e.target.closest("[data-asset]");
      if (!row || !root.contains(row)) return;
      openCoinAnalysisModal(row.dataset.asset);
    });
  });
}

function bindAssetHoverTips() {
  const roots = ["#portfolio-table tbody", "#allocation-bars"];
  roots.forEach((sel) => {
    const root = document.querySelector(sel);
    if (!root || root.dataset.assetTipsBound) return;
    root.dataset.assetTipsBound = "1";
    root.addEventListener("mouseover", (e) => {
      const row = e.target.closest("[data-asset]");
      if (!row || !root.contains(row)) return;
      const asset = assetTipMap.get(row.dataset.asset);
      if (!asset) return;
      showAssetTip(asset, state.quote, e.clientX, e.clientY);
    });
    root.addEventListener("mousemove", (e) => {
      const el = document.getElementById("asset-tip");
      if (el && !el.classList.contains("hidden")) positionAssetTip(e.clientX, e.clientY);
    });
    root.addEventListener("mouseleave", (e) => {
      if (!e.relatedTarget || !root.contains(e.relatedTarget)) hideAssetTip();
    });
  });
}

function fmtPct(v) {
  if (!v) return "<span class='muted'>—</span>";
  const n = parseFloat(v);
  const cls = n >= 0 ? "pos" : "neg";
  const arrow = n >= 0 ? "▲" : "▼";
  return `<span class="pct-badge ${cls}">${arrow} ${Math.abs(n).toFixed(2)}%</span>`;
}

function setStatus(id, msg, type = "") {
  const el = $("#" + id);
  if (!el) return;
  el.textContent = msg;
  el.className = `inline-status ${type}`.trim();
}

function setLoading(section, on) {
  const map = {
    portfolio: "portfolio-status",
    markets: "markets-status",
    groups: "groups-status",
    history: "history-status",
  };
  const id = map[section];
  if (!id) return;
  if (on) setStatus(id, "Loading from Gate.io…");
}

function updateSelectionUI() {
  const n = state.selectedCoins.size;
  $("#selected-count").textContent = n;
  $("#selection-bar-count").textContent = n;
  $("#create-group-btn").disabled = n === 0;
  $("#selection-bar")?.classList.toggle("hidden", n === 0);
}

function switchTab(name) {
  state.activeTab = name;
  $$(".top-tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".page-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
  const meta = PAGE_META[name];
  if (meta) {
    $("#page-title").textContent = meta.title;
    $("#page-subtitle").textContent = meta.sub;
  }
  if (name === "portfolio") loadPortfolio();
  if (name === "markets") loadMarkets();
  if (name === "groups") loadGroups();
  if (name === "history") loadHistory();
}

function renderDonut(assets) {
  const wrap = $("#donut-wrap");
  const chart = $("#donut-chart");
  const label = $("#donut-label");
  if (!wrap || !chart || !assets?.length) {
    wrap?.classList.add("hidden");
    return;
  }

  const top = assets.slice(0, 5);
  const total = top.reduce((s, a) => s + parseFloat(a.allocation_pct || 0), 0);
  let gradient = [];
  let acc = 0;

  top.forEach((a, i) => {
    const pct = parseFloat(a.allocation_pct || 0);
    const color = coinColor(a.currency);
    gradient.push(`${color} ${acc}% ${acc + pct}%`);
    acc += pct;
  });
  if (acc < 100) gradient.push(`rgba(255,255,255,0.06) ${acc}% 100%`);

  chart.style.background = `conic-gradient(${gradient.join(", ")})`;
  label.textContent = top[0]?.currency || "—";
  wrap.classList.remove("hidden");
}

async function loadStatus() {
  const data = await api("/api/status");
  clearError();
  state.quote = data.default_quote || "USDT";
  state.mode = data.mode;
  $$(".quote-label").forEach((el) => (el.textContent = state.quote));

  const badge = $("#status-badge");
  if (!data.configured) {
    badge.textContent = "API not configured";
    badge.className = "status-pill error";
    showError("API keys missing — edit .env with your Gate.io API key and secret, then restart the server.");
    return false;
  }
  badge.textContent = data.mode === "testnet" ? "Testnet" : "Live";
  badge.className = `status-pill ${data.mode === "testnet" ? "testnet" : "live"}`;

  const banner = $("#testnet-banner");
  if (data.mode === "testnet") {
    banner.classList.remove("hidden");
    banner.innerHTML = `Demo mode — funds at <a href="${data.testnet_portal}" target="_blank" rel="noopener">testnet.gate.com</a>. API keys: <a href="${data.api_key_url}" target="_blank" rel="noopener">Management</a>.`;
  } else {
    banner.classList.add("hidden");
  }
  return true;
}

function renderPortfolio(data) {
  if (!data || typeof data !== "object") {
    throw new Error("Invalid portfolio data");
  }
  try {
    state.portfolio = data;
    state.portfolioAnalytics = data.analytics || null;
    state.inrRate = data.inr_rate ? parseFloat(data.inr_rate) : null;
    state.inrSource = data.inr_source || null;
    const q = data.quote || state.quote;

    const heroTotal = $("#hero-total");
    if (heroTotal) heroTotal.textContent = formatMoney(data.total_value, q);

    const heroMeta = $("#hero-meta");
    if (heroMeta) {
      heroMeta.textContent = `${safe(data.holdings_count, 0)} assets · Top: ${safe(data.top_holding)} (${safe(data.top_holding_pct, 0)}%)`;
    }

    const heroPnl = $("#hero-pnl");
    if (heroPnl && data.analytics) {
      const vy = data.analytics.vs_yesterday;
      const vw = data.analytics.vs_week_ago;
      heroPnl.innerHTML = [
        vy?.available ? fmtPnl(vy.change, vy.change_pct, "24h") : "",
        vw?.available ? fmtPnl(vw.change, vw.change_pct, "7d") : "",
      ]
        .filter(Boolean)
        .join(" · ");
    }

    if (data.analytics) renderPortfolioChart(data.analytics);

    const summary = $("#portfolio-summary");
    if (summary) {
      summary.innerHTML = `
    <div class="summary-card"><div class="label">Holdings</div><div class="value">${safe(data.holdings_count, 0)}</div></div>
    <div class="summary-card"><div class="label">Top asset</div><div class="value">${safe(data.top_holding)}</div></div>
    <div class="summary-card"><div class="label">Top share</div><div class="value">${data.top_holding_pct ? safe(data.top_holding_pct) + "%" : "—"}</div></div>`;
    }

    const totalLabel = $("#portfolio-total-label");
    if (totalLabel) totalLabel.textContent = `Total ${formatMoney(data.total_value, q)}`;

    const assets = Array.isArray(data.assets) ? data.assets : [];
    const empty = $("#portfolio-empty");
    const tbody = $("#portfolio-table tbody");

    if (!assets.length) {
      if (tbody) tbody.innerHTML = "";
      empty?.classList.remove("hidden");
      const bars = $("#allocation-bars");
      if (bars) bars.innerHTML = "";
      $("#donut-wrap")?.classList.add("hidden");
      return;
    }
    empty?.classList.add("hidden");
    renderDonut(assets);

    const bars = $("#allocation-bars");
    if (bars) {
      bars.innerHTML = assets
        .slice(0, 8)
        .map((a) => `
      <div class="alloc-row asset-hover-row" data-asset="${safe(a.currency)}">
        <span class="coin-cell">${coinAvatar(a.currency, "sm")}<span>${safe(a.currency)}</span></span>
        <div class="alloc-bar"><div class="alloc-fill" style="width:${safe(a.allocation_pct, 0)}%;background:${coinColor(a.currency)}"></div></div>
        <span>${safe(a.allocation_pct, 0)}%</span>
      </div>`)
        .join("");
    }

    updateAssetTipMap(assets);
    bindAssetHoverTips();
    bindAssetClickHandlers();

    if (tbody) {
      tbody.innerHTML = assets
        .map((a) => `
      <tr class="asset-hover-row" data-asset="${safe(a.currency)}">
        <td><div class="coin-cell">${coinAvatar(a.currency)}<strong>${safe(a.currency)}</strong></div></td>
        <td>${safe(a.total)}</td>
        <td>${a.price ? fmtNum(a.price, 4) + " " + q : "—"}</td>
        <td>${fmtPct(a.change_pct)}</td>
        <td><strong>${a.value_quote ? formatMoney(a.value_quote, q) : "—"}</strong></td>
        <td><span class="alloc-pill">${safe(a.allocation_pct, 0)}%</span></td>
      </tr>`)
        .join("");
    }
  } catch (e) {
    throw new Error("Could not render portfolio: " + e.message);
  }
}

async function loadInrRate() {
  try {
    const fx = await api("/api/fx/inr");
    if (fx.inr_rate) {
      state.inrRate = parseFloat(fx.inr_rate);
      state.inrSource = fx.inr_source || null;
    }
  } catch {
    /* keep USDT display */
  }
}

async function loadPortfolio() {
  setLoading("portfolio", true);
  try {
    const data = await api(`/api/portfolio?quote=${encodeURIComponent(state.quote)}`);
    clearError();
    renderPortfolio(data);
    if (!state.inrRate) await loadInrRate();
    setStatus("portfolio-status", `Loaded ${data.holdings_count || 0} assets from Gate.io`, "ok");
  } catch (e) {
    setStatus("portfolio-status", e.message, "err");
    showError("Portfolio: " + e.message);
    toast(e.message, "err");
  }
}

function getFilteredMarkets() {
  const filter = state.marketFilter.trim().toUpperCase();
  return filter
    ? state.markets.filter((m) => m.coin.includes(filter) || m.pair.includes(filter))
    : state.markets;
}

function renderMarkets() {
  const q = state.quote;
  const filtered = getFilteredMarkets();
  const display = filtered.slice(0, MARKETS_DISPLAY_LIMIT);
  const truncated = filtered.length > MARKETS_DISPLAY_LIMIT;

  $("#markets-count").textContent = `${filtered.length} of ${state.markets.length} · ${q}`;
  updateSelectionUI();

  const note = $("#markets-table-note");
  if (truncated && !state.marketFilter.trim()) {
    note.textContent = `Showing top ${MARKETS_DISPLAY_LIMIT} by volume. Search to find other coins.`;
    note.classList.remove("hidden");
  } else if (truncated) {
    note.textContent = `${filtered.length} matches — showing first ${MARKETS_DISPLAY_LIMIT}. Refine your search.`;
    note.classList.remove("hidden");
  } else {
    note.classList.add("hidden");
  }

  $("#markets-table tbody").innerHTML = display
    .map((m) => {
      const checked = state.selectedCoins.has(m.coin);
      return `
        <tr class="${checked ? "row-selected" : ""}">
          <td class="col-check"><input type="checkbox" data-coin="${m.coin}" ${checked ? "checked" : ""} /></td>
          <td><div class="coin-cell">${coinAvatar(m.coin)}<strong>${m.coin}</strong></div></td>
          <td class="muted">${m.pair}</td>
          <td><strong>${fmtNum(m.last, 4)}</strong> <span class="muted">${q}</span></td>
          <td>${fmtPct(m.change_pct)}</td>
          <td class="muted">${fmtNum(m.quote_volume, 0)}</td>
        </tr>`;
    })
    .join("");

  $$("#markets-table tbody input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", () => {
      const coin = cb.dataset.coin;
      const row = cb.closest("tr");
      if (cb.checked) {
        state.selectedCoins.add(coin);
        row?.classList.add("row-selected");
      } else {
        state.selectedCoins.delete(coin);
        row?.classList.remove("row-selected");
      }
      updateSelectionUI();
    });
  });
}

async function loadMarkets() {
  setLoading("markets", true);
  try {
    const data = await api(`/api/markets?quote=${encodeURIComponent(state.quote)}`);
    clearError();
    state.markets = data.markets || [];
    renderMarkets();
    setStatus("markets-status", `Loaded ${state.markets.length} markets from Gate.io`, "ok");
  } catch (e) {
    setStatus("markets-status", e.message, "err");
    showError("Markets: " + e.message);
    toast(e.message, "err");
  }
}

function formatAllocChips(coins, allocations = {}) {
  const hasAny = coins.some((c) => (allocations[c] || "").trim());
  if (!hasAny) {
    return coins.map((c) => `<span class="chip">${c}</span>`).join("");
  }
  return coins
    .map((c) => {
      const p = (allocations[c] || "").trim();
      return p
        ? `<span class="chip">${c} <span class="chip-pct">${p}%</span></span>`
        : `<span class="chip">${c} <span class="chip-pct">auto</span></span>`;
    })
    .join("");
}

function renderGroups() {
  const groups = state.groups;
  const empty = $("#groups-empty");
  const list = $("#groups-list");

  if (!groups.length) {
    empty.classList.remove("hidden");
    list.innerHTML = "";
    return;
  }
  empty.classList.add("hidden");

  list.innerHTML = groups
    .map((g) => {
      const holdings = g.holdings || [];
      const tiles = holdings
        .map((h) => {
          const hasBal = parseFloat(h.total) > 0;
          return `
          <div class="holding-tile ${hasBal ? "has-balance" : ""}">
            <div class="holding-tile-head">${coinAvatar(h.coin, "sm")}<strong>${h.coin}</strong></div>
            <div class="tile-row">Balance: ${h.total}</div>
            ${h.last ? `<div class="tile-row">Price: ${fmtNum(h.last, 4)} ${g.quote}</div>` : ""}
            ${h.value_quote ? `<div class="tile-value">≈ ${fmtNum(h.value_quote, 2)} ${g.quote}</div>` : ""}
          </div>`;
        })
        .join("");

      return `
        <div class="group-card" data-id="${g.id}">
          <div class="group-head">
            <div class="group-head-main group-clickable" data-analyze="${g.id}" role="button" tabindex="0" title="Click for group analysis">
              <div class="group-title">${g.name}</div>
              <div class="group-meta">${g.coins.length} coins · click for analysis</div>
              <div class="group-stats">
                <span class="group-stat">Value <strong>${fmtNum(g.total_value, 2)} ${g.quote}</strong></span>
                <span class="group-stat">Held <strong>${g.holdings_count || 0}</strong></span>
              </div>
              <div class="chips">${formatAllocChips(g.coins, g.allocations || {})}</div>
            </div>
            <div class="group-actions">
              <button type="button" class="btn btn-ghost btn-sm" data-edit-coins="${g.id}">Edit coins</button>
              <button type="button" class="btn btn-ghost btn-sm" data-alloc="${g.id}">Set %</button>
              <button type="button" class="btn btn-buy btn-sm" data-buy="${g.id}">Buy</button>
              <button type="button" class="btn btn-sell btn-sm" data-sell="${g.id}">Sell</button>
              <button type="button" class="btn btn-ghost btn-sm" data-delete="${g.id}">Delete</button>
            </div>
          </div>
          <div class="group-holdings">${tiles}</div>
        </div>`;
    })
    .join("");

  list.querySelectorAll("[data-alloc]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openAllocModal(btn.dataset.alloc);
    });
  });
  list.querySelectorAll("[data-edit-coins]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openEditCoinsModal(btn.dataset.editCoins);
    });
  });
  list.querySelectorAll("[data-analyze]").forEach((el) => {
    el.addEventListener("click", () => openGroupAnalysisModal(el.dataset.analyze));
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openGroupAnalysisModal(el.dataset.analyze);
      }
    });
  });
  list.querySelectorAll("[data-buy]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openBuyModal(btn.dataset.buy);
    });
  });
  list.querySelectorAll("[data-sell]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openSellModal(btn.dataset.sell);
    });
  });
  list.querySelectorAll("[data-delete]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteGroup(btn.dataset.delete);
    });
  });
}

function getEditCoinsMarkets() {
  const filter = state.editCoinsFilter.trim().toUpperCase();
  const markets = state.markets.length
    ? state.markets
    : state.groups
        .flatMap((g) => g.coins || [])
        .map((c) => ({ coin: c, pair: `${c}_${state.quote}` }));
  if (!filter) return markets;
  return markets.filter(
    (m) => m.coin.includes(filter) || (m.pair && m.pair.includes(filter))
  );
}

function updateEditCoinsCount() {
  const el = $("#edit-coins-count");
  if (el) el.textContent = String(state.editCoinsSelected.size);
}

function renderEditCoinsList() {
  const list = $("#edit-coins-list");
  if (!list) return;
  const visible = getEditCoinsMarkets().slice(0, MARKETS_DISPLAY_LIMIT);
  if (!visible.length) {
    list.innerHTML = "<p class='muted edit-coins-empty'>No coins match your search.</p>";
    updateEditCoinsCount();
    return;
  }
  list.innerHTML = visible
    .map((m) => {
      const checked = state.editCoinsSelected.has(m.coin);
      return `
    <label class="edit-coin-row ${checked ? "selected" : ""}">
      <input type="checkbox" data-edit-coin="${m.coin}" ${checked ? "checked" : ""} />
      <span class="coin-cell">${coinAvatar(m.coin, "sm")}<strong>${m.coin}</strong></span>
      <span class="muted edit-coin-pair">${safe(m.pair)}</span>
      ${m.last ? `<span class="edit-coin-price">${fmtNum(m.last, 4)}</span>` : ""}
    </label>`;
    })
    .join("");

  list.querySelectorAll("input[data-edit-coin]").forEach((cb) => {
    cb.addEventListener("change", () => {
      const coin = cb.dataset.editCoin;
      const row = cb.closest(".edit-coin-row");
      if (cb.checked) {
        state.editCoinsSelected.add(coin);
        row?.classList.add("selected");
      } else {
        state.editCoinsSelected.delete(coin);
        row?.classList.remove("selected");
      }
      updateEditCoinsCount();
    });
  });
  updateEditCoinsCount();
}

async function openEditCoinsModal(groupId) {
  const group = state.groups.find((g) => g.id === groupId);
  if (!group) return;
  state.activeEditCoinsGroupId = groupId;
  state.editCoinsSelected = new Set(group.coins || []);
  state.editCoinsFilter = "";
  const search = $("#edit-coins-search");
  if (search) search.value = "";
  $("#edit-coins-title").textContent = `Edit coins — ${group.name}`;
  openModal("edit-coins-modal");

  if (!state.markets.length) {
    const list = $("#edit-coins-list");
    if (list) list.innerHTML = "<p class='muted'>Loading markets…</p>";
    try {
      const data = await api(`/api/markets?quote=${encodeURIComponent(state.quote)}`);
      state.markets = data.markets || [];
    } catch (e) {
      toast(e.message, "err");
    }
  }
  renderEditCoinsList();
}

async function saveEditCoins() {
  const groupId = state.activeEditCoinsGroupId;
  if (!groupId) return;
  const coins = [...state.editCoinsSelected].sort();
  if (!coins.length) {
    toast("Select at least one coin", "err");
    return;
  }
  try {
    await api(`/api/groups/${groupId}/coins`, {
      method: "PUT",
      body: JSON.stringify({ coins }),
    });
    closeAllModals();
    toast("Group coins updated", "ok");
    await loadGroups();
  } catch (e) {
    toast(e.message, "err");
  }
}

function selectAllEditCoinsVisible() {
  getEditCoinsMarkets()
    .slice(0, MARKETS_DISPLAY_LIMIT)
    .forEach((m) => state.editCoinsSelected.add(m.coin));
  renderEditCoinsList();
}

function clearEditCoinsSelection() {
  state.editCoinsSelected.clear();
  renderEditCoinsList();
}

async function loadGroups() {
  setLoading("groups", true);
  try {
    const data = await api("/api/groups");
    clearError();
    state.groups = data.groups || [];
    renderGroups();
    setStatus("groups-status", `${state.groups.length} group(s) loaded`, "ok");
  } catch (e) {
    setStatus("groups-status", e.message, "err");
    showError("Groups: " + e.message);
    toast(e.message, "err");
  }
}

function openModal(id) {
  $("#" + id)?.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

function closeAllModals() {
  $$(".modal").forEach((m) => m.classList.add("hidden"));
  document.body.style.overflow = "";
}

function openGroupModal() {
  const chips = [...state.selectedCoins].sort();
  $("#group-preview-chips").innerHTML = chips.map((c) => `<span class="chip">${c}</span>`).join("");
  $("#group-name-input").value = "";
  openModal("group-modal");
  setTimeout(() => $("#group-name-input")?.focus(), 100);
}

async function saveGroup() {
  const name = $("#group-name-input").value.trim();
  const coins = [...state.selectedCoins];
  if (!name) {
    toast("Enter a group name", "err");
    return;
  }
  if (!coins.length) {
    toast("Select coins first", "err");
    return;
  }
  try {
    await api("/api/groups", {
      method: "POST",
      body: JSON.stringify({ name, coins, quote: state.quote }),
    });
    state.selectedCoins.clear();
    updateSelectionUI();
    closeAllModals();
    toast("Group created", "ok");
    switchTab("groups");
  } catch (e) {
    toast(e.message, "err");
  }
}

function openAllocModal(groupId) {
  const group = state.groups.find((g) => g.id === groupId);
  if (!group) return;
  state.activeAllocGroupId = groupId;
  $("#alloc-modal-title").textContent = `Allocation — ${group.name}`;
  const allocs = group.allocations || {};
  $("#alloc-rows").innerHTML = group.coins
    .map(
      (c) => `
    <div class="alloc-row-edit">
      <label>${c}</label>
      <input type="number" min="0" max="100" step="any" data-alloc-coin="${c}"
        placeholder="auto" value="${(allocs[c] || "").trim()}" />
    </div>`
    )
    .join("");
  updateAllocSumHint();
  openModal("alloc-modal");
}

function getAllocInputs() {
  const inputs = $$("#alloc-rows input[data-alloc-coin]");
  const allocations = {};
  inputs.forEach((inp) => {
    allocations[inp.dataset.allocCoin] = inp.value.trim();
  });
  return allocations;
}

function updateAllocSumHint() {
  const hint = $("#alloc-sum-hint");
  if (!hint) return;
  const allocations = getAllocInputs();
  let sum = 0;
  Object.values(allocations).forEach((v) => {
    if (v) sum += parseFloat(v) || 0;
  });
  if (sum === 0) {
    hint.textContent = "No % set — buys will split equally across all coins.";
    hint.className = "alloc-sum-hint";
    return;
  }
  const remainder = 100 - sum;
  if (remainder === 0) {
    hint.textContent =
      "100% allocated — buy amount is divided only among coins with a set % (blank coins are skipped).";
    hint.className = "alloc-sum-hint ok";
    return;
  }
  if (remainder > 0) {
    hint.textContent = `Set total: ${sum.toFixed(1)}% · Remaining ${remainder.toFixed(1)}% split equally among blank coins`;
    hint.className = sum > 100 ? "alloc-sum-hint warn" : "alloc-sum-hint ok";
    return;
  }
  hint.textContent = `Set total: ${sum.toFixed(1)}%`;
  hint.className = "alloc-sum-hint warn";
}

async function saveAllocations() {
  const groupId = state.activeAllocGroupId;
  if (!groupId) return;
  const allocations = getAllocInputs();
  let sum = 0;
  Object.values(allocations).forEach((v) => {
    if (v) sum += parseFloat(v) || 0;
  });
  if (sum > 100) {
    toast("Allocations cannot exceed 100%", "err");
    return;
  }
  try {
    await api(`/api/groups/${groupId}/allocations`, {
      method: "POST",
      body: JSON.stringify({ allocations }),
    });
    closeAllModals();
    toast("Allocations saved", "ok");
    await loadGroups();
  } catch (e) {
    toast(e.message, "err");
  }
}

function getQuoteBalanceFromPortfolio(quote) {
  const assets = state.portfolio?.assets;
  if (!assets) return null;
  const row = assets.find((a) => (a.currency || "").toUpperCase() === (quote || state.quote).toUpperCase());
  return row?.available ?? null;
}

function previewBalanceStripHtml(
  quote,
  current,
  after,
  { currentLabel = "Current balance", afterLabel = "After trade" } = {}
) {
  if (!current && !after) return "";
  const afterHtml =
    after != null && after !== ""
      ? `<span class="trade-balance-item trade-balance-after">${afterLabel}: <strong>${after} ${quote}</strong></span>`
      : "";
  return `
    <div class="trade-balance-banner preview-balance-strip">
      <span class="trade-balance-item">${currentLabel}: <strong>${current ?? "0"} ${quote}</strong></span>
      ${afterHtml}
    </div>`;
}

const BUY_PREVIEW_COLS = `
  <thead>
    <tr>
      <th>Coin</th>
      <th>Current</th>
      <th>You spend</th>
      <th class="split-col-get">You get</th>
      <th>After buy</th>
    </tr>
  </thead>`;

const SELL_PREVIEW_COLS = `
  <thead>
    <tr>
      <th>Coin</th>
      <th>Current</th>
      <th>You sell</th>
      <th class="split-col-get">You get</th>
      <th>Coin after</th>
    </tr>
  </thead>`;

function previewDashCell(pending = false) {
  return pending ? "<span class='muted'>…</span>" : "<span class='muted'>—</span>";
}

function buyBalanceRowsFromHoldings(group, { pending = false } = {}) {
  const holdings = group?.holdings || [];
  const dash = previewDashCell(pending);
  if (!holdings.length) {
    return `<tr><td colspan="5" class="muted preview-hint">No coins in this group.</td></tr>`;
  }
  return holdings
    .map((h) => {
      const bal = h.total || h.available || "0";
      return `
        <tr>
          <td class="split-coin">${coinAvatar(h.coin, "sm")}<strong>${h.coin}</strong></td>
          <td>${bal}</td>
          <td>${dash}</td>
          <td class="split-col-get">${dash}</td>
          <td>${bal}</td>
        </tr>`;
    })
    .join("");
}

function sellBalanceRowsFromHoldings(group, { pending = false } = {}) {
  const holdings = (group?.holdings || []).filter((h) => parseFloat(h.available || 0) > 0);
  const dash = previewDashCell(pending);
  if (!holdings.length) {
    return `<tr><td colspan="5" class="muted preview-hint">No coins with balance in this group.</td></tr>`;
  }
  return holdings
    .map((h) => {
      const bal = h.total || h.available || "0";
      return `
        <tr>
          <td class="split-coin">${coinAvatar(h.coin, "sm")}<strong>${h.coin}</strong></td>
          <td>${bal}</td>
          <td>${dash}</td>
          <td class="split-col-get">${dash}</td>
          <td>${bal}</td>
        </tr>`;
    })
    .join("");
}

function renderBuySplitPlaceholder(message = "Enter a total amount above to see spend and estimated coins.") {
  const group = state.groups.find((g) => g.id === state.activeBuyGroupId);
  const quote = group?.quote || state.quote;
  const quoteBal = getQuoteBalanceFromPortfolio(quote);
  const box = $("#buy-split-preview");
  box.className = "split-preview split-preview-empty";
  box.innerHTML = `
    ${previewBalanceStripHtml(quote, quoteBal, null, {
      currentLabel: `${quote} balance`,
      afterLabel: `${quote} after buy`,
    })}
    <table class="split-table preview-balances-table">
      ${BUY_PREVIEW_COLS}
      <tbody>${buyBalanceRowsFromHoldings(group)}</tbody>
    </table>
    <p class="preview-hint">${message}</p>`;
}

function renderBuySplitLoading() {
  const group = state.groups.find((g) => g.id === state.activeBuyGroupId);
  const quote = group?.quote || state.quote;
  const quoteBal = getQuoteBalanceFromPortfolio(quote);
  const box = $("#buy-split-preview");
  box.className = "split-preview split-preview-loading";
  box.innerHTML = `
    ${previewBalanceStripHtml(quote, quoteBal, null, {
      currentLabel: `${quote} balance`,
      afterLabel: `${quote} after buy`,
    })}
    <table class="split-table preview-balances-table">
      ${BUY_PREVIEW_COLS}
      <tbody>${buyBalanceRowsFromHoldings(group, { pending: true })}</tbody>
    </table>
    <p class="preview-hint">Calculating split…</p>`;
}

let buyPreviewAbort = null;
let buyPreviewSeq = 0;

function isSplitRowIncluded(row) {
  if (row.included === false) return false;
  return parseFloat(row.amount || 0) > 0;
}

function renderBuySplitPreview(preview) {
  const box = $("#buy-split-preview");
  const quote = preview.quote || state.quote;
  const total = parseFloat(preview.total_amount || 0);
  const breakdown = preview.breakdown || [];
  const included = breakdown.filter((row) => isSplitRowIncluded(row));
  const skipped = breakdown.filter((row) => !isSplitRowIncluded(row));
  const coinCount = included.length;

  const barSegments = included
    .map((row) => {
      const pct = parseFloat(row.pct_of_total || 0);
      const color = coinColor(row.coin);
      const label = pct >= 8 ? row.coin : "";
      return `<div class="split-bar-seg" style="width:${pct}%;background:${color}" title="${row.coin}: ${row.pct_of_total}%">
        <span class="split-bar-label">${label}</span>
      </div>`;
    })
    .join("");

  const legend = included
    .map((row) => {
      const color = coinColor(row.coin);
      return `<span class="split-legend-item"><span class="split-legend-dot" style="background:${color}"></span>${row.coin} ${row.pct_of_total}%</span>`;
    })
    .join("");

  const rows = breakdown
    .map((row) => {
      if (!isSplitRowIncluded(row)) {
        return `
        <tr class="split-row-skipped">
          <td class="split-coin">${coinAvatar(row.coin, "sm")}<strong>${row.coin}</strong></td>
          <td class="muted">${row.current_balance || "0"}</td>
          <td class="split-amt muted">—</td>
          <td class="split-col-get muted">—</td>
          <td class="muted">${row.balance_after || row.current_balance || "0"}</td>
        </tr>`;
      }
      const getAmt = row.est_coin_amount
        ? `<strong>${row.est_coin_amount}</strong> <span class="muted">${row.coin}</span>`
        : "<span class='muted'>—</span>";
      const spendAmt = `<strong>${fmtNum(row.amount, 4)}</strong> <span class="muted">${quote}</span>`;
      const ruleHint =
        row.rule_text
          ? `<div class="split-rule-hint muted">${row.pct_of_total}% · ${row.rule_text}</div>`
          : "";
      return `
        <tr>
          <td class="split-coin">${coinAvatar(row.coin, "sm")}<strong>${row.coin}</strong>${ruleHint}</td>
          <td>${row.current_balance || "0"}</td>
          <td class="split-amt">${spendAmt}</td>
          <td class="split-col-get">${getAmt}</td>
          <td>${row.balance_after || "—"}</td>
        </tr>`;
    })
    .join("");

  const skippedNote =
    skipped.length > 0
      ? `<p class="split-skipped-note">${skipped.length} coin(s) skipped — not part of this buy</p>`
      : "";

  const issues = preview.issues || [];
  const issuesBox =
    issues.length > 0
      ? `<div class="split-issues"><strong>Cannot buy yet:</strong><ul>${issues
          .map((i) => `<li>${i}</li>`)
          .join("")}</ul><span class="muted">Gate.io minimum per order is usually ${preview.min_order_quote || "3"} ${quote}.</span></div>`
      : "";

  const canBuy = preview.can_buy !== false && issues.length === 0;
  const buyBtn = $("#buy-modal-confirm");
  if (buyBtn) buyBtn.disabled = !canBuy;

  const balanceStrip = previewBalanceStripHtml(
    quote,
    preview.quote_balance,
    preview.quote_balance_after,
    { currentLabel: `${quote} balance`, afterLabel: `${quote} after buy` }
  );

  box.className = "split-preview";
  box.innerHTML = `
    ${balanceStrip}
    <div class="split-preview-head">
      <div>
        <div class="split-preview-total">${fmtNum(total, 2)} ${quote}</div>
        <div class="split-preview-sub">divided among ${coinCount} coin${coinCount === 1 ? "" : "s"}</div>
      </div>
      <div class="split-preview-mode">${preview.mode === "equal" ? "Equal split" : "Custom %"}</div>
    </div>
    <p class="split-preview-summary">${preview.summary_text || ""}</p>
    <div class="split-bar-wrap">
      <div class="split-bar">${barSegments}</div>
      <div class="split-legend">${legend}</div>
    </div>
    <table class="split-table">
      <thead>
        <tr>
          <th>Coin</th>
          <th>Current</th>
          <th>You spend</th>
          <th class="split-col-get">You get</th>
          <th>After buy</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
      <tfoot>
        <tr>
          <td colspan="2" class="split-foot-label">Total (active coins)</td>
          <td class="split-amt"><strong>${fmtNum(total, 2)}</strong> ${quote}</td>
          <td class="split-col-get">—</td>
          <td>—</td>
        </tr>
      </tfoot>
    </table>
    ${issuesBox}
    ${skippedNote}`;
}

function openBuyModal(groupId) {
  const group = state.groups.find((g) => g.id === groupId);
  if (!group) return;
  state.activeBuyGroupId = groupId;
  $("#buy-modal-title").textContent = `Buy — ${group.name}`;
  $("#buy-amount-input").value = "";
  const buyBtn = $("#buy-modal-confirm");
  if (buyBtn) buyBtn.disabled = false;
  renderBuySplitPlaceholder();
  openModal("buy-modal");
  api(`/api/groups/${groupId}/warm-cache`, { method: "POST" }).catch(() => {});
  setTimeout(() => $("#buy-amount-input")?.focus(), 100);
}

async function updateBuyPreview() {
  const group = state.groups.find((g) => g.id === state.activeBuyGroupId);
  if (!group) return;
  const total = $("#buy-amount-input").value.trim();
  if (!total || parseFloat(total) <= 0) {
    if (buyPreviewAbort) buyPreviewAbort.abort();
    renderBuySplitPlaceholder();
    return;
  }
  if (buyPreviewAbort) buyPreviewAbort.abort();
  buyPreviewAbort = new AbortController();
  const seq = ++buyPreviewSeq;
  const signal = buyPreviewAbort.signal;
  renderBuySplitLoading();
  try {
    const preview = await api(
      `/api/groups/${state.activeBuyGroupId}/buy-preview?total_amount=${encodeURIComponent(total)}`,
      { signal }
    );
    if (seq !== buyPreviewSeq) return;
    renderBuySplitPreview(preview);
  } catch (e) {
    if (e.name === "AbortError") return;
    if (seq !== buyPreviewSeq) return;
    renderBuySplitPlaceholder(e.message);
  }
}

async function confirmBuy() {
  const total = $("#buy-amount-input").value.trim();
  if (!total || parseFloat(total) <= 0) {
    toast("Enter a valid total amount", "err");
    return;
  }
  try {
    const res = await api(`/api/groups/${state.activeBuyGroupId}/buy`, {
      method: "POST",
      body: JSON.stringify({ total_amount: total }),
    });
    closeAllModals();
    toast(res.execution?.message || "Buy orders filled", "ok");
    await loadGroups();
    await loadPortfolio();
    if (state.activeTab === "history") await loadHistory();
  } catch (e) {
    toast(e.message, "err");
  }
}

function openSellModal(groupId) {
  const group = state.groups.find((g) => g.id === groupId);
  if (!group) return;
  state.activeSellGroupId = groupId;
  state.sellSelected = new Set();
  state.sellAmounts = {};
  $("#sell-modal-title").textContent = `Sell — ${group.name}`;
  const sellBtn = $("#sell-modal-confirm");
  if (sellBtn) sellBtn.disabled = false;
  renderSellCoinList(group);
  renderSellSplitPlaceholder();
  openModal("sell-modal");
}

function renderSellCoinList(group) {
  const list = $("#sell-coin-list");
  if (!list) return;
  const holdings = group.holdings || [];
  const withBal = holdings.filter((h) => parseFloat(h.available || 0) > 0);

  if (!withBal.length) {
    list.innerHTML = `<p class="muted sell-empty">No coins with available balance in this group.</p>`;
    return;
  }

  list.innerHTML = withBal
    .map((h) => {
      const checked = state.sellSelected.has(h.coin);
      const amt = state.sellAmounts[h.coin] || "";
      const locked = parseFloat(h.locked || 0);
      const balLabel =
        locked > 0
          ? `Balance: ${h.total} (${h.available} avail)`
          : `Balance: ${h.total || h.available}`;
      return `
      <div class="sell-coin-row ${checked ? "selected" : ""}" data-sell-coin="${h.coin}">
        <label class="sell-coin-check">
          <input type="checkbox" data-sell-check="${h.coin}" ${checked ? "checked" : ""} />
          ${coinAvatar(h.coin, "sm")}
          <strong>${h.coin}</strong>
        </label>
        <div class="sell-coin-bal muted">${balLabel}</div>
        <div class="sell-coin-val">${h.value_quote ? `≈ ${fmtNum(h.value_quote, 2)} ${group.quote}` : "—"}</div>
        <input type="number" class="sell-coin-amt" data-sell-amount="${h.coin}"
          placeholder="Full balance" min="0" step="any" value="${amt}" ${checked ? "" : "disabled"} />
      </div>`;
    })
    .join("");

  list.querySelectorAll("[data-sell-check]").forEach((inp) => {
    inp.addEventListener("change", () => {
      const coin = inp.dataset.sellCheck;
      if (inp.checked) state.sellSelected.add(coin);
      else {
        state.sellSelected.delete(coin);
        delete state.sellAmounts[coin];
      }
      renderSellCoinList(group);
      updateSellPreview();
    });
  });

  list.querySelectorAll("[data-sell-amount]").forEach((inp) => {
    inp.addEventListener("input", () => {
      const coin = inp.dataset.sellAmount;
      const v = inp.value.trim();
      if (v) state.sellAmounts[coin] = v;
      else delete state.sellAmounts[coin];
      clearTimeout(inp._sellTimer);
      inp._sellTimer = setTimeout(() => updateSellPreview(), 200);
    });
  });
}

function sellSelectAllWithBalance() {
  const group = state.groups.find((g) => g.id === state.activeSellGroupId);
  if (!group) return;
  (group.holdings || []).forEach((h) => {
    if (parseFloat(h.available || 0) > 0) state.sellSelected.add(h.coin);
  });
  renderSellCoinList(group);
  updateSellPreview();
}

function sellClearSelection() {
  const group = state.groups.find((g) => g.id === state.activeSellGroupId);
  state.sellSelected.clear();
  state.sellAmounts = {};
  if (group) renderSellCoinList(group);
  renderSellSplitPlaceholder();
}

function renderSellSplitPlaceholder(message = "Select coins above to preview sell amounts and what you receive.") {
  const group = state.groups.find((g) => g.id === state.activeSellGroupId);
  const quote = group?.quote || state.quote;
  const quoteBal = getQuoteBalanceFromPortfolio(quote);
  const box = $("#sell-split-preview");
  box.className = "split-preview split-preview-empty";
  box.innerHTML = `
    ${previewBalanceStripHtml(quote, quoteBal, null, {
      currentLabel: `${quote} balance`,
      afterLabel: `${quote} after sell`,
    })}
    <table class="split-table preview-balances-table">
      ${SELL_PREVIEW_COLS}
      <tbody>${sellBalanceRowsFromHoldings(group)}</tbody>
    </table>
    <p class="preview-hint">${message}</p>`;
  const btn = $("#sell-modal-confirm");
  if (btn) btn.disabled = true;
}

function renderSellSplitLoading() {
  const group = state.groups.find((g) => g.id === state.activeSellGroupId);
  const quote = group?.quote || state.quote;
  const quoteBal = getQuoteBalanceFromPortfolio(quote);
  const box = $("#sell-split-preview");
  box.className = "split-preview split-preview-loading";
  box.innerHTML = `
    ${previewBalanceStripHtml(quote, quoteBal, null, {
      currentLabel: `${quote} balance`,
      afterLabel: `${quote} after sell`,
    })}
    <table class="split-table preview-balances-table">
      ${SELL_PREVIEW_COLS}
      <tbody>${sellBalanceRowsFromHoldings(group, { pending: true })}</tbody>
    </table>
    <p class="preview-hint">Calculating sell preview…</p>`;
}

let sellPreviewAbort = null;
let sellPreviewSeq = 0;

function renderSellSplitPreview(preview) {
  const box = $("#sell-split-preview");
  const quote = preview.quote || state.quote;
  const breakdown = preview.breakdown || [];
  const total = parseFloat(preview.est_total_quote || 0);

  const rows = breakdown
    .map((row) => `
      <tr>
        <td class="split-coin">${coinAvatar(row.coin, "sm")}<strong>${row.coin}</strong></td>
        <td>${row.current_balance || row.available || "0"}</td>
        <td class="split-amt"><strong>${row.amount}</strong> <span class="muted">${row.coin}</span></td>
        <td class="split-col-get"><strong>${row.est_value_quote || "—"}</strong> <span class="muted">${quote}</span></td>
        <td>${row.balance_after || "—"}</td>
      </tr>`)
    .join("");

  const issues = preview.issues || [];
  const issuesBox =
    issues.length > 0
      ? `<div class="split-issues"><strong>Cannot sell:</strong><ul>${issues
          .map((i) => `<li>${i}</li>`)
          .join("")}</ul></div>`
      : "";

  const canSell = preview.can_sell !== false && issues.length === 0;
  const btn = $("#sell-modal-confirm");
  if (btn) btn.disabled = !canSell;

  const balanceStrip = previewBalanceStripHtml(
    quote,
    preview.quote_balance,
    preview.quote_balance_after,
    { currentLabel: `${quote} balance`, afterLabel: `${quote} after sell` }
  );

  box.className = "split-preview";
  box.innerHTML = `
    ${balanceStrip}
    <div class="split-preview-head">
      <div>
        <div class="split-preview-total">${fmtNum(total, 2)} ${quote}</div>
        <div class="split-preview-sub">estimated receive from ${breakdown.length} sell order(s)</div>
      </div>
      <div class="split-preview-mode sell-mode-badge">Sell preview</div>
    </div>
    <p class="split-preview-summary">${preview.summary_text || ""}</p>
    <table class="split-table">
      <thead>
        <tr>
          <th>Coin</th>
          <th>Current</th>
          <th>You sell</th>
          <th class="split-col-get">You get</th>
          <th>Coin after</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
      <tfoot>
        <tr>
          <td colspan="3" class="split-foot-label">Total you receive</td>
          <td class="split-col-get"><strong>${fmtNum(total, 2)}</strong> ${quote}</td>
          <td>—</td>
        </tr>
      </tfoot>
    </table>
    ${issuesBox}`;
}

async function updateSellPreview() {
  if (!state.activeSellGroupId || state.sellSelected.size === 0) {
    if (sellPreviewAbort) sellPreviewAbort.abort();
    renderSellSplitPlaceholder();
    return;
  }
  if (sellPreviewAbort) sellPreviewAbort.abort();
  sellPreviewAbort = new AbortController();
  const seq = ++sellPreviewSeq;
  renderSellSplitLoading();
  const coins = [...state.sellSelected];
  const amounts = {};
  coins.forEach((c) => {
    if (state.sellAmounts[c]) amounts[c] = state.sellAmounts[c];
  });
  try {
    const preview = await api(`/api/groups/${state.activeSellGroupId}/sell-preview`, {
      method: "POST",
      body: JSON.stringify({ coins, amounts: Object.keys(amounts).length ? amounts : undefined }),
      signal: sellPreviewAbort.signal,
    });
    if (seq !== sellPreviewSeq) return;
    renderSellSplitPreview(preview);
  } catch (e) {
    if (e.name === "AbortError") return;
    if (seq !== sellPreviewSeq) return;
    renderSellSplitPlaceholder(e.message);
  }
}

async function confirmSell() {
  if (!state.activeSellGroupId || state.sellSelected.size === 0) {
    toast("Select at least one coin to sell", "err");
    return;
  }
  const coins = [...state.sellSelected];
  const amounts = {};
  coins.forEach((c) => {
    if (state.sellAmounts[c]) amounts[c] = state.sellAmounts[c];
  });
  try {
    const res = await api(`/api/groups/${state.activeSellGroupId}/sell`, {
      method: "POST",
      body: JSON.stringify({
        coins,
        amounts: Object.keys(amounts).length ? amounts : undefined,
      }),
    });
    closeAllModals();
    toast(res.execution?.message || "Sell orders filled", "ok");
    await loadGroups();
    await loadPortfolio();
    if (state.activeTab === "history") await loadHistory();
  } catch (e) {
    toast(e.message, "err");
  }
}

function fmtTime(msOrSec) {
  if (!msOrSec) return "—";
  const n = Number(msOrSec);
  const ms = n > 1e12 ? n : n * 1000;
  try {
    return new Date(ms).toLocaleString();
  } catch {
    return "—";
  }
}

function sourceBadge(source) {
  if (source === "bot") {
    return `<span class="source-badge source-bot">BOT</span>`;
  }
  if (source === "website") {
    return `<span class="source-badge source-web">WEBSITE</span>`;
  }
  return `<span class="source-badge source-other">OTHER</span>`;
}

function renderHistory() {
  const rows = state.transactions;
  const tbody = $("#history-table tbody");
  const empty = $("#history-empty");
  $("#history-count").textContent = rows.length ? `${rows.length} shown` : "";

  if (!rows.length) {
    tbody.innerHTML = "";
    empty?.classList.remove("hidden");
    return;
  }
  empty?.classList.add("hidden");
  tbody.innerHTML = rows
    .map((t) => {
      const sideCls = t.side === "buy" ? "pos" : "neg";
      return `
      <tr class="${t.is_bot ? "row-bot" : ""}">
        <td class="muted">${fmtTime(t.create_time_ms || t.create_time)}</td>
        <td>${sourceBadge(t.source)}</td>
        <td><span class="${sideCls}">${(t.side || "").toUpperCase()}</span></td>
        <td>${coinAvatar(t.coin, "sm")} <strong>${t.coin}</strong></td>
        <td>${fmtNum(t.amount, 6)}</td>
        <td>${fmtNum(t.price, 4)}</td>
        <td>${t.value_quote ? fmtNum(t.value_quote, 2) : "—"} ${t.quote || state.quote}</td>
        <td class="muted">${t.fee ? `${t.fee} ${t.fee_currency || ""}` : "—"}</td>
      </tr>`;
    })
    .join("");
}

async function loadHistory() {
  setLoading("history", true);
  try {
    const filter = state.historyFilter || "all";
    const data = await api(
      `/api/transactions?source=${encodeURIComponent(filter)}&limit=50&page=1`
    );
    state.transactions = data.transactions || [];
    renderHistory();
    setStatus("history-status", `Loaded ${state.transactions.length} transactions`, "ok");
  } catch (e) {
    setStatus("history-status", e.message, "err");
    toast(e.message, "err");
  }
}

async function deleteGroup(id) {
  if (!confirm("Delete this group? (Does not sell coins)")) return;
  try {
    await api(`/api/groups/${id}`, { method: "DELETE" });
    toast("Group deleted", "ok");
    await loadGroups();
  } catch (e) {
    toast(e.message, "err");
  }
}

function selectAllVisible() {
  getFilteredMarkets().forEach((m) => state.selectedCoins.add(m.coin));
  renderMarkets();
}

function clearSelection() {
  state.selectedCoins.clear();
  renderMarkets();
}

function init() {
  bindAssetHoverTips();
  bindAssetClickHandlers();

  $$(".top-tab").forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });

  $$("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.goto));
  });

  $$("[data-close-modal]").forEach((el) => {
    el.addEventListener("click", closeAllModals);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAllModals();
  });

  $("#refresh-all-btn").addEventListener("click", async () => {
    const btn = $("#refresh-all-btn");
    btn.classList.add("spinning");
    try {
      await loadStatus();
      await loadPortfolio();
      await loadMarkets();
      await loadGroups();
      toast("Data refreshed", "ok");
    } finally {
      btn.classList.remove("spinning");
    }
  });

  $("#market-search").addEventListener("input", (e) => {
    state.marketFilter = e.target.value;
    renderMarkets();
  });

  $("#select-all-btn").addEventListener("click", selectAllVisible);
  $("#clear-select-btn").addEventListener("click", clearSelection);
  $("#create-group-btn").addEventListener("click", openGroupModal);
  $("#selection-bar-create").addEventListener("click", openGroupModal);
  $("#group-modal-save").addEventListener("click", saveGroup);
  $("#alloc-modal-save").addEventListener("click", saveAllocations);
  $("#alloc-modal")?.addEventListener("input", (e) => {
    if (e.target.matches("[data-alloc-coin]")) updateAllocSumHint();
  });

  let buyPreviewTimer = null;
  $("#buy-amount-input").addEventListener("input", () => {
    clearTimeout(buyPreviewTimer);
    buyPreviewTimer = setTimeout(() => updateBuyPreview(), 200);
  });
  $("#buy-modal-confirm").addEventListener("click", confirmBuy);
  $("#sell-modal-confirm").addEventListener("click", confirmSell);
  $("#sell-select-all-btn").addEventListener("click", sellSelectAllWithBalance);
  $("#sell-clear-btn").addEventListener("click", sellClearSelection);
  $("#history-filter").addEventListener("change", (e) => {
    state.historyFilter = e.target.value;
    loadHistory();
  });
  $("#history-refresh-btn").addEventListener("click", () => loadHistory());

  const portfolioHero = $("#portfolio-hero");
  portfolioHero?.addEventListener("click", () => openPortfolioAnalysisModal());
  portfolioHero?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openPortfolioAnalysisModal();
    }
  });
  $("#inr-display-toggle")?.addEventListener("change", async (e) => {
    if (e.target.checked && !state.inrRate) await loadInrRate();
    applyInrDisplay(e.target.checked);
    if (e.target.checked && !state.inrRate) {
      toast("INR rate unavailable — add INR_PER_USDT=85 in .env", "err");
    }
  });

  $("#edit-coins-save").addEventListener("click", saveEditCoins);
  $("#edit-coins-select-visible").addEventListener("click", selectAllEditCoinsVisible);
  $("#edit-coins-clear").addEventListener("click", clearEditCoinsSelection);
  $("#edit-coins-search")?.addEventListener("input", (e) => {
    state.editCoinsFilter = e.target.value;
    renderEditCoinsList();
  });

  loadStatus()
    .then((ok) => (ok ? loadPortfolio() : null))
    .catch((e) => {
      showError(e.message);
      toast(e.message, "err");
    });
}

try {
  init();
} catch (e) {
  showError("Dashboard failed to start: " + e.message);
}
