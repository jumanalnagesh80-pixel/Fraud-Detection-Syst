/* ============================================================
   Sentinel Dashboard - frontend logic
   - Polls /api/metrics, /api/transactions, /api/alerts
   - Renders Chart.js charts and live tables
   - Handles "Run Simulation" and manual scoring form
   ============================================================ */

const API = {
  metrics: '/api/metrics',
  transactions: '/api/transactions?limit=20',
  alerts: '/api/alerts?limit=15',
  modelInfo: '/api/model/info',
  simulate: '/api/simulate',
  predict: '/api/predict',
  health: '/api/health',
};

const POLL_MS = 3000;
const COLORS = {
  blue: '#3b82f6', red: '#ef4444', green: '#10b981',
  orange: '#f97316', amber: '#f59e0b', violet: '#8b5cf6',
  pink: '#ec4899', cyan: '#06b6d4', teal: '#14b8a6',
  slate: 'rgba(148, 163, 184, 0.4)',
};

Chart.defaults.color = '#93a4c8';
Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.borderColor = 'rgba(148, 163, 184, 0.12)';

let charts = {};
let knownTxnIds = new Set();
let lastTxnCount = 0;
let lastTimestamp = Date.now();

// ============================================================
// CHARTS
// ============================================================
function buildCharts() {
  // Hourly volume (mixed: bars for total, line for fraud)
  charts.hourly = new Chart(document.getElementById('chart-hourly'), {
    type: 'bar',
    data: {
      labels: Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, '0')}h`),
      datasets: [
        {
          label: 'Total',
          data: Array(24).fill(0),
          backgroundColor: gradientFor('chart-hourly', COLORS.blue),
          borderRadius: 6,
          borderSkipped: false,
          maxBarThickness: 22,
          order: 2,
        },
        {
          label: 'Fraud',
          type: 'line',
          data: Array(24).fill(0),
          borderColor: COLORS.red,
          backgroundColor: 'rgba(239, 68, 68, 0.15)',
          tension: 0.35,
          fill: true,
          pointRadius: 3,
          pointBackgroundColor: COLORS.red,
          borderWidth: 2,
          order: 1,
        },
      ],
    },
    options: chartBaseOpts({ legend: false }),
  });

  // Risk distribution (doughnut)
  charts.risk = new Chart(document.getElementById('chart-risk'), {
    type: 'doughnut',
    data: {
      labels: ['Low', 'Medium', 'High', 'Critical'],
      datasets: [{
        data: [0, 0, 0, 0],
        backgroundColor: [COLORS.green, COLORS.amber, COLORS.orange, COLORS.red],
        borderColor: 'rgba(10, 15, 31, 0.9)',
        borderWidth: 3,
        hoverOffset: 8,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '68%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: { padding: 14, usePointStyle: true, pointStyle: 'circle', boxWidth: 8 },
        },
        tooltip: tooltipStyle(),
      },
    },
  });

  // Top fraud categories (horizontal bar)
  charts.categories = new Chart(document.getElementById('chart-categories'), {
    type: 'bar',
    data: { labels: [], datasets: [{
      label: 'Fraud count',
      data: [],
      backgroundColor: gradientFor('chart-categories', COLORS.pink),
      borderRadius: 6,
      borderSkipped: false,
      maxBarThickness: 22,
    }]},
    options: {
      ...chartBaseOpts({ legend: false }),
      indexAxis: 'y',
    },
  });

  // Feature importance (radar / bar)
  charts.features = new Chart(document.getElementById('chart-features'), {
    type: 'bar',
    data: { labels: [], datasets: [{
      label: 'Importance',
      data: [],
      backgroundColor: gradientFor('chart-features', COLORS.violet),
      borderRadius: 6,
      borderSkipped: false,
      maxBarThickness: 22,
    }]},
    options: chartBaseOpts({ legend: false }),
  });
}

function gradientFor(canvasId, color) {
  return (ctx) => {
    const chart = ctx.chart;
    const { ctx: c, chartArea } = chart;
    if (!chartArea) return color;
    const isHorizontal = chart.options.indexAxis === 'y';
    const g = isHorizontal
      ? c.createLinearGradient(chartArea.left, 0, chartArea.right, 0)
      : c.createLinearGradient(0, chartArea.bottom, 0, chartArea.top);
    g.addColorStop(0, hexToRgba(color, 0.25));
    g.addColorStop(1, color);
    return g;
  };
}

function hexToRgba(hex, alpha) {
  const m = hex.replace('#', '').match(/.{2}/g).map(x => parseInt(x, 16));
  return `rgba(${m[0]}, ${m[1]}, ${m[2]}, ${alpha})`;
}

function chartBaseOpts({ legend = true } = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: legend ? {
        labels: { usePointStyle: true, boxWidth: 8 },
        position: 'bottom',
      } : { display: false },
      tooltip: tooltipStyle(),
    },
    scales: {
      x: {
        grid: { display: false, drawBorder: false },
        ticks: { font: { size: 11 } },
      },
      y: {
        beginAtZero: true,
        grid: { color: 'rgba(148, 163, 184, 0.08)', drawBorder: false },
        ticks: { font: { size: 11 } },
      },
    },
  };
}

function tooltipStyle() {
  return {
    backgroundColor: 'rgba(13, 19, 36, 0.95)',
    borderColor: 'rgba(148, 163, 184, 0.2)',
    borderWidth: 1,
    titleColor: '#e6ecff',
    bodyColor: '#cbd5e1',
    padding: 10,
    cornerRadius: 8,
    displayColors: true,
    boxPadding: 4,
  };
}

// ============================================================
// DATA REFRESH
// ============================================================
async function refresh() {
  try {
    const [metrics, txns, alerts] = await Promise.all([
      fetch(API.metrics).then(r => r.json()),
      fetch(API.transactions).then(r => r.json()),
      fetch(API.alerts).then(r => r.json()),
    ]);

    setStatus(true);
    updateKpis(metrics);
    updateCharts(metrics);
    updateFeed(txns.transactions || []);
    updateAlerts(alerts.alerts || []);
  } catch (err) {
    console.error('refresh failed', err);
    setStatus(false);
  }
}

async function loadModelInfo() {
  try {
    const info = await fetch(API.modelInfo).then(r => r.json());
    const m = info.metrics || {};
    if (m.accuracy != null) {
      document.getElementById('model-info').textContent =
        `Model: accuracy ${(m.accuracy * 100).toFixed(1)}% · ROC-AUC ${(m.roc_auc || 0).toFixed(3)} · samples ${m.training_samples || 0}`;
    }
    // feature importance chart
    const imp = info.feature_importance || {};
    const sorted = Object.entries(imp).sort((a, b) => b[1] - a[1]).slice(0, 8);
    charts.features.data.labels = sorted.map(([k]) => k);
    charts.features.data.datasets[0].data = sorted.map(([, v]) => +(v * 100).toFixed(2));
    charts.features.update();
  } catch (e) { console.warn('model info failed', e); }
}

function setStatus(connected) {
  const pill = document.getElementById('status-pill');
  const text = document.getElementById('status-text');
  if (connected) {
    pill.classList.remove('disconnected');
    text.textContent = 'Live · monitoring';
  } else {
    pill.classList.add('disconnected');
    text.textContent = 'Disconnected';
  }
}

// ------------------------------------------------------------
// KPIs
// ------------------------------------------------------------
function updateKpis(m) {
  const total = m.total_transactions || 0;
  const fraud = m.fraud_detected || 0;

  setText('kpi-total', formatNum(total));
  setText('kpi-fraud', formatNum(fraud));
  setText('kpi-approved', formatNum(m.approved || 0));
  setText('kpi-review', m.review || 0);
  setText('kpi-declined', m.declined || 0);
  setText('kpi-latency', (m.avg_latency_ms || 0).toFixed(1));
  setText('kpi-fraud-rate', `${((m.fraud_rate || 0) * 100).toFixed(2)}% fraud rate`);
  setText('kpi-uptime', `Uptime ${formatDuration(m.uptime_seconds || 0)}`);

  // throughput estimate (txns since last poll)
  const now = Date.now();
  const dt = (now - lastTimestamp) / 1000;
  const delta = total - lastTxnCount;
  const perMin = dt > 0 ? Math.round((delta / dt) * 60) : 0;
  setText('kpi-throughput', `${perMin} / min throughput`);
  lastTxnCount = total;
  lastTimestamp = now;
}

// ------------------------------------------------------------
// charts
// ------------------------------------------------------------
function updateCharts(m) {
  const hourly = m.hourly || [];
  charts.hourly.data.datasets[0].data = hourly.map(h => h.total);
  charts.hourly.data.datasets[1].data = hourly.map(h => h.fraud);
  charts.hourly.update();

  const r = m.risk_distribution || {};
  charts.risk.data.datasets[0].data = [r.low || 0, r.medium || 0, r.high || 0, r.critical || 0];
  charts.risk.update();

  const cats = m.top_fraud_categories || [];
  charts.categories.data.labels = cats.map(c => c[0]);
  charts.categories.data.datasets[0].data = cats.map(c => c[1]);
  charts.categories.update();
}

// ------------------------------------------------------------
// live feed
// ------------------------------------------------------------
function updateFeed(items) {
  const tbody = document.getElementById('feed-body');
  if (!items.length) {
    tbody.innerHTML = '<tr class="empty"><td colspan="7">No transactions yet. Click <strong>Run Simulation</strong>.</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(item => {
    const t = item.transaction || {};
    const r = item.result || {};
    const id = r.transaction_id || t.transaction_id || '';
    const isNew = !knownTxnIds.has(id);
    knownTxnIds.add(id);

    const amount = Number(t.amount || 0);
    const time = new Date(item.recorded_at).toLocaleTimeString();
    return `
      <tr class="${isNew ? 'row-new' : ''}">
        <td>${escapeHtml(time)}</td>
        <td><span class="txn-id">${escapeHtml(id)}</span></td>
        <td>$${amount.toFixed(2)}</td>
        <td>${escapeHtml(t.country || '-')}</td>
        <td>${escapeHtml(t.merchant_category || '-')}</td>
        <td>${riskBadge(r.risk_level)}</td>
        <td>${decisionBadge(r.decision)}</td>
      </tr>`;
  }).join('');

  // cap memory
  if (knownTxnIds.size > 2000) {
    knownTxnIds = new Set(Array.from(knownTxnIds).slice(-1000));
  }
}

function riskBadge(level) {
  const lv = level || 'low';
  return `<span class="badge badge-${lv}"><i></i>${lv}</span>`;
}
function decisionBadge(decision) {
  const d = decision || 'approve';
  return `<span class="badge badge-${d}">${d}</span>`;
}

// ------------------------------------------------------------
// alerts
// ------------------------------------------------------------
function updateAlerts(items) {
  const container = document.getElementById('alerts-list');
  if (!items.length) {
    container.innerHTML = '<div class="empty-state">No alerts yet.</div>';
    return;
  }
  container.innerHTML = items.map(a => {
    const time = new Date(a.created_at).toLocaleTimeString();
    const reason = (a.reasons && a.reasons[0]) || 'High-risk transaction';
    return `
      <div class="alert-item alert-${a.risk_level}">
        <div class="stripe"></div>
        <div class="alert-content">
          <div class="alert-title">${escapeHtml(a.transaction_id)} · ${a.risk_level.toUpperCase()}</div>
          <div class="alert-meta">${escapeHtml(time)} · decision: <strong>${escapeHtml(a.decision)}</strong></div>
          <div class="alert-reason">${escapeHtml(reason)}</div>
        </div>
        <div class="alert-prob">${(a.fraud_probability * 100).toFixed(0)}%</div>
      </div>`;
  }).join('');
}

// ============================================================
// ACTIONS
// ============================================================
async function runSimulation() {
  const btn = document.getElementById('btn-simulate');
  btn.disabled = true;
  const original = btn.innerHTML;
  btn.innerHTML = '<span>Simulating…</span>';
  try {
    await fetch(API.simulate, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ count: 40, fraud_rate: 0.18 }),
    });
    await refresh();
  } catch (e) { console.error(e); }
  btn.disabled = false;
  btn.innerHTML = original;
}

async function submitScoreForm(e) {
  e.preventDefault();
  const form = e.target;
  const data = Object.fromEntries(new FormData(form).entries());
  const txn = {
    amount: Number(data.amount),
    country: data.country,
    merchant_category: data.merchant_category,
    hour: Number(data.hour),
    device_type: data.device_type,
    is_card_present: !!data.is_card_present,
    transaction_id: `manual_${Date.now()}`,
  };

  const result = await fetch(API.predict, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(txn),
  }).then(r => r.json());

  renderScoreResult(result);
  refresh();
}

function renderScoreResult(payload) {
  const r = payload.result || payload;
  const prob = (r.fraud_probability || 0) * 100;
  const level = r.risk_level || 'low';
  const colorByLevel = { low: COLORS.green, medium: COLORS.amber, high: COLORS.orange, critical: COLORS.red };
  const color = colorByLevel[level] || COLORS.green;

  const circumference = 2 * Math.PI * 45;
  const offset = circumference * (1 - prob / 100);

  const rules = (r.triggered_rules || []).map(rl =>
    `<div class="rule"><strong>${escapeHtml(rl.name)}</strong> · ${escapeHtml(rl.reason)}</div>`
  ).join('') || '<div class="rule">No rules triggered.</div>';

  const html = `
    <div class="score-card">
      <div class="score-gauge">
        <svg width="110" height="110">
          <circle cx="55" cy="55" r="45" stroke="rgba(148,163,184,0.15)" stroke-width="10" fill="none"/>
          <circle cx="55" cy="55" r="45" stroke="${color}" stroke-width="10" fill="none"
                  stroke-linecap="round"
                  stroke-dasharray="${circumference}"
                  stroke-dashoffset="${offset}"/>
        </svg>
        <div class="score-text" style="color:${color}">${prob.toFixed(0)}%</div>
      </div>
      <div class="score-details">
        <div class="score-row"><span class="lbl">Risk level</span> ${riskBadge(level)}</div>
        <div class="score-row"><span class="lbl">Decision</span> ${decisionBadge(r.decision)}</div>
        <div class="score-row"><span class="lbl">Model score</span> <span class="val">${((r.model_score||0)*100).toFixed(1)}%</span></div>
        <div class="score-row"><span class="lbl">Rule score</span> <span class="val">${((r.rule_score||0)*100).toFixed(1)}%</span></div>
        <div class="rules-list">${rules}</div>
      </div>
    </div>`;
  const out = document.getElementById('score-result');
  out.innerHTML = html;
  out.classList.add('visible');
}

// ============================================================
// helpers
// ============================================================
function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}
function formatNum(n) { return Number(n).toLocaleString(); }
function formatDuration(secs) {
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs/60)}m ${secs%60}s`;
  const h = Math.floor(secs/3600);
  const m = Math.floor((secs%3600)/60);
  return `${h}h ${m}m`;
}
function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}

// ============================================================
// boot
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  buildCharts();
  loadModelInfo();
  refresh();
  setInterval(refresh, POLL_MS);

  document.getElementById('btn-simulate').addEventListener('click', runSimulation);
  document.getElementById('btn-refresh').addEventListener('click', refresh);
  document.getElementById('score-form').addEventListener('submit', submitScoreForm);
});
