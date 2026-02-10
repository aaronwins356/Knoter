const state = {
  markets: [],
  positions: [],
  orders: [],
  fills: [],
  activity: [],
  audit: [],
  status: "Idle",
  trades: 0,
  pnl: 0,
  highVolCount: 0,
  cadenceSeconds: 30,
  openPositions: 0,
  riskMode: "Conservative",
  nextAction: "Configure bot",
  tradingMode: "paper",
  liveEnabled: false,
  sortKey: "overall_score",
  sortDir: "desc",
  filter: "",
  selectedMarket: null,
};

const elements = {
  status: document.getElementById("bot-status"),
  volCount: document.getElementById("vol-count"),
  openPositions: document.getElementById("open-positions"),
  eventPnl: document.getElementById("event-pnl"),
  tradeCount: document.getElementById("trade-count"),
  nextAction: document.getElementById("next-action"),
  scanCadence: document.getElementById("scan-cadence"),
  riskMode: document.getElementById("risk-mode"),
  modeLabel: document.getElementById("mode-label"),
  table: document.getElementById("market-table"),
  positions: document.getElementById("positions"),
  orders: document.getElementById("orders"),
  fills: document.getElementById("fills"),
  log: document.getElementById("activity-log"),
  auditLog: document.getElementById("audit-log"),
  start: document.getElementById("start-bot"),
  stop: document.getElementById("stop-bot"),
  killBot: document.getElementById("kill-bot"),
  flattenAll: document.getElementById("flatten-all"),
  modePill: document.getElementById("mode-pill"),
  liveWarning: document.getElementById("live-warning"),
  openaiStatus: document.getElementById("openai-status"),
  kalshiStatus: document.getElementById("kalshi-status"),
  modeSelect: document.getElementById("mode-select"),
  liveConfirm: document.getElementById("live-confirm"),
  applyMode: document.getElementById("apply-mode"),
  saveConfig: document.getElementById("save-config"),
  eventType: document.getElementById("event-type"),
  volThreshold: document.getElementById("vol-threshold"),
  maxSpread: document.getElementById("max-spread"),
  minLiquidity: document.getElementById("min-liquidity"),
  takeProfit: document.getElementById("take-profit"),
  stopLoss: document.getElementById("stop-loss"),
  maxHold: document.getElementById("max-hold"),
  closeBefore: document.getElementById("close-before"),
  trailStart: document.getElementById("trail-start"),
  trailGap: document.getElementById("trail-gap"),
  orderTtl: document.getElementById("order-ttl"),
  maxReplace: document.getElementById("max-replace"),
  maxExposure: document.getElementById("max-exposure"),
  maxExposureDollars: document.getElementById("max-exposure-dollars"),
  maxEventLoss: document.getElementById("max-event-loss"),
  maxSessionLoss: document.getElementById("max-session-loss"),
  maxLosses: document.getElementById("max-losses"),
  maxTrades: document.getElementById("max-trades"),
  cooldownSeconds: document.getElementById("cooldown-seconds"),
  killSwitch: document.getElementById("kill-switch"),
  riskNotes: document.getElementById("risk-notes"),
  ruleTp: document.getElementById("rule-tp"),
  ruleSl: document.getElementById("rule-sl"),
  ruleHold: document.getElementById("rule-hold"),
  ruleClose: document.getElementById("rule-close"),
  ruleTrail: document.getElementById("rule-trail"),
  scannerFilter: document.getElementById("scanner-filter"),
  drawerTitle: document.getElementById("drawer-title"),
  drawerMetrics: document.getElementById("drawer-metrics"),
  drawerAudit: document.getElementById("drawer-audit"),
  sparkline: document.getElementById("sparkline"),
  downloadAudit: document.getElementById("download-audit"),
  tabButtons: document.querySelectorAll(".tab-button"),
  tabPanels: document.querySelectorAll(".tab-panel"),
};

const formatPercent = (value) => `${(value * 100).toFixed(2)}%`;

