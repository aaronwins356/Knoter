const state = {
  markets: [],
  positions: [],
  activity: [],
  status: "Idle",
  sentiment: "Waiting",
  trades: 0,
  pnl: 0,
  highVolCount: 0,
  cadenceSeconds: 30,
  openPositions: 0,
  riskMode: "Conservative",
  nextAction: "Configure bot",
};

const elements = {
  status: document.getElementById("bot-status"),
  volCount: document.getElementById("vol-count"),
  openPositions: document.getElementById("open-positions"),
  eventPnl: document.getElementById("event-pnl"),
  tradeCount: document.getElementById("trade-count"),
  sentiment: document.getElementById("sentiment"),
  nextAction: document.getElementById("next-action"),
  table: document.getElementById("market-table"),
  positions: document.getElementById("positions"),
  log: document.getElementById("activity-log"),
  start: document.getElementById("start-bot"),
  stop: document.getElementById("stop-bot"),
  volThreshold: document.getElementById("vol-threshold"),
  tradeSequence: document.getElementById("trade-sequence"),
  avgGain: document.getElementById("avg-gain"),
  riskNotes: document.getElementById("risk-notes"),
  eventType: document.getElementById("event-type"),
  targetGains: document.getElementById("target-gains"),
  scanCadence: document.getElementById("scan-cadence"),
  modePill: document.getElementById("mode-pill"),
  openaiStatus: document.getElementById("openai-status"),
  kalshiStatus: document.getElementById("kalshi-status"),
  stopRule: document.getElementById("stop-rule"),
};

const formatPercent = (value) => `${(value * 100).toFixed(2)}%`;

const renderMarkets = (markets) => {
  if (!Array.isArray(markets)) return;
  elements.table.innerHTML = markets
    .map((market) => {
      const volatilityClass =
        market.volatility_percent >= market.threshold + 4
          ? "vol-critical"
          : market.volatility_percent >= market.threshold
            ? "vol-high"
            : "";
      return `
        <tr>
          <td>${market.name}</td>
          <td><span class="tag">${market.type}</span></td>
          <td>${formatPercent(market.mid_price)}</td>
          <td class="${volatilityClass}">${market.volatility_percent.toFixed(2)}%</td>
          <td>${market.signal}</td>
        </tr>
      `;
    })
    .join("");
};

const updatePositions = (positions) => {
  if (!positions || positions.length === 0) {
    elements.positions.innerHTML = '<p class="warning">No active positions yet.</p>';
    return;
  }

  elements.positions.innerHTML = positions
    .map(
      (position) => `
      <div class="card" style="padding: 12px;">
        <strong>${position.market_name}</strong>
        <div class="metric"><span>Entry</span><span>${formatPercent(position.entry_price)}</span></div>
        <div class="metric"><span>Current</span><span>${formatPercent(position.current_price)}</span></div>
        <div class="metric"><span>Target</span><span>${position.take_profit_pct.toFixed(1)}%</span></div>
      </div>
    `
    )
    .join("");
};

const updateLog = (entries) => {
  if (!entries) return;
  elements.log.innerHTML = entries
    .map(
      (entry) =>
        `<div class="log-entry"><strong>${new Date(entry.timestamp).toLocaleTimeString()}</strong> — ${entry.message}</div>`
    )
    .join("");
};

const updateMetrics = () => {
  elements.status.textContent = state.status;
  elements.volCount.textContent = String(state.highVolCount);
  elements.openPositions.textContent = String(state.openPositions);
  elements.eventPnl.textContent = `${state.pnl.toFixed(2)}%`;
  elements.tradeCount.textContent = String(state.trades);
  elements.sentiment.textContent = state.sentiment;
  elements.nextAction.textContent = state.nextAction;
  elements.scanCadence.textContent = `${state.cadenceSeconds}s`;
  elements.tradeSequence.textContent = `${state.trades} / 6`;
};

const setConnectionStatus = (element, ok, label) => {
  element.textContent = ok ? `${label} connected` : `${label} not configured`;
  element.style.background = ok ? "rgba(42, 214, 166, 0.18)" : "rgba(255, 204, 122, 0.2)";
  element.style.color = ok ? "#6df2c9" : "#ffcc7a";
};

const syncConfig = (config) => {
  if (!config) return;
  elements.eventType.value = config.event_focus;
  elements.volThreshold.value = config.volatility_threshold;
  elements.avgGain.textContent = `${config.take_profit_pct.toFixed(1)}%`;
  elements.stopRule.textContent = `${config.max_consecutive_losses} losses`;
  state.cadenceSeconds = config.cadence_seconds;
  elements.modePill.textContent = config.paper_trading ? "PAPER MODE" : "LIVE MODE";
};

const loadInitial = async () => {
  const [healthRes, configRes] = await Promise.all([fetch("/health"), fetch("/config")]);
  if (healthRes.ok) {
    const health = await healthRes.json();
    setConnectionStatus(elements.kalshiStatus, health.kalshi_configured, "Kalshi");
    setConnectionStatus(elements.openaiStatus, health.openai_configured, "OpenAI");
  }
  if (configRes.ok) {
    const config = await configRes.json();
    syncConfig(config);
  }
};

const sendConfigUpdate = async () => {
  const payload = {
    event_focus: elements.eventType.value,
    volatility_threshold: Number(elements.volThreshold.value),
    target_gains: elements.targetGains.value,
    risk_notes: elements.riskNotes.value,
  };
  await fetch("/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
};

const startBot = async () => {
  await sendConfigUpdate();
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

elements.start.addEventListener("click", startBot);
elements.stop.addEventListener("click", stopBot);

const connectWebSocket = () => {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws`);

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "status") {
      state.status = message.data.status;
      state.trades = message.data.trades_executed;
      state.pnl = message.data.event_pnl_pct;
      state.openPositions = message.data.open_positions;
      state.highVolCount = message.data.high_vol_count;
      state.sentiment = message.data.sentiment_label;
      state.nextAction = message.data.next_action;
      state.riskMode = message.data.risk_mode;
      updateMetrics();
    }
    if (message.type === "scan") {
      renderMarkets(message.data.markets);
    }
    if (message.type === "positions") {
      updatePositions(message.data.positions);
    }
    if (message.type === "activity") {
      state.activity = message.data.entries;
      updateLog(state.activity);
    }
  });

  socket.addEventListener("close", () => {
    setTimeout(connectWebSocket, 2000);
  });
};

loadInitial();
connectWebSocket();
updateMetrics();
updatePositions([]);
updateLog([]);
