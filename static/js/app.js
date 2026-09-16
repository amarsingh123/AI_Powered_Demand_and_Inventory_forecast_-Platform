// ================================================================== CORE HELPERS
const API = "";
const charts = {};

async function api(path, opts) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = j.detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return res.json();
}

function money(n, compact = false) {
  n = Number(n) || 0;
  if (compact) {
    if (Math.abs(n) >= 1e6) return "₹" + (n / 1e6).toFixed(2) + "M";
    if (Math.abs(n) >= 1e3) return "₹" + (n / 1e3).toFixed(1) + "K";
    return "₹" + n.toFixed(0);
  }
  return "₹" + n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function num(n) { return Number(n).toLocaleString("en-US"); }

function toast(msg, type = "") {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast show" + (type ? " " + type : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.className = "toast"; }, 3200);
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function destroyChart(id) {
  if (charts[id]) { charts[id].destroy(); delete charts[id]; }
}

function chartTheme() {
  return {
    text: cssVar("--text-muted"),
    grid: cssVar("--border"),
    accent: cssVar("--accent"),
    accent2: cssVar("--accent-2"),
    success: cssVar("--success"),
    danger: cssVar("--danger"),
    warning: cssVar("--warning"),
    info: cssVar("--info"),
  };
}

function baseChartOptions(extra = {}) {
  const t = chartTheme();
  return Chart.helpers.mergeIf(extra, {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { labels: { color: t.text, usePointStyle: true, boxWidth: 8, font: { size: 11.5 } } },
      tooltip: {
        backgroundColor: cssVar("--card-bg"), titleColor: cssVar("--text"), bodyColor: cssVar("--text-muted"),
        borderColor: cssVar("--border"), borderWidth: 1, padding: 10, cornerRadius: 8,
      },
    },
    scales: {
      x: { ticks: { color: t.text, font: { size: 11 } }, grid: { color: t.grid, display: false } },
      y: { ticks: { color: t.text, font: { size: 11 } }, grid: { color: t.grid } },
    },
  });
}

const PALETTE = ["#7c6cf6", "#3b82f6", "#22c55e", "#eab308", "#ef4444", "#a06cf9", "#06b6d4", "#f97316"];

// ================================================================== THEME
function initTheme() {
  const saved = localStorage.getItem("salesiq-theme") || "dark";
  setTheme(saved);
  document.getElementById("themeToggle").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    setTheme(cur === "dark" ? "light" : "dark");
    rerenderActiveCharts();
  });
}
function setTheme(mode) {
  document.documentElement.setAttribute("data-theme", mode);
  localStorage.setItem("salesiq-theme", mode);
  document.getElementById("themeIcon").textContent = mode === "dark" ? "🌙" : "☀️";
  document.querySelector("#themeToggle .tt-label").textContent = mode === "dark" ? "Dark mode" : "Light mode";
}
function rerenderActiveCharts() {
  // theme colors changed -> reload whichever view is currently visible
  const active = document.querySelector(".view.active");
  if (active) loadView(active.id.replace("view-", ""), true);
}

// ================================================================== SIDEBAR / NAV
function initSidebarNav() {
  document.getElementById("collapseBtn").addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("collapsed");
  });
  document.getElementById("mobileMenuBtn").addEventListener("click", () => {
    document.getElementById("sidebar").classList.add("mobile-open");
    document.getElementById("backdrop").classList.add("show");
  });
  document.getElementById("backdrop").addEventListener("click", closeMobileSidebar);
  document.getElementById("signOutBtn").addEventListener("click", () => toast("This is a demo — sign-out isn't wired to a backend session."));

  document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach(i => i.classList.remove("active"));
      item.classList.add("active");
      const view = item.dataset.view;
      document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
      document.getElementById("view-" + view).classList.add("active");
      closeMobileSidebar();
      loadView(view);
    });
  });
}
function closeMobileSidebar() {
  document.getElementById("sidebar").classList.remove("mobile-open");
  document.getElementById("backdrop").classList.remove("show");
}