const setConnectionStatus = (element, ok, label, meta = "") => {
  const suffix = meta ? ` (${meta})` : "";
  element.textContent = ok ? `${label} connected${suffix}` : `${label} not configured${suffix}`;
  element.style.background = ok ? "rgba(42, 214, 166, 0.18)" : "rgba(255, 204, 122, 0.2)";
  element.style.color = ok ? "#6df2c9" : "#ffcc7a";
};

const updateModeUI = () => {
  const live = state.tradingMode === "live";
  elements.modePill.textContent = live ? "LIVE MODE" : "PAPER MODE";
  elements.modePill.classList.toggle("live", live);
  elements.liveWarning.classList.toggle("show", live);
  elements.modeLabel.textContent = live ? "Live" : "Paper";
};

const updateMetrics = () => {
  elements.status.textContent = state.status;
  elements.volCount.textContent = String(state.highVolCount);
  elements.openPositions.textContent = String(state.openPositions);
  elements.eventPnl.textContent = `${state.pnl.toFixed(2)}%`;
  elements.tradeCount.textContent = String(state.trades);
  elements.nextAction.textContent = state.nextAction;
  elements.scanCadence.textContent = `${state.cadenceSeconds}s`;
  elements.riskMode.textContent = state.riskMode;
};

const renderRules = (config) => {
  elements.ruleTp.textContent = `${config.exit.take_profit_pct.toFixed(1)}%`;
  elements.ruleSl.textContent = `${config.exit.stop_loss_pct.toFixed(1)}%`;
  elements.ruleHold.textContent = `${config.exit.max_hold_seconds}s`;
  elements.ruleClose.textContent = `${config.exit.close_before_resolution_minutes}m`;
  elements.ruleTrail.textContent = `${config.exit.trail_start_pct.toFixed(1)}% / ${config.exit.trail_gap_pct.toFixed(1)}%`;
};

const renderMarkets = () => {
  const filtered = state.markets.filter((market) => {
    if (!state.filter) return true;
    const target = `${market.name} ${market.market_id}`.toLowerCase();
    return target.includes(state.filter);
  });
  const sorted = [...filtered].sort((a, b) => {
    const aValue = a[state.sortKey];
    const bValue = b[state.sortKey];
    if (typeof aValue === "string") {
      return state.sortDir === "asc" ? aValue.localeCompare(bValue) : bValue.localeCompare(aValue);
    }
    return state.sortDir === "asc" ? aValue - bValue : bValue - aValue;
  });

  elements.table.innerHTML = sorted
    .map(
      (market) => `
        <tr data-market="${market.market_id}">
          <td>${market.name}</td>
          <td><span class="tag">${market.focus}</span></td>
          <td>${formatPercent(market.mid_yes)}</td>
          <td>${market.overall_score.toFixed(1)}</td>
          <td>${market.volatility_pct.toFixed(2)}%</td>
          <td>${market.spread_yes_pct.toFixed(2)}%</td>
          <td>${market.time_to_resolution_minutes.toFixed(0)}m</td>
          <td>${market.qualifies ? "Yes" : "No"}</td>
        </tr>
      `
    )
    .join("");
};

const renderPositions = () => {
  if (!state.positions || state.positions.length === 0) {
    elements.positions.innerHTML = '<p class="warning">No active positions yet.</p>';
    return;
  }
  elements.positions.innerHTML = state.positions
    .map(
      (position) => `
      <div class="card" style="padding: 12px;">
        <strong>${position.market_name}</strong>
        <div class="metric"><span>Side</span><span>${position.side}</span></div>
        <div class="metric"><span>Entry</span><span>${formatPercent(position.entry_price)}</span></div>
        <div class="metric"><span>Current</span><span>${formatPercent(position.current_price)}</span></div>
        <div class="metric"><span>PnL</span><span>${position.pnl_pct.toFixed(2)}%</span></div>
        <div class="metric"><span>TP / SL</span><span>${position.take_profit_pct.toFixed(1)}% / ${position.stop_loss_pct.toFixed(1)}%</span></div>
        <div class="metric"><span>Time stop</span><span>${position.max_hold_seconds}s</span></div>
        <button class="secondary" data-close="${position.position_id}">Close</button>
      </div>
    `
    )
    .join("");
};

const renderOrders = () => {
  const openOrders = (state.orders || []).filter(
    (order) => !["filled", "cancelled"].includes(order.status)
  );
  if (openOrders.length === 0) {
    elements.orders.innerHTML = '<p class="warning">No open orders.</p>';
    return;
  }
  elements.orders.innerHTML = openOrders
    .map(
      (order) => `
      <div class="card" style="padding: 12px;">
        <strong>${order.market_id}</strong>
        <div class="metric"><span>Action</span><span>${order.action}</span></div>
        <div class="metric"><span>Side</span><span>${order.side}</span></div>
        <div class="metric"><span>Price</span><span>${formatPercent(order.price)}</span></div>
        <div class="metric"><span>Status</span><span>${order.status}</span></div>
        <button class="danger" data-cancel="${order.order_id}">Cancel</button>
      </div>
    `
    )
    .join("");
};

const renderFills = () => {
  if (!state.fills || state.fills.length === 0) {
    elements.fills.innerHTML = '<p class="warning">No fills yet.</p>';
    return;
  }
  elements.fills.innerHTML = state.fills
    .slice(0, 6)
    .map(
      (fill) => `
      <div class="card" style="padding: 12px;">
        <strong>${fill.market_id}</strong>
        <div class="metric"><span>Action</span><span>${fill.action}</span></div>
        <div class="metric"><span>Side</span><span>${fill.side}</span></div>
        <div class="metric"><span>Price</span><span>${formatPercent(fill.price)}</span></div>
        <div class="metric"><span>Qty</span><span>${fill.qty}</span></div>
      </div>
    `
    )
    .join("");
};

const renderAudit = () => {
  if (!state.audit || state.audit.length === 0) {
    elements.auditLog.innerHTML = '<p class="warning">No audit records yet.</p>';
    return;
  }
  elements.auditLog.innerHTML = state.audit
    .map(
      (entry) => `
      <div class="log-entry">
        <strong>${new Date(entry.timestamp).toLocaleTimeString()}</strong> — ${entry.market_id} — ${entry.reason_code}
        <div class="warning">${entry.rationale}</div>
      </div>
    `
    )
    .join("");
};

const updateLog = (entries) => {
  if (!entries) return;
  if (entries.length > 0 && entries[0].market_id) {
    const grouped = entries.reduce((acc, entry) => {
      acc[entry.market_id] = acc[entry.market_id] || [];
      acc[entry.market_id].push(entry);
      return acc;
    }, {});
    elements.log.innerHTML = Object.entries(grouped)
      .map(
        ([marketId, items]) => `
        <div class="log-entry">
          <strong>${marketId}</strong>
          ${items
            .slice(0, 3)
            .map(
              (item) => `
              <div>
                ${new Date(item.timestamp).toLocaleTimeString()} — ${item.reason_code}
                <div class="warning">${item.rationale}</div>
              </div>
            `
            )
            .join("")}
        </div>
      `
      )
      .join("");
    return;
  }
  elements.log.innerHTML = entries
    .map(
      (entry) =>
        `<div class="log-entry"><strong>${new Date(entry.timestamp).toLocaleTimeString()}</strong> — ${
          entry.message || `${entry.market_id} ${entry.action}`
        }${entry.rationale ? `<div class="warning">${entry.rationale}</div>` : ""}${
          entry.advisory?.explanations ? `<div>${entry.advisory.explanations.join("<br />")}</div>` : ""
        }</div>`
    )
    .join("");
};