const loadedOnce = new Set();
function loadView(view, force = false) {
  if (loadedOnce.has(view) && !force) {
    // still refresh charts cheaply from cached DOM? simplest: just reload data each visit
  }
  loadedOnce.add(view);
  const fns = {
    dashboard: loadDashboard,
    forecasting: () => {}, // user-triggered via Run Forecast button
    segments: loadSegments,
    recommendations: loadRecommendationsView,
    inventory: loadInventoryOverview,
    alerts: loadAlerts,
    admin: loadAdmin,
  };
  (fns[view] || (() => {}))();
}

// ================================================================== TABS (generic)
function initTabs(scopeSelector) {
  document.querySelectorAll(scopeSelector + " .tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const group = btn.closest(".view");
      group.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      group.querySelectorAll("[id^='tab-']").forEach(panel => {
        panel.style.display = panel.id === "tab-" + tab ? "" : "none";
      });
    });
  });
}

// ================================================================== DASHBOARD
async function loadDashboard() {
  const period = document.getElementById("dashPeriod").value;
  let data;
  try { data = await api(`/api/dashboard?period=${period}`); }
  catch (e) { toast("Failed to load dashboard: " + e.message, "error"); return; }

  const k = data.kpis;
  const kpiHtml = `
    <div class="kpi-card"><div class="kpi-label">💰 Revenue</div><div class="kpi-value">${money(k.revenue, true)}</div>
      <div class="kpi-delta ${k.revenue_change_pct >= 0 ? "up" : "down"}">${k.revenue_change_pct >= 0 ? "↑" : "↓"} ${Math.abs(k.revenue_change_pct)}% vs prev period</div></div>
    <div class="kpi-card"><div class="kpi-label">🧾 Orders</div><div class="kpi-value">${num(k.orders)}</div>
      <div class="kpi-delta ${k.orders_change_pct >= 0 ? "up" : "down"}">${k.orders_change_pct >= 0 ? "↑" : "↓"} ${Math.abs(k.orders_change_pct)}% vs prev period</div></div>
    <div class="kpi-card"><div class="kpi-label">👤 Customers</div><div class="kpi-value">${num(k.customers)}</div></div>
    <div class="kpi-card"><div class="kpi-label">🏷️ Avg Order Value</div><div class="kpi-value">${money(k.aov, true)}</div></div>
  `;
  document.getElementById("dashKpis").innerHTML = kpiHtml;

  const t = chartTheme();
  destroyChart("dailyTrend");
  charts.dailyTrend = new Chart(document.getElementById("chartDailyTrend"), {
    type: "line",
    data: {
      labels: data.daily_trend.map(d => d.date.slice(5)),
      datasets: [
        { label: "Revenue", data: data.daily_trend.map(d => d.revenue), borderColor: t.accent,
          backgroundColor: t.accent + "22", fill: true, tension: 0.35, pointRadius: 0, borderWidth: 2 },
        { label: "7-Day MA", data: data.daily_trend.map(d => d.ma7), borderColor: t.warning,
          borderDash: [5, 4], pointRadius: 0, borderWidth: 1.8, fill: false, tension: 0.35 },
      ],
    },
    options: baseChartOptions(),
  });

  destroyChart("revByCat");
  const cats = data.revenue_by_category;
  charts.revByCat = new Chart(document.getElementById("chartRevByCategory"), {
    type: "doughnut",
    data: { labels: cats.map(c => c.category), datasets: [{ data: cats.map(c => c.revenue), backgroundColor: PALETTE, borderWidth: 0 }] },
    options: { responsive: true, maintainAspectRatio: false, cutout: "62%",
      plugins: { legend: { position: "right", labels: { color: t.text, usePointStyle: true, boxWidth: 8, font: { size: 11 } } } } },
  });
}