const drawSparkline = (prices) => {
  const canvas = elements.sparkline;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  canvas.width = width;
  canvas.height = height;
  ctx.clearRect(0, 0, width, height);
  if (!prices || prices.length === 0) return;
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  ctx.strokeStyle = "#6df2c9";
  ctx.lineWidth = 2;
  ctx.beginPath();
  prices.forEach((price, idx) => {
    const x = (idx / (prices.length - 1)) * width;
    const normalized = (price - min) / Math.max(max - min, 0.0001);
    const y = height - normalized * height;
    if (idx === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.stroke();
};

const loadMarketDetail = async (marketId) => {
  const response = await fetch(`/markets/${marketId}/detail`);
  if (!response.ok) return;
  const data = await response.json();
  state.selectedMarket = marketId;
  elements.drawerTitle.textContent = data.snapshot.name;
  drawSparkline(data.recent_prices);
  elements.drawerMetrics.innerHTML = `
    <div class="metric"><span>Volatility</span><span>${data.snapshot.volatility_pct.toFixed(2)}%</span></div>
    <div class="metric"><span>Spread</span><span>${data.snapshot.spread_yes_pct.toFixed(2)}%</span></div>
    <div class="metric"><span>Liquidity</span><span>${data.snapshot.liquidity_score.toFixed(1)}</span></div>
    <div class="metric"><span>Score</span><span>${data.snapshot.overall_score.toFixed(1)}</span></div>
    <div class="metric"><span>Resolution</span><span>${data.snapshot.time_to_resolution_minutes.toFixed(0)}m</span></div>
    <div class="metric"><span>Mid (Yes)</span><span>${formatPercent(data.snapshot.mid_yes)}</span></div>
  `;
  if (data.audit.length === 0) {
    elements.drawerAudit.innerHTML = '<p class="warning">No audit records yet.</p>';
  } else {
    elements.drawerAudit.innerHTML = data.audit
      .map(
        (entry) => `
        <div class="log-entry">
          <strong>${new Date(entry.timestamp).toLocaleTimeString()}</strong> — ${entry.reason_code}
          <div class="warning">${entry.rationale}</div>
          ${entry.advisory ? `<div>${entry.advisory.explanations?.join("<br />") || ""}</div>` : ""}
        </div>
      `
      )
      .join("");
  }
};

const syncConfig = (config) => {
  elements.eventType.value = config.market_filters.event_type;
  elements.volThreshold.value = config.scoring.vol_threshold;
  elements.maxSpread.value = config.scoring.max_spread_pct;
  elements.minLiquidity.value = config.scoring.min_liquidity_score;
  elements.takeProfit.value = config.exit.take_profit_pct;
  elements.stopLoss.value = config.exit.stop_loss_pct;
  elements.maxHold.value = config.exit.max_hold_seconds;
  elements.closeBefore.value = config.exit.close_before_resolution_minutes;
  elements.trailStart.value = config.exit.trail_start_pct;
  elements.trailGap.value = config.exit.trail_gap_pct;
  elements.orderTtl.value = config.entry.order_ttl_seconds;
  elements.maxReplace.value = config.entry.max_replacements;
  elements.maxExposure.value = config.risk_limits.max_exposure_contracts;
  elements.maxExposureDollars.value = config.risk_limits.max_exposure_dollars;
  elements.maxEventLoss.value = config.risk_limits.max_event_loss_pct;
  elements.maxSessionLoss.value = config.risk_limits.max_session_loss_pct;
  elements.maxLosses.value = config.risk_limits.max_consecutive_losses;
  elements.maxTrades.value = config.risk_limits.max_trades_per_event;
  elements.cooldownSeconds.value = config.risk_limits.cooldown_after_trade_seconds;
  elements.killSwitch.value = config.risk_limits.kill_switch ? "true" : "false";
  elements.riskNotes.value = config.risk_notes;
  elements.modeSelect.value = config.trading_mode;
  state.tradingMode = config.trading_mode;
  state.liveEnabled = config.live_trading_enabled;
  state.cadenceSeconds = config.cadence_seconds;
  renderRules(config);
  updateModeUI();
};

const loadInitial = async () => {
  const [healthRes, configRes, kalshiRes, auditRes] = await Promise.all([
    fetch("/health"),
    fetch("/config"),
    fetch("/kalshi/status"),
    fetch("/audit"),
  ]);
  if (healthRes.ok) {
    const health = await healthRes.json();
    setConnectionStatus(elements.openaiStatus, health.openai_configured, "OpenAI");
  }
  if (kalshiRes.ok) {
    const kalshi = await kalshiRes.json();
    const meta = kalshi.environment ? `${kalshi.environment}${kalshi.last_error_summary ? " · error" : ""}` : "";
    setConnectionStatus(elements.kalshiStatus, kalshi.connected, "Kalshi", meta);
  }
  if (configRes.ok) {
    const config = await configRes.json();
    syncConfig(config);
  }
  if (auditRes.ok) {
    const audit = await auditRes.json();
    state.audit = audit.records || [];
    renderAudit();
    updateLog(state.audit);
  }
};

const saveConfig = async () => {
  const payload = {
    market_filters: {
      event_type: elements.eventType.value,
      time_window_hours: 24,
    },
    scoring: {
      vol_threshold: Number(elements.volThreshold.value),
      max_spread_pct: Number(elements.maxSpread.value),
      min_liquidity_score: Number(elements.minLiquidity.value),
    },
    exit: {
      take_profit_pct: Number(elements.takeProfit.value),
      stop_loss_pct: Number(elements.stopLoss.value),
      max_hold_seconds: Number(elements.maxHold.value),
      close_before_resolution_minutes: Number(elements.closeBefore.value),
      trail_start_pct: Number(elements.trailStart.value),
      trail_gap_pct: Number(elements.trailGap.value),
    },
    entry: {
      order_ttl_seconds: Number(elements.orderTtl.value),
      max_replacements: Number(elements.maxReplace.value),
    },
    risk_limits: {
      max_exposure_contracts: Number(elements.maxExposure.value),
      max_exposure_dollars: Number(elements.maxExposureDollars.value),
      max_event_loss_pct: Number(elements.maxEventLoss.value),
      max_session_loss_pct: Number(elements.maxSessionLoss.value),
      max_consecutive_losses: Number(elements.maxLosses.value),
      max_trades_per_event: Number(elements.maxTrades.value),
      cooldown_after_trade_seconds: Number(elements.cooldownSeconds.value),
      kill_switch: elements.killSwitch.value === "true",
    },
    risk_notes: elements.riskNotes.value,
  };
  await fetch("/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
};

const applyMode = async () => {
  const payload = {
    trading_mode: elements.modeSelect.value,
    live_confirm: elements.liveConfirm.value,
  };
  const response = await fetch("/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (response.ok) {
    const config = await response.json();
    syncConfig(config);
  } else {
    const message = await response.json();
    alert(message.detail || "Unable to switch mode");
  }
};

const startBot = async () => {
  await saveConfig();
  const response = await fetch("/bot/start", { method: "POST" });
  if (response.ok) {
    elements.start.disabled = true;
    elements.stop.disabled = false;
  }
};

const stopBot = async () => {
  const response = await fetch("/bot/stop", { method: "POST" });
  if (response.ok) {
    elements.start.disabled = false;
    elements.stop.disabled = true;
  }
};

const flattenAll = async () => {
  if (!confirm("Flatten all positions and cancel open orders?")) return;
  const response = await fetch("/positions/flatten", { method: "POST" });
  if (!response.ok) {
    alert("Flatten failed.");
    return;
  }
  const data = await response.json();
  state.activity.unshift({
    timestamp: new Date().toISOString(),
    message: `Flatten requested. Closed ${data.closed_positions.length} positions, cancelled ${data.cancelled_orders.length} orders.`,
    category: data.errors && data.errors.length > 0 ? "warning" : "info",
  });
  renderActivity();
};

const killBot = async () => {
  const response = await fetch("/bot/kill", { method: "POST" });
  if (response.ok) {
    elements.start.disabled = false;
    elements.stop.disabled = true;
  }
};

const connectWebSocket = () => {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws`);

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "batch") {
      if (message.data?.status) {
        state.status = message.data.status.status;
        state.trades = message.data.status.trades_executed;
        state.pnl = message.data.status.event_pnl_pct;
        state.openPositions = message.data.status.open_positions;
        state.highVolCount = message.data.status.high_vol_count;
        state.nextAction = message.data.status.next_action;
        state.riskMode = message.data.status.risk_mode;
        state.tradingMode = message.data.status.trading_mode;
        state.liveEnabled = message.data.status.live_trading_enabled;
      }
      if (message.data?.scan) {
        state.markets = message.data.scan.markets || [];
      }
      if (message.data?.positions) {
        state.positions = message.data.positions.positions || [];
      }
      if (message.data?.activity) {
        state.activity = message.data.activity.entries || [];
      }
      updateModeUI();
      updateMetrics();
      renderMarkets();
      renderPositions();
      updateLog(state.audit && state.audit.length ? state.audit : state.activity);
      return;
    }
    if (message.type === "status") {
      state.status = message.data.status;
      state.trades = message.data.trades_executed;
      state.pnl = message.data.event_pnl_pct;
      state.openPositions = message.data.open_positions;
      state.highVolCount = message.data.high_vol_count;
      state.nextAction = message.data.next_action;
      state.riskMode = message.data.risk_mode;
      state.tradingMode = message.data.trading_mode;
      state.liveEnabled = message.data.live_trading_enabled;
      updateModeUI();
      updateMetrics();
    }
    if (message.type === "scan") {
      state.markets = message.data.markets || [];
      renderMarkets();
    }
    if (message.type === "positions") {
      state.positions = message.data.positions || [];
      renderPositions();
    }
    if (message.type === "activity") {
      state.activity = message.data.entries;
      updateLog(state.audit && state.audit.length ? state.audit : state.activity);
    }
  });

  socket.addEventListener("close", () => {
    setTimeout(connectWebSocket, 2000);
  });
};

const refreshOrders = async () => {
  const [ordersRes, fillsRes] = await Promise.all([fetch("/orders"), fetch("/fills")]);
  if (ordersRes.ok) {
    const data = await ordersRes.json();
    state.orders = data.orders || [];
    renderOrders();
  }
  if (fillsRes.ok) {
    const data = await fillsRes.json();
    state.fills = data.fills || [];
    renderFills();
  }
};

const refreshAudit = async () => {
  const response = await fetch("/audit");
  if (response.ok) {
    const data = await response.json();
    state.audit = data.records || [];
    renderAudit();
    updateLog(state.audit);
  }
};

const handleTableClick = (event) => {
  const row = event.target.closest("tr");
  if (!row) return;
  const marketId = row.dataset.market;
  if (marketId) {
    loadMarketDetail(marketId);
  }
};

const handleTabClick = (event) => {
  const tab = event.target.dataset.tab;
  if (!tab) return;
  elements.tabButtons.forEach((button) => button.classList.toggle("active", button.dataset.tab === tab));
  elements.tabPanels.forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${tab}`));
};

const handleSort = (event) => {
  const key = event.target.dataset.sort;
  if (!key) return;
  if (state.sortKey === key) {
    state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
  } else {
    state.sortKey = key;
    state.sortDir = "desc";
  }
  renderMarkets();
};

const handlePositionAction = async (event) => {
  const closeId = event.target.dataset.close;
  if (closeId) {
    await fetch(`/positions/${closeId}/close`, { method: "POST" });
  }
  await refreshOrders();
};

const handleOrderAction = async (event) => {
  const cancelId = event.target.dataset.cancel;
  if (cancelId) {
    await fetch(`/orders/${cancelId}/cancel`, { method: "POST" });
  }
  await refreshOrders();
};

const handleFilter = (event) => {
  state.filter = event.target.value.toLowerCase();
  renderMarkets();
};

elements.start.addEventListener("click", startBot);
elements.stop.addEventListener("click", stopBot);
elements.killBot.addEventListener("click", killBot);
elements.flattenAll.addEventListener("click", flattenAll);
elements.saveConfig.addEventListener("click", saveConfig);
elements.applyMode.addEventListener("click", applyMode);
elements.table.addEventListener("click", handleTableClick);
elements.scannerFilter.addEventListener("input", handleFilter);
document.querySelector("thead").addEventListener("click", handleSort);
elements.positions.addEventListener("click", handlePositionAction);
elements.orders.addEventListener("click", handleOrderAction);
elements.downloadAudit.addEventListener("click", () => {
  window.location.href = "/audit/csv";
});
elements.tabButtons.forEach((button) => button.addEventListener("click", handleTabClick));

loadInitial();
connectWebSocket();
updateMetrics();
renderPositions();
renderOrders();
renderFills();
updateLog([]);
setInterval(refreshOrders, 5000);
setInterval(refreshAudit, 15000);