// ================================================================== SALES FORECASTING
function initForecasting() {
  document.getElementById("fcHorizon").addEventListener("input", e => {
    document.getElementById("fcHorizonVal").textContent = e.target.value;
  });
  document.getElementById("fcRunBtn").addEventListener("click", runForecast);
}

async function runForecast() {
  const btn = document.getElementById("fcRunBtn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Running...';
  try {
    const body = {
      model: document.getElementById("fcModel").value,
      horizon: Number(document.getElementById("fcHorizon").value),
      history_days: Number(document.getElementById("fcHistory").value),
    };
    const data = await api("/api/forecast/run", { method: "POST", body: JSON.stringify(body) });
    renderForecast(data);
    document.getElementById("fcResults").style.display = "";
    document.getElementById("fcEmpty").style.display = "none";
  } catch (e) {
    toast("Forecast failed: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = "🚀 Run Forecast";
  }
}

function renderForecast(data) {
  const m = data.metrics;
  document.getElementById("fcMetrics").innerHTML = `
    <div class="kpi-card"><div class="kpi-label">MAE</div><div class="kpi-value">${money(m.mae)}</div></div>
    <div class="kpi-card"><div class="kpi-label">RMSE</div><div class="kpi-value">${money(m.rmse)}</div></div>
    <div class="kpi-card"><div class="kpi-label">R²</div><div class="kpi-value">${m.r2}</div></div>
  `;

  const t = chartTheme();
  destroyChart("forecast");
  const histLabels = data.history.map(h => h.date.slice(5));
  const fcLabels = data.forecast.map(f => f.date.slice(5));
  const allLabels = [...histLabels, ...fcLabels];
  const histData = data.history.map(h => h.revenue);
  const fcDataPadded = new Array(histLabels.length - 1).fill(null).concat([histData[histData.length - 1]], data.forecast.map(f => f.forecast));

  charts.forecast = new Chart(document.getElementById("chartForecast"), {
    type: "line",
    data: {
      labels: allLabels,
      datasets: [
        { label: "Actual Revenue", data: [...histData, ...new Array(fcLabels.length).fill(null)],
          borderColor: t.accent, backgroundColor: "transparent", pointRadius: 0, borderWidth: 2, tension: 0.3 },
        { label: "Forecast", data: fcDataPadded, borderColor: t.success, borderDash: [4, 3],
          backgroundColor: t.success + "18", fill: true, pointRadius: 0, borderWidth: 2, tension: 0.3 },
      ],
    },
    options: baseChartOptions(),
  });

  document.getElementById("fcTableBody").innerHTML = data.forecast.map(f =>
    `<tr><td>${f.date}</td><td>${money(f.forecast)}</td></tr>`).join("");

  destroyChart("featImp");
  const imp = data.feature_importance;
  charts.featImp = new Chart(document.getElementById("chartFeatureImportance"), {
    type: "bar",
    data: { labels: imp.map(i => i.feature), datasets: [{ data: imp.map(i => i.importance), backgroundColor: t.accent, borderRadius: 4 }] },
    options: baseChartOptions({ indexAxis: "y", plugins: { legend: { display: false } },
      scales: { x: { ticks: { color: t.text }, grid: { color: t.grid } }, y: { ticks: { color: t.text, font: { size: 10.5 } }, grid: { display: false } } } }),
  });
}

// ================================================================== CUSTOMER SEGMENTS
function initSegments() {
  document.getElementById("segK").addEventListener("change", loadSegments);
  document.getElementById("segK").addEventListener("input", e => {
    document.getElementById("segKVal").textContent = e.target.value;
  });
}

const SEG_COLORS = {
  "Champions": "#3b82f6", "Loyal Customers": "#22c55e", "At Risk": "#eab308",
  "Lost Customers": "#ef4444", "New Customers": "#7c6cf6", "Occasional Buyers": "#06b6d4",
};
const SEG_ICONS = {
  "Champions": "💎", "Loyal Customers": "🔥", "At Risk": "🌱", "Lost Customers": "👋",
  "New Customers": "✨", "Occasional Buyers": "🕓",
};

async function loadSegments() {
  const k = document.getElementById("segK").value;
  let data;
  try { data = await api(`/api/segments?k=${k}`); }
  catch (e) { toast("Failed to load segments: " + e.message, "error"); return; }

  document.getElementById("segGrid").innerHTML = data.overview.map(s => {
    const color = SEG_COLORS[s.segment] || "#7c6cf6";
    return `
    <div class="seg-card" style="border-color:${color}55;">
      <div class="seg-icon">${SEG_ICONS[s.segment] || "👥"}</div>
      <div style="font-weight:700;font-size:14px;color:${color};">${s.segment}</div>
      <div class="seg-count">${num(s.customers)}</div>
      <div class="seg-count-label">customers</div>
      <div class="seg-stat"><span>Avg Recency</span><span>${s.avg_recency}d</span></div>
      <div class="seg-stat"><span>Avg Orders</span><span>${s.avg_frequency}</span></div>
      <div class="seg-stat"><span>Avg Spend</span><span>${money(s.avg_monetary)}</span></div>
    </div>`;
  }).join("");

  const t = chartTheme();
  destroyChart("clusterMap");
  const bySeg = {};
  data.cluster_map.forEach(p => { (bySeg[p.segment] = bySeg[p.segment] || []).push(p); });
  const datasets = Object.keys(bySeg).map(seg => ({
    label: seg,
    data: bySeg[seg].map(p => ({ x: p.pc1, y: p.pc2 })),
    backgroundColor: (SEG_COLORS[seg] || "#7c6cf6") + "cc",
    pointRadius: 4,
  }));
  charts.clusterMap = new Chart(document.getElementById("chartClusterMap"), {
    type: "scatter",
    data: { datasets },
    options: baseChartOptions({ scales: {
      x: { title: { display: true, text: "PC1", color: t.text }, ticks: { color: t.text }, grid: { color: t.grid } },
      y: { title: { display: true, text: "PC2", color: t.text }, ticks: { color: t.text }, grid: { color: t.grid } },
    } }),
  });

  destroyChart("revBySeg");
  const rev = data.revenue_by_segment;
  charts.revBySeg = new Chart(document.getElementById("chartRevBySegment"), {
    type: "bar",
    data: { labels: rev.map(r => r.segment), datasets: [{ data: rev.map(r => r.revenue),
      backgroundColor: rev.map(r => SEG_COLORS[r.segment] || "#7c6cf6"), borderRadius: 6 }] },
    options: baseChartOptions({ plugins: { legend: { display: false } } }),
  });
}

// ================================================================== RECOMMENDATIONS
let recoN = 5, simN = 5;

function initRecommendations() {
  initTabs("#view-recommendations");
  document.getElementById("recoNMinus").addEventListener("click", () => { recoN = Math.max(1, recoN - 1); document.getElementById("recoNVal").textContent = recoN; });
  document.getElementById("recoNPlus").addEventListener("click", () => { recoN = Math.min(10, recoN + 1); document.getElementById("recoNVal").textContent = recoN; });
  document.getElementById("simNMinus").addEventListener("click", () => { simN = Math.max(1, simN - 1); document.getElementById("simNVal").textContent = simN; });
  document.getElementById("simNPlus").addEventListener("click", () => { simN = Math.min(10, simN + 1); document.getElementById("simNVal").textContent = simN; });
  document.getElementById("recoGetBtn").addEventListener("click", getCustomerRecommendations);
  document.getElementById("simGetBtn").addEventListener("click", getSimilarProducts);
}

async function loadRecommendationsView() {
  try {
    const [customers, products] = await Promise.all([api("/api/customers"), api("/api/products")]);
    const custSel = document.getElementById("recoCustomerSelect");
    custSel.innerHTML = customers.map(c => `<option value="${c.customer_id}">${c.name} (ID: ${c.customer_id})</option>`).join("");
    const prodSel = document.getElementById("simProductSelect");
    prodSel.innerHTML = products.map(p => `<option value="${p.product_id}">${p.name} (${p.category})</option>`).join("");
    if (customers.length) updatePurchasedNote(customers[0]);
    custSel.addEventListener("change", () => {
      const c = customers.find(x => String(x.customer_id) === custSel.value);
      if (c) updatePurchasedNote(c);
    });
  } catch (e) {
    toast("Failed to load recommendation data: " + e.message, "error");
  }
}
function updatePurchasedNote(c) {
  document.getElementById("recoPurchasedNote").textContent = `Previously purchased ${c.unique_products} unique product${c.unique_products === 1 ? "" : "s"}.`;
}

async function getCustomerRecommendations() {
  const custId = document.getElementById("recoCustomerSelect").value;
  if (!custId) return;
  const btn = document.getElementById("recoGetBtn");
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Loading...';
  try {
    const data = await api(`/api/recommendations/customer?customer_id=${custId}&n=${recoN}`);
    document.getElementById("recoTitle").textContent = `🎁 Top ${data.recommendations.length} Recommendations`;
    renderRecoCards("recoGrid", data.recommendations);
    renderRecoScoresChart(data.recommendations);
  } catch (e) {
    toast("Could not fetch recommendations: " + e.message, "error");
  } finally {
    btn.disabled = false; btn.innerHTML = "✨ Get Recommendations";
  }
}

function renderRecoCards(containerId, items) {
  const el = document.getElementById(containerId);
  if (!items.length) { el.innerHTML = `<div class="empty-state">No recommendations found for this selection.</div>`; return; }
  el.innerHTML = items.map(r => `
    <div class="reco-card">
      <div class="reco-name">${r.name}</div>
      <div class="reco-cat">${r.category}</div>
      <div class="reco-price">${money(r.price)}</div>
      <div class="reco-score">Match score: ${r.match_score}</div>
    </div>`).join("");
}

function renderRecoScoresChart(items) {
  document.getElementById("recoScoresTitle").style.display = items.length ? "" : "none";
  document.getElementById("recoScoresBox").style.display = items.length ? "" : "none";
  if (!items.length) return;
  const t = chartTheme();
  destroyChart("recoScores");
  charts.recoScores = new Chart(document.getElementById("chartRecoScores"), {
    type: "bar",
    data: { labels: items.map(i => i.name), datasets: [{ data: items.map(i => i.match_score), backgroundColor: t.accent2, borderRadius: 6 }] },
    options: baseChartOptions({ plugins: { legend: { display: false } } }),
  });
}

async function getSimilarProducts() {
  const prodId = document.getElementById("simProductSelect").value;
  if (!prodId) return;
  const btn = document.getElementById("simGetBtn");
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Loading...';
  try {
    const data = await api(`/api/recommendations/similar?product_id=${prodId}&n=${simN}`);
    renderRecoCards("simGrid", data.recommendations);
  } catch (e) {
    toast("Could not fetch similar products: " + e.message, "error");
  } finally {
    btn.disabled = false; btn.innerHTML = "✨ Find Similar";
  }
}

// ================================================================== INVENTORY & DEMAND
function initInventory() {
  initTabs("#view-inventory");
  document.getElementById("invDays").addEventListener("input", e => { document.getElementById("invDaysVal").textContent = e.target.value; });
  document.getElementById("invForecastBtn").addEventListener("click", runInventoryForecast);
}

async function loadInventoryOverview() {
  let data;
  try { data = await api("/api/inventory/overview"); }
  catch (e) { toast("Failed to load inventory: " + e.message, "error"); return; }

  document.getElementById("invKpis").innerHTML = `
    <div class="kpi-card"><div class="kpi-label">📦 Total Products</div><div class="kpi-value">${num(data.total_products)}</div></div>
    <div class="kpi-card"><div class="kpi-label">💵 Inventory Value</div><div class="kpi-value">${money(data.inventory_value)}</div></div>
    <div class="kpi-card"><div class="kpi-label">⚠️ Low Stock (&lt;10)</div><div class="kpi-value">${num(data.low_stock_count)}</div>
      <div class="kpi-sub">${data.low_stock_count} need${data.low_stock_count === 1 ? "s" : ""} restock</div></div>
    <div class="kpi-card"><div class="kpi-label">🚫 Out of Stock</div><div class="kpi-value">${num(data.out_of_stock_count)}</div></div>
  `;

  const t = chartTheme();
  destroyChart("lowStock");
  const ls = data.low_stock_products;
  if (ls.length) {
    charts.lowStock = new Chart(document.getElementById("chartLowStock"), {
      type: "bar",
      data: { labels: ls.map(p => p.name), datasets: [{ label: "Units left", data: ls.map(p => p.stock),
        backgroundColor: ls.map(p => p.stock <= 5 ? t.danger : t.warning), borderRadius: 6 }] },
      options: baseChartOptions({ indexAxis: "y", plugins: { legend: { display: false } } }),
    });
    document.getElementById("chartLowStock").style.display = "";
  } else {
    document.getElementById("chartLowStock").parentElement.innerHTML = `<div class="empty-state">No products below the low-stock threshold. 🎉</div>`;
  }

  const catData = data.stock_by_category;
  const maxV = Math.max(...catData.map(c => c.value), 1);
  const tm = document.getElementById("treemap");
  const cols = Math.min(4, catData.length);
  tm.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  tm.style.gridAutoRows = "1fr";
  tm.innerHTML = catData.map((c, i) => {
    const intensity = 0.35 + 0.65 * (c.value / maxV);
    return `<div class="treemap-tile" style="background:${PALETTE[i % PALETTE.length]}; opacity:${intensity.toFixed(2)};">
      ${c.category}<span class="tt-val">${money(c.value, true)}</span></div>`;
  }).join("");
}

async function runInventoryForecast() {
  const productId = document.getElementById("invProductSelect").value;
  if (!productId) return;
  const btn = document.getElementById("invForecastBtn");
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Forecasting...';
  try {
    const body = {
      product_id: Number(productId),
      days: Number(document.getElementById("invDays").value),
      model: document.getElementById("invModel").value,
    };
    const data = await api("/api/inventory/forecast", { method: "POST", body: JSON.stringify(body) });
    renderInventoryForecast(data, body.days);
    document.getElementById("invResults").style.display = "";
    document.getElementById("invEmpty").style.display = "none";
  } catch (e) {
    toast("Demand forecast failed: " + e.message, "error");
  } finally {
    btn.disabled = false; btn.innerHTML = "📈 Forecast Demand";
  }
}

function renderInventoryForecast(data, days) {
  document.getElementById("invMetrics").innerHTML = `
    <div class="kpi-card"><div class="kpi-label">📦 Current Stock</div><div class="kpi-value">${num(data.current_stock)} units</div></div>
    <div class="kpi-card"><div class="kpi-label">🔮 Predicted Demand (${days}d)</div><div class="kpi-value">${num(Math.round(data.predicted_demand))} units</div></div>
    <div class="kpi-card"><div class="kpi-label">📊 Stock Coverage</div><div class="kpi-value">${data.coverage_days >= 999 ? "999+" : data.coverage_days} days</div>
      <div class="kpi-delta ${data.sufficient ? "up" : "down"}">${data.sufficient ? "↑ Sufficient" : "↓ Restock soon"}</div></div>
  `;
  document.getElementById("invMaeNote").textContent = `Model MAE: ${data.model_mae} units/day`;
  document.getElementById("invChartTitle").textContent = `📈 ${data.product.name} (${data.product.category}) — Demand Forecast`;

  const t = chartTheme();
  destroyChart("invForecast");
  const histLabels = data.history.map(h => h.date.slice(5));
  const fcLabels = data.forecast.map(f => f.date.slice(5));
  const allLabels = [...histLabels, ...fcLabels];
  const histQty = data.history.map(h => h.qty);
  const fcPadded = new Array(histLabels.length - 1).fill(null).concat([histQty[histQty.length - 1]], data.forecast.map(f => f.qty));
  const remainingPadded = new Array(histLabels.length).fill(null).concat(data.est_remaining_stock.map(r => r.remaining));

  charts.invForecast = new Chart(document.getElementById("chartInvForecast"), {
    type: "line",
    data: {
      labels: allLabels,
      datasets: [
        { label: "Historical Demand", data: [...histQty, ...new Array(fcLabels.length).fill(null)],
          type: "bar", backgroundColor: t.accent + "99", borderRadius: 3, yAxisID: "y" },
        { label: "Predicted Demand", data: fcPadded, borderColor: t.success, backgroundColor: "transparent",
          pointRadius: 2, borderWidth: 2, tension: 0.3, yAxisID: "y" },
        { label: "Est. Remaining Stock", data: remainingPadded, borderColor: t.warning, borderDash: [3, 3],
          backgroundColor: "transparent", pointRadius: 0, borderWidth: 1.8, yAxisID: "y1" },
      ],
    },
    options: baseChartOptions({
      scales: {
        x: { ticks: { color: t.text }, grid: { display: false } },
        y: { position: "left", title: { display: true, text: "Units", color: t.text }, ticks: { color: t.text }, grid: { color: t.grid } },
        y1: { position: "right", title: { display: true, text: "Remaining Stock", color: t.text }, ticks: { color: t.text }, grid: { display: false } },
      },
    }),
  });
}

async function loadInventoryProductSelect() {
  try {
    const products = await api("/api/products");
    document.getElementById("invProductSelect").innerHTML = products.map(p => `<option value="${p.product_id}">${p.name} (${p.category}) [Stock: ${p.stock}]</option>`).join("");
  } catch (e) { /* handled elsewhere */ }
}

// ================================================================== KPI ALERTS
function initAlerts() {
  document.getElementById("alertRunBtn").addEventListener("click", loadAlerts);
  document.getElementById("alertDays").addEventListener("change", loadAlerts);
  document.getElementById("alertShowResolved").addEventListener("change", loadAlerts);
}

async function loadAlerts() {
  const btn = document.getElementById("alertRunBtn");
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Checking...';
  const days = document.getElementById("alertDays").value;
  const resolved = document.getElementById("alertShowResolved").checked;
  try {
    const data = await api(`/api/alerts?days=${days}&show_resolved=${resolved}`);
    renderAlerts(data);
  } catch (e) {
    toast("Failed to run KPI check: " + e.message, "error");
  } finally {
    btn.disabled = false; btn.innerHTML = "🔎 Run KPI Check";
  }
}

function renderAlerts(data) {
  const s = data.summary;
  document.getElementById("alertSummary").innerHTML = `
    <div class="kpi-card"><div class="kpi-label">📋 Total Alerts</div><div class="kpi-value">${s.total}</div></div>
    <div class="kpi-card"><div class="kpi-label">🔴 Critical</div><div class="kpi-value" style="color:var(--danger)">${s.critical}</div></div>
    <div class="kpi-card"><div class="kpi-label">🟡 Warnings</div><div class="kpi-value" style="color:var(--warning)">${s.warnings}</div></div>
    <div class="kpi-card"><div class="kpi-label">🟢 Resolved</div><div class="kpi-value" style="color:var(--success)">${s.resolved}</div></div>
  `;

  const t = chartTheme();
  destroyChart("alertTrend");
  charts.alertTrend = new Chart(document.getElementById("chartAlertTrend"), {
    type: "bar",
    data: { labels: data.trend.map(d => d.date.slice(5)), datasets: [{ label: "Alerts", data: data.trend.map(d => d.count), backgroundColor: t.danger, borderRadius: 4 }] },
    options: baseChartOptions({ plugins: { legend: { display: false } } }),
  });

  destroyChart("alertDist");
  const dist = data.type_distribution;
  if (dist.length) {
    charts.alertDist = new Chart(document.getElementById("chartAlertDist"), {
      type: "doughnut",
      data: { labels: dist.map(d => d.type), datasets: [{ data: dist.map(d => d.count), backgroundColor: PALETTE, borderWidth: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: "60%",
        plugins: { legend: { position: "right", labels: { color: t.text, usePointStyle: true, boxWidth: 8 } } } },
    });
  } else {
    document.getElementById("chartAlertDist").parentElement.innerHTML = `<div class="empty-state">No alerts to distribute. 🎉</div>`;
  }

  const list = document.getElementById("alertsList");
  if (!data.alerts.length) {
    list.innerHTML = `<div class="empty-state">No active alerts in this window. Everything looks healthy. ✅</div>`;
  } else {
    list.innerHTML = data.alerts.map(a => `
      <div class="alert-row">
        <div class="alert-dot ${a.severity}"></div>
        <div class="alert-body">
          <div class="alert-type">${a.type} <span class="badge badge-${a.severity}">${a.severity}</span></div>
          <div class="alert-msg">${a.message}</div>
          <div class="alert-date">${a.date}</div>
        </div>
      </div>`).join("");
  }
}

// ================================================================== ADMIN PANEL
function initAdmin() {
  initTabs("#view-admin");
  document.getElementById("createUserBtn").addEventListener("click", createUser);
}

async function loadAdmin() {
  try {
    const users = await api("/api/admin/users");
    renderUsersTable(users);
    const stats = await api("/api/admin/stats");
    document.getElementById("adminStatsGrid").innerHTML = `
      <div class="kpi-card"><div class="kpi-label">👥 Users</div><div class="kpi-value">${num(stats.users)}</div></div>
      <div class="kpi-card"><div class="kpi-label">🧑‍🤝‍🧑 Customers</div><div class="kpi-value">${num(stats.customers)}</div></div>
      <div class="kpi-card"><div class="kpi-label">📦 Products</div><div class="kpi-value">${num(stats.products)}</div></div>
      <div class="kpi-card"><div class="kpi-label">🧾 Orders</div><div class="kpi-value">${num(stats.orders)}</div></div>
      <div class="kpi-card"><div class="kpi-label">📅 Days of History</div><div class="kpi-value">${num(stats.days_of_history)}</div></div>
      <div class="kpi-card"><div class="kpi-label">💰 Total Revenue</div><div class="kpi-value">${money(stats.total_revenue, true)}</div></div>
    `;
  } catch (e) {
    toast("Failed to load admin data: " + e.message, "error");
  }
}

function renderUsersTable(users) {
  document.getElementById("usersTableBody").innerHTML = users.map(u => `
    <tr><td>${u.username}</td><td><span class="badge ${u.role === "Admin" ? "badge-admin" : "badge-manager"}">${u.role}</span></td><td>${u.created_at}</td></tr>
  `).join("");
}

async function createUser() {
  const username = document.getElementById("newUsername").value.trim();
  const password = document.getElementById("newPassword").value;
  const role = document.getElementById("newRole").value;
  if (!username || !password) { toast("Username and password are required", "error"); return; }
  const btn = document.getElementById("createUserBtn");
  btn.disabled = true;
  try {
    const res = await api("/api/admin/users", { method: "POST", body: JSON.stringify({ username, password, role }) });
    renderUsersTable(res.users);
    document.getElementById("newUsername").value = "";
    document.getElementById("newPassword").value = "";
    toast(`User "${username}" created`, "success");
  } catch (e) {
    toast("Could not create user: " + e.message, "error");
  } finally {
    btn.disabled = false;
  }
}

// ================================================================== BOOTSTRAP
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initSidebarNav();
  initForecasting();
  initSegments();
  initRecommendations();
  initInventory();
  initAlerts();
  initAdmin();

  document.getElementById("dashPeriod").addEventListener("change", loadDashboard);

  loadDashboard();
  loadInventoryProductSelect();
});
