"""Static assets for the web dashboard frontend."""

WEB_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HLTrading Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {
    --bg:#0a1018;
    --surface:#121a25;
    --surface-2:#0f1620;
    --surface-3:#182230;
    --border:#233043;
    --border-soft:rgba(138, 160, 181, 0.12);
    --green:#3fb950;
    --red:#f85149;
    --yellow:#d7a93b;
    --cyan:#66b6ff;
    --text:#e5edf7;
    --muted:#8da1b5;
    --muted-2:#6f8294;
    --purple:#bc8cff;
    --shadow:0 16px 36px rgba(0,0,0,.28);
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{
    background:
      radial-gradient(circle at top, rgba(102,182,255,.08), transparent 28%),
      linear-gradient(180deg, #091019 0%, var(--bg) 20%, #081019 100%);
    color:var(--text);
    font-family:'Segoe UI',system-ui,sans-serif;
    padding:0 0 48px;
    line-height:1.35;
  }

  /* ── Header ── */
  .header{
    display:flex;align-items:center;gap:18px;flex-wrap:wrap;
    background:rgba(10,16,24,.88);
    backdrop-filter:blur(16px);
    border-bottom:1px solid var(--border-soft);
    padding:16px 24px;
    position:sticky;top:0;z-index:100
  }
  .brand{display:flex;align-items:center;gap:14px;min-width:0}
  .brand-copy{display:flex;flex-direction:column;gap:2px}
  .brand-copy small{color:var(--muted);font-size:.74rem;letter-spacing:.04em;text-transform:uppercase}
  .header h1{color:var(--text);font-size:1.08rem;white-space:nowrap;font-weight:650;letter-spacing:.01em}
  .status-dot{width:10px;height:10px;border-radius:50%;background:var(--muted);
              display:inline-block;transition:background .3s}
  .status-dot.running{background:var(--green);box-shadow:0 0 10px rgba(63,185,80,.45)}
  .status-dot.stopped{background:var(--red)}
  .status-dot.paused{background:var(--yellow)}
  #mode-label{
    font-size:.77rem;color:var(--muted);
    background:rgba(255,255,255,.03);
    border:1px solid var(--border-soft);
    padding:6px 10px;border-radius:999px
  }
  #last-updated{font-size:.72rem;color:var(--muted);margin-left:auto}

  /* ── Control buttons ── */
  .controls{display:flex;gap:8px;flex-wrap:wrap}
  .btn{
    padding:8px 14px;border-radius:10px;border:1px solid transparent;cursor:pointer;
    font-size:.78rem;font-weight:600;transition:transform .12s, opacity .15s, border-color .15s
  }
  .btn:hover{opacity:.92;transform:translateY(-1px)} .btn:active{opacity:.78;transform:translateY(0)}
  .btn:disabled{opacity:.4;cursor:not-allowed}
  .btn-start{background:rgba(63,185,80,.12);color:var(--green);border-color:rgba(63,185,80,.22)}
  .btn-stop{background:rgba(215,169,59,.12);color:var(--yellow);border-color:rgba(215,169,59,.22)}
  .btn-pause{background:rgba(102,182,255,.12);color:var(--cyan);border-color:rgba(102,182,255,.22)}
  .btn-emerg{background:rgba(248,81,73,.12);color:var(--red);border-color:rgba(248,81,73,.24)}
  .btn-opt{background:rgba(188,140,255,.12);color:var(--purple);border-color:rgba(188,140,255,.24)}

  /* ── Layout ── */
  .main{padding:22px 24px;max-width:1440px;margin:0 auto}
  .hero{display:grid;gap:16px;margin-bottom:18px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px}
  .card{
    background:linear-gradient(180deg, rgba(255,255,255,.02), transparent), var(--surface);
    border:1px solid var(--border-soft);
    border-radius:16px;
    padding:14px 16px;
    box-shadow:var(--shadow);
    min-height:96px;
  }
  .card .lbl{
    color:var(--muted);
    font-size:.66rem;
    text-transform:uppercase;
    letter-spacing:.08em;
    font-weight:600
  }
  .card .val{font-size:1.42rem;font-weight:700;margin-top:8px;letter-spacing:-.02em}
  .card .sub{color:var(--muted-2);font-size:.74rem;margin-top:6px}
  .card.primary .val{font-size:1.62rem}
  .stack{display:grid;gap:18px}
  .split-2{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,.95fr);gap:18px}
  .split-2-even{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
  .full-width{display:grid;grid-template-columns:1fr;gap:18px}
  .row-section{display:grid;gap:12px}
  .row-toggle{
    display:flex;align-items:center;justify-content:space-between;gap:12px;
    padding:12px 14px;border:1px solid var(--border-soft);border-radius:14px;
    background:rgba(255,255,255,.025);cursor:pointer;user-select:none;
  }
  .row-toggle:hover{background:rgba(255,255,255,.04)}
  .row-toggle-left{display:flex;align-items:center;gap:10px;min-width:0}
  .row-toggle h2{
    font-size:.78rem;color:var(--text);text-transform:uppercase;letter-spacing:.08em;font-weight:700
  }
  .row-toggle span{
    color:var(--muted);font-size:.72rem
  }
  .chevron{
    color:var(--muted);font-size:.9rem;transition:transform .18s ease
  }
  .row-section.collapsed .chevron{transform:rotate(-90deg)}
  .row-content{display:grid;gap:18px}
  .row-section.collapsed .row-content{display:none}
  .panel{
    background:linear-gradient(180deg, rgba(255,255,255,.018), transparent), var(--surface);
    border:1px solid var(--border-soft);
    border-radius:18px;
    padding:16px 18px;
    box-shadow:var(--shadow);
    min-width:0;
  }

  /* ── Charts ── */
  .charts-row{display:grid;grid-template-columns:minmax(0,1fr);gap:18px}
  .cbox{
    background:linear-gradient(180deg, rgba(255,255,255,.018), transparent), var(--surface);
    border:1px solid var(--border-soft);
    border-radius:18px;
    padding:16px 18px;
    box-shadow:var(--shadow)
  }
  .cbox h2{font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px}
  canvas{max-height:220px}
  .coin-performance-grid{
    display:grid;
    grid-template-columns:minmax(320px,.92fr) minmax(0,1.08fr);
    gap:18px;
    align-items:stretch;
  }

  /* ── Sections ── */
  section{margin:0}
  .section-title{
    font-size:.7rem;color:var(--muted);text-transform:uppercase;
    letter-spacing:.08em;margin-bottom:12px;display:flex;align-items:center;gap:8px;
    font-weight:700
  }
  .section-title .cnt{
    background:rgba(255,255,255,.05);color:var(--text);
    border-radius:999px;padding:2px 8px;font-size:.64rem;border:1px solid var(--border-soft)
  }

  /* ── Tables ── */
  table{width:100%;border-collapse:separate;border-spacing:0;font-size:.78rem}
  th{
    color:var(--muted);text-align:left;
    padding:9px 10px;border-bottom:1px solid var(--border-soft);font-weight:600;white-space:nowrap;
    font-size:.68rem;text-transform:uppercase;letter-spacing:.05em
  }
  td{padding:10px;border-bottom:1px solid rgba(255,255,255,.04);vertical-align:middle}
  tbody tr:hover td{background:rgba(255,255,255,.025)}
  .empty{color:var(--muted);font-style:italic;padding:10px 0;font-size:.82rem}
  .table-wrap{
    width:100%;
    overflow:auto;
    border:1px solid rgba(255,255,255,.04);
    border-radius:14px;
    background:var(--surface-2);
  }
  .table-wrap table{min-width:760px}

  /* ── Coin grid ── */
  .coin-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}
  .coin-card{
    background:var(--surface-2);border:1px solid var(--border-soft);border-radius:14px;
    padding:12px 14px;display:flex;align-items:center;justify-content:space-between;gap:12px
  }
  .coin-info .name{font-weight:650;font-size:.84rem}
  .coin-info .meta{color:var(--muted-2);font-size:.69rem;margin-top:4px;line-height:1.4}
  .toggle{position:relative;width:38px;height:20px;cursor:pointer}
  .toggle input{opacity:0;width:0;height:0}
  .toggle-track{position:absolute;top:0;left:0;right:0;bottom:0;
                background:#2a3749;border-radius:20px;transition:.2s}
  .toggle input:checked+.toggle-track{background:var(--green)}
  .toggle-track:before{content:'';position:absolute;width:14px;height:14px;
                       left:3px;top:3px;background:#fff;border-radius:50%;transition:.2s}
  .toggle input:checked+.toggle-track:before{transform:translateX(18px)}

  /* ── Log ── */
  .log-box{
    background:var(--surface-2);border:1px solid var(--border-soft);border-radius:16px;
    padding:10px 14px;max-height:320px;overflow-y:auto;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.74rem
  }
  .log-row{display:grid;grid-template-columns:70px 58px 58px 1fr;gap:10px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.04)}
  .log-row:last-child{border-bottom:none}
  .log-ts{color:var(--muted);white-space:nowrap}
  .log-coin{color:var(--cyan);width:auto;flex-shrink:0}
  .log-action.long,.log-action.short{color:var(--green)}
  .log-action.hold{color:var(--muted)}
  .log-reason{color:var(--text);opacity:.75;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

  /* ── Badges & pills ── */
  .badge{display:inline-block;padding:3px 8px;border-radius:999px;font-size:.67rem;font-weight:700}
  .bl{background:rgba(63,185,80,.14);color:var(--green)} .bs{background:rgba(248,81,73,.14);color:var(--red)}
  .pill{display:inline-block;padding:3px 7px;border-radius:999px;font-size:.66rem;font-weight:700}
  .pill-tp{background:rgba(63,185,80,.14);color:var(--green)} .pill-sl{background:rgba(248,81,73,.14);color:var(--red)}
  .pill-mb{background:rgba(215,169,59,.14);color:var(--yellow)} .pill-mc{background:rgba(102,182,255,.14);color:var(--cyan)}
  .green{color:var(--green)} .red{color:var(--red)} .yellow{color:var(--yellow)} .cyan{color:var(--cyan)}
  .muted{color:var(--muted)}

  /* ── Opt modal ── */
  .modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:200;
                 align-items:center;justify-content:center}
  .modal-overlay.show{display:flex}
  .modal{background:var(--surface);border:1px solid var(--border-soft);border-radius:18px;
         padding:24px;min-width:360px;max-width:560px;width:90%;box-shadow:var(--shadow)}
  .modal h2{color:var(--cyan);margin-bottom:12px;font-size:1rem}
  .modal pre{background:var(--surface-2);border-radius:10px;padding:10px;font-size:.73rem;
             max-height:320px;overflow:auto;color:var(--text)}
  .modal .close-btn{margin-top:14px;float:right}

  /* ── Close button in table ── */
  .btn-xs{padding:5px 10px;font-size:.68rem;border-radius:8px;border:none;cursor:pointer}
  .btn-close-pos{background:rgba(248,81,73,.12);color:var(--red);border:1px solid rgba(248,81,73,.24)}
  .btn-close-pos:hover{background:#4d2525}

  /* ── Stats grid ── */
  .stats-grid{
    display:grid;
    grid-template-columns:repeat(auto-fill,minmax(180px,1fr));
    gap:10px;
    align-content:stretch;
  }
  .stat-item{background:var(--surface-2);border:1px solid var(--border-soft);border-radius:14px;padding:12px 14px;height:100%}
  .stat-item .slbl{color:var(--muted);font-size:.66rem;text-transform:uppercase;letter-spacing:.06em}
  .stat-item .sval{font-size:1.08rem;font-weight:700;margin-top:6px}
  .subsection{display:grid;gap:14px;height:100%}
  .subsection .section-title{margin-bottom:0}
  .stats-panel{
    display:grid;
    grid-template-rows:auto 1fr;
    gap:14px;
    height:100%;
    background:var(--surface-2);
    border:1px solid var(--border-soft);
    border-radius:18px;
    padding:14px 16px;
  }

  @media(max-width:1100px){
    .split-2,.split-2-even,.charts-row,.coin-performance-grid{grid-template-columns:1fr}
  }
  @media(max-width:720px){
    .header{gap:10px;padding:14px 16px}
    .main{padding:18px 16px}
    .cards{grid-template-columns:repeat(2,minmax(0,1fr))}
    .card{min-height:auto}
    .header .controls{width:100%}
    .header .controls .btn{flex:1 1 calc(50% - 8px)}
    .log-row{grid-template-columns:60px 52px 52px 1fr}
  }
  @media(max-width:520px){
    .cards{grid-template-columns:1fr}
    .coin-grid,.stats-grid{grid-template-columns:1fr}
  }
</style>
</head>
<body>

<!-- ── Header ─────────────────────────────────────────────────────────── -->
<div class="header">
  <div class="brand">
    <span id="dot" class="status-dot stopped"></span>
    <div class="brand-copy">
      <small>Live Control Panel</small>
      <h1>HLTrading Dashboard</h1>
    </div>
  </div>
  <span id="mode-label" class="muted">—</span>

  <div class="controls">
    <button class="btn btn-start"  onclick="botAction('start')">▶ Start</button>
    <button class="btn btn-stop"   onclick="botAction('stop')">■ Stop</button>
    <button id="btn-pause" class="btn btn-pause" onclick="botAction('pause')">⏸ Pause</button>
    <button class="btn btn-emerg"  onclick="confirmEmergency()">🔴 Emergency</button>
    <button class="btn btn-opt"    onclick="openOptimizer()">🔬 Optimize</button>
  </div>
  <span id="last-updated">Connecting…</span>
</div>

<div class="main">

<!-- ── Summary cards ─────────────────────────────────────────────────── -->
<div class="hero">
<div class="cards">
  <div class="card primary"><div class="lbl">Capital</div>
    <div class="val cyan" id="c-capital">—</div>
    <div class="sub" id="c-hl-sub" style="font-size:0.72rem;opacity:0.7"></div></div>
  <div class="card primary"><div class="lbl">Total P&amp;L</div>
    <div class="val" id="c-pnl">—</div>
    <div class="sub" id="c-pnl-pct">—</div></div>
  <div class="card"><div class="lbl">Win Rate</div>
    <div class="val" id="c-wr">—</div>
    <div class="sub" id="c-trades">—</div></div>
  <div class="card"><div class="lbl">Profit Factor</div>
    <div class="val" id="c-pf">—</div></div>
  <div class="card"><div class="lbl">Max Drawdown</div>
    <div class="val" id="c-dd">—</div></div>
  <div class="card"><div class="lbl">Today P&amp;L</div>
    <div class="val" id="c-today">—</div>
    <div class="sub" id="c-today-n">—</div></div>
  <div class="card"><div class="lbl">Fees Paid</div>
    <div class="val yellow" id="c-fees">—</div></div>
</div>
</div>

<div class="stack">
  <!-- ── Main monitoring row ────────────────────────────────────────── -->
  <div class="row-section" data-row-id="monitoring">
    <div class="row-toggle" onclick="toggleRow('monitoring')">
      <div class="row-toggle-left">
        <span class="chevron" id="chevron-monitoring">▾</span>
        <h2>Monitoring</h2>
        <span>Equity Curve · Bot Activity Log</span>
      </div>
    </div>
    <div class="row-content split-2" id="row-content-monitoring">
      <section class="panel">
        <div class="section-title">Equity Curve</div>
        <div class="charts-row">
          <div class="cbox"><h2>Portfolio Equity</h2><canvas id="equity-chart"></canvas></div>
        </div>
      </section>

      <section class="panel">
        <div class="section-title">Bot Activity Log</div>
        <div class="log-box" id="log-box"><span class="muted">Waiting for scan data…</span></div>
      </section>
    </div>
  </div>

  <!-- ── Trading state row ──────────────────────────────────────────── -->
  <div class="row-section" data-row-id="trading-state">
    <div class="row-toggle" onclick="toggleRow('trading-state')">
      <div class="row-toggle-left">
        <span class="chevron" id="chevron-trading-state">▾</span>
        <h2>Trading State</h2>
        <span>Open Positions · Recent Trades</span>
      </div>
    </div>
    <div class="row-content split-2-even" id="row-content-trading-state">
      <section class="panel">
        <div class="section-title">Open Positions <span class="cnt" id="pos-count">0</span></div>
        <div class="table-wrap">
          <div id="positions-table"><p class="empty">No open positions.</p></div>
        </div>
      </section>

      <section class="panel">
        <div class="section-title">Recent Trades <span class="cnt" id="trades-count">0</span></div>
        <div class="table-wrap">
          <div id="trades-table"><p class="empty">No closed trades yet.</p></div>
        </div>
      </section>
    </div>
  </div>

  <!-- ── Bottom row ─────────────────────────────────────────────────── -->
  <div class="row-section" data-row-id="coin-performance">
    <div class="row-toggle" onclick="toggleRow('coin-performance')">
      <div class="row-toggle-left">
        <span class="chevron" id="chevron-coin-performance">▾</span>
        <h2>Coin Performance</h2>
        <span>P&amp;L by Coin · Performance Stats · Coins</span>
      </div>
    </div>
    <div class="row-content full-width" id="row-content-coin-performance">
      <section class="panel">
        <div class="section-title">Coin Performance Summary</div>
        <div class="coin-performance-grid">
          <div class="subsection">
            <div class="cbox"><h2>P&amp;L by Coin</h2><canvas id="coin-chart"></canvas></div>
            <div class="panel" style="padding:14px 16px">
              <div class="section-title">Coins</div>
              <div class="coin-grid" id="coin-grid">Loading…</div>
            </div>
          </div>
          <div class="stats-panel">
            <div class="section-title">Performance Stats</div>
            <div class="stats-grid" id="stats-grid">Loading…</div>
          </div>
        </div>
      </section>
    </div>
  </div>
</div>

</div><!-- /main -->

<!-- ── Optimizer modal ───────────────────────────────────────────────── -->
<div class="modal-overlay" id="opt-modal">
  <div class="modal">
    <h2>🔬 Optimizer</h2>
    <p id="opt-msg" style="color:var(--muted);font-size:.82rem;margin-bottom:10px">
      This runs a full grid search on all active coins (3–10 min). Continue?
    </p>
    <pre id="opt-result" style="display:none"></pre>
    <div style="display:flex;gap:8px;margin-top:14px">
      <button class="btn btn-opt" id="opt-run-btn" onclick="runOptimizer()">Run Optimizer</button>
      <button class="btn btn-stop" onclick="closeModal('opt-modal')">Close</button>
    </div>
  </div>
</div>

<!-- ── Emergency confirm modal ───────────────────────────────────────── -->
<div class="modal-overlay" id="emerg-modal">
  <div class="modal">
    <h2 style="color:var(--red)">⚠ Emergency Stop</h2>
    <p style="color:var(--muted);font-size:.82rem;margin-bottom:14px">
      This will immediately close ALL open positions and halt trading.<br>
      <b style="color:var(--red)">This cannot be undone.</b>
    </p>
    <div style="display:flex;gap:8px">
      <button class="btn btn-emerg" onclick="doEmergency()">Confirm: Close All &amp; Halt</button>
      <button class="btn btn-stop"  onclick="closeModal('emerg-modal')">Cancel</button>
    </div>
  </div>
</div>

<script>
// ── State ──────────────────────────────────────────────────────────────────
let equityChart = null, coinChart = null;
let lastLogTs   = null;
let coinsLoaded = false;
const COLLAPSIBLE_ROWS = ['monitoring', 'trading-state', 'coin-performance'];

// ── Utilities ──────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
function fmt(n, prefix='$') {
  if (n == null) return '—';
  const s = Math.abs(n).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return (n >= 0 ? '+' : '-') + prefix + s;
}
function fmtNum(n) { return n == null ? '—' : n.toLocaleString(); }
function pill(reason) {
  const r = (reason||'').toLowerCase();
  if (r.includes('take_profit')||r=='tp') return '<span class="pill pill-tp">TP</span>';
  if (r.includes('stop_loss')||r=='sl')   return '<span class="pill pill-sl">SL</span>';
  if (r.includes('max_bar')||r.includes('timeout')) return '<span class="pill pill-mb">Timeout</span>';
  return '<span class="pill pill-mc">'+reason+'</span>';
}

function setRowCollapsed(rowId, collapsed) {
  const section = document.querySelector(`[data-row-id="${rowId}"]`);
  if (!section) return;
  section.classList.toggle('collapsed', collapsed);
  try {
    localStorage.setItem(`hlt-row-${rowId}`, collapsed ? '1' : '0');
  } catch (e) {}
}

function toggleRow(rowId) {
  const section = document.querySelector(`[data-row-id="${rowId}"]`);
  if (!section) return;
  setRowCollapsed(rowId, !section.classList.contains('collapsed'));
}

function initCollapsibleRows() {
  COLLAPSIBLE_ROWS.forEach((rowId) => {
    let collapsed = false;
    try {
      collapsed = localStorage.getItem(`hlt-row-${rowId}`) === '1';
    } catch (e) {}
    setRowCollapsed(rowId, collapsed);
  });
}

// ── Status polling (every 5 s) ─────────────────────────────────────────────
async function fetchStatus() {
  try {
    const d = await fetch('/api/status').then(r => r.json());

    // Header
    const dot = $('dot');
    dot.className = 'status-dot ' + (d.paused ? 'paused' : d.bot_running ? 'running' : 'stopped');
    $('mode-label').textContent = (d.mode==='live'?'⚡ LIVE':'📄 Paper') + ' · ' +
                                  (d.network==='testnet'?'Testnet':'⚠ Mainnet');
    $('last-updated').textContent = 'Updated ' + d.last_updated;
    $('btn-pause').textContent = d.paused ? '▶ Resume' : '⏸ Pause';

    // Cards
    $('c-capital').textContent = '$' + d.capital.toLocaleString('en', {minimumFractionDigits:2,maximumFractionDigits:2});
    // Show HL perps/spot breakdown when live data is available
    const hlSub = $('c-hl-sub');
    if (d.hl_balance != null) {
      hlSub.textContent = 'perps $' + (d.hl_perps_equity||0).toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2})
                        + ' · spot $' + (d.hl_spot_usdc||0).toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2});
    } else {
      hlSub.textContent = d.mode === 'paper' ? 'paper mode' : 'HL unavailable';
    }
    const pnlEl = $('c-pnl');
    pnlEl.textContent = fmt(d.total_pnl);
    pnlEl.className   = 'val ' + (d.total_pnl >= 0 ? 'green' : 'red');
    $('c-pnl-pct').textContent = (d.total_pnl_pct >= 0 ? '+' : '') + d.total_pnl_pct + '%';

    // Positions table
    const posDiv = $('positions-table');
    const poses  = Object.entries(d.positions||{});
    $('pos-count').textContent = poses.length;
    if (!poses.length) {
      posDiv.innerHTML = '<p class="empty">No open positions.</p>';
    } else {
      let rows = poses.map(([coin, p]) => {
        const pnlCls = (p.live_pnl??0) >= 0 ? 'green' : 'red';
        const pnlStr = p.live_pnl != null ? '<span class="'+pnlCls+'">'+fmt(p.live_pnl)+'</span>' : '<span class="muted">—</span>';
        const lp     = p.live_price ? '$'+p.live_price.toLocaleString('en',{minimumFractionDigits:4,maximumFractionDigits:6}) : '—';
        return `<tr>
          <td><b>${coin}</b><br><span class="muted" style="font-size:.68rem">${p.strategy||''}</span></td>
          <td><span class="badge b${p.side[0]}">${p.side.toUpperCase()}</span></td>
          <td>$${p.entry_price.toLocaleString('en',{minimumFractionDigits:4,maximumFractionDigits:6})}</td>
          <td>$${p.size_usd.toFixed(2)}</td>
          <td>${lp}</td>
          <td>${pnlStr}</td>
          <td class="muted">${p.stop_loss != null ? '$'+p.stop_loss.toFixed(4) : '—'}</td>
          <td class="muted">${p.take_profit != null ? '$'+p.take_profit.toFixed(4) : '—'}</td>
          <td class="muted" style="font-size:.72rem">${p.opened_at}</td>
          <td><button class="btn btn-xs btn-close-pos" onclick="closePosition('${coin}')">Close</button></td>
        </tr>`;
      }).join('');
      posDiv.innerHTML = `<table><thead><tr>
        <th>Coin</th><th>Side</th><th>Entry</th><th>Value</th>
        <th>Live Price</th><th>Unreal P&amp;L</th><th>SL</th><th>TP</th><th>Opened</th><th></th>
        </tr></thead><tbody>${rows}</tbody></table>`;
    }
  } catch(e) { $('last-updated').textContent = 'Connection error — retrying…'; }
}

initCollapsibleRows();

// ── Performance polling (every 30 s) ──────────────────────────────────────
async function fetchPerformance() {
  try {
    const d = await fetch('/api/performance').then(r => r.json());
    const s = d.stats || {};

    // Cards from stats
    if (s.win_rate != null) {
      const wrEl = $('c-wr');
      wrEl.textContent = s.win_rate.toFixed(1) + '%';
      wrEl.className   = 'val ' + (s.win_rate >= 50 ? 'green' : 'red');
    }
    $('c-trades').textContent = (s.total_trades||0) + ' trades';
    const pfEl = $('c-pf');
    if (s.profit_factor != null) {
      pfEl.textContent = s.profit_factor >= 999 ? '∞' : s.profit_factor.toFixed(2);
      pfEl.className   = 'val ' + (s.profit_factor >= 1.2 ? 'green' : s.profit_factor >= 1.0 ? 'yellow' : 'red');
    }
    const ddEl = $('c-dd');
    if (s.max_drawdown != null) {
      ddEl.textContent = s.max_drawdown.toFixed(1) + '%';
      ddEl.className   = 'val ' + (s.max_drawdown > 10 ? 'red' : s.max_drawdown > 5 ? 'yellow' : 'green');
    }
    const todayEl = $('c-today');
    if (s.today_pnl != null) {
      todayEl.textContent = fmt(s.today_pnl);
      todayEl.className   = 'val ' + (s.today_pnl >= 0 ? 'green' : 'red');
      $('c-today-n').textContent = (s.today_trades||0) + ' trades today';
    }
    if (s.total_fees != null) $('c-fees').textContent = '$' + s.total_fees.toFixed(4);

    // Stats grid
    const sg = $('stats-grid');
    const statItems = [
      ['Avg Win',       s.avg_win  != null ? '$'+s.avg_win.toFixed(2)  : '—', 'green'],
      ['Avg Loss',      s.avg_loss != null ? '$'+s.avg_loss.toFixed(2) : '—', 'red'],
      ['Sharpe Ratio',  s.sharpe_ratio != null ? s.sharpe_ratio.toFixed(3) : '—',
                        s.sharpe_ratio >= 1.0 ? 'green' : s.sharpe_ratio > 0 ? 'yellow' : 'red'],
      ['Sortino Ratio', s.sortino_ratio != null ? (s.sortino_ratio >= 999 ? '∞' : s.sortino_ratio.toFixed(3)) : '—',
                        s.sortino_ratio >= 1.5 ? 'green' : s.sortino_ratio > 0 ? 'yellow' : 'red'],
      ['Brier Score',   s.brier_score  != null ? s.brier_score.toFixed(4) : '—',
                        s.brier_score < 0.15 ? 'green' : s.brier_score < 0.20 ? 'yellow' : 'red'],
      ['Max Consec Loss', s.max_consec_losses ?? '—', 'text'],
      ['Best Trade',    s.best_trade  != null ? fmt(s.best_trade)  : '—', 'green'],
      ['Worst Trade',   s.worst_trade != null ? fmt(s.worst_trade) : '—', 'red'],
    ];
    sg.innerHTML = statItems.map(([lbl,val,cls]) =>
      `<div class="stat-item"><div class="slbl">${lbl}</div>
       <div class="sval ${cls}">${val}</div></div>`).join('');

    // Equity chart
    const eq = d.equity || {labels:[], values:[]};
    if (equityChart) {
      equityChart.data.labels   = eq.labels;
      equityChart.data.datasets[0].data = eq.values;
      equityChart.update('none');
    } else if (eq.labels.length) {
      equityChart = new Chart($('equity-chart'), {
        type: 'line',
        data: { labels: eq.labels, datasets: [{
          label: 'Capital ($)', data: eq.values,
          borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,0.08)',
          fill: true, tension: .3, pointRadius: eq.values.length > 60 ? 0 : 3, borderWidth: 2
        }]},
        options: { responsive:true, maintainAspectRatio:true,
          plugins:{legend:{display:false}},
          scales:{ x:{ticks:{color:'#8b949e',maxTicksLimit:6},grid:{color:'#21262d'}},
                   y:{ticks:{color:'#8b949e',callback:v=>'$'+v},grid:{color:'#21262d'}} }}
      });
    }

    // Coin P&L chart
    const co = d.coins || {labels:[], values:[]};
    if (coinChart) {
      coinChart.data.labels   = co.labels;
      coinChart.data.datasets[0].data = co.values;
      coinChart.data.datasets[0].backgroundColor = co.values.map(v => v>=0?'#3fb950':'#f85149');
      coinChart.update('none');
    } else if (co.labels.length) {
      coinChart = new Chart($('coin-chart'), {
        type: 'bar',
        data: { labels: co.labels, datasets: [{
          label: 'P&L ($)', data: co.values,
          backgroundColor: co.values.map(v => v>=0?'#3fb950':'#f85149'), borderRadius: 4
        }]},
        options: { responsive:true, maintainAspectRatio:true,
          plugins:{legend:{display:false}},
          scales:{ x:{ticks:{color:'#8b949e'},grid:{color:'#21262d'}},
                   y:{ticks:{color:'#8b949e',callback:v=>'$'+v},grid:{color:'#21262d'}} }}
      });
    }

    // Trades table
    fetchTrades();
  } catch(e) { console.error('perf fetch failed', e); }
}

// ── Trades ─────────────────────────────────────────────────────────────────
async function fetchTrades() {
  try {
    const d = await fetch('/api/trades?n=50').then(r => r.json());
    const trades = d.trades || [];
    $('trades-count').textContent = trades.length;
    if (!trades.length) {
      $('trades-table').innerHTML = '<p class="empty">No closed trades yet.</p>';
      return;
    }
    const rows = trades.map(t => {
      const pnl    = parseFloat(t.pnl||0);
      const pnlCls = pnl >= 0 ? 'green' : 'red';
      return `<tr>
        <td class="muted" style="font-size:.72rem">${(t.timestamp||'').slice(0,16)}</td>
        <td><b>${t.coin||'?'}</b></td>
        <td><span class="badge b${(t.side||'?')[0]}">${(t.side||'?').toUpperCase()}</span></td>
        <td>$${parseFloat(t.entry_price||0).toFixed(4)}</td>
        <td>$${parseFloat(t.exit_price||0).toFixed(4)}</td>
        <td class="${pnlCls}">${fmt(pnl)}</td>
        <td class="muted">${parseFloat(t.pnl_pct||0).toFixed(2)}%</td>
        <td class="muted">${t.duration_min||'?'} min</td>
        <td>${pill(t.reason||'')}</td>
      </tr>`;
    }).join('');
    $('trades-table').innerHTML = `<table><thead><tr>
      <th>Time</th><th>Coin</th><th>Side</th><th>Entry</th><th>Exit</th>
      <th>P&amp;L</th><th>%</th><th>Dur</th><th>Outcome</th>
      </tr></thead><tbody>${rows}</tbody></table>`;
  } catch(e) {}
}

// ── Coins ──────────────────────────────────────────────────────────────────
async function fetchCoins() {
  try {
    const d = await fetch('/api/coins').then(r => r.json());
    const grid = $('coin-grid');
    grid.innerHTML = Object.entries(d).map(([key, cfg]) => {
      const stratLabel = cfg.strategy === 'supertrend' ? '📈 ST' : '🔁 KC';
      const posTag = cfg.has_position ?
        '<span style="color:var(--yellow);font-size:.65rem">● open</span>' : '';
      return `<div class="coin-card">
        <div class="coin-info">
          <div class="name">${key} ${posTag}</div>
          <div class="meta">${stratLabel} · ${cfg.interval} · ${cfg.hl_symbol}</div>
        </div>
        <label class="toggle">
          <input type="checkbox" ${cfg.enabled?'checked':''} onchange="toggleCoin('${key}', this)">
          <span class="toggle-track"></span>
        </label>
      </div>`;
    }).join('');
  } catch(e) {}
}

// ── Log polling (every 5 s) ────────────────────────────────────────────────
async function fetchLog() {
  try {
    const d    = await fetch('/api/log?n=100').then(r => r.json());
    const box  = $('log-box');
    const logs = d.log || [];
    if (!logs.length) return;
    box.innerHTML = logs.slice().reverse().map(e =>
      `<div class="log-row">
        <span class="log-ts">${e.ts}</span>
        <span class="log-coin">${e.coin}</span>
        <span class="log-action ${e.action}">${e.action.toUpperCase()}</span>
        <span class="log-reason">${e.reason}</span>
       </div>`
    ).join('');
  } catch(e) {}
}

// ── Control actions ────────────────────────────────────────────────────────
async function botAction(action) {
  try {
    const r = await fetch('/api/'+action, {method:'POST'}).then(r => r.json());
    if (!r.ok) alert('Error: ' + (r.error||'unknown'));
    else { fetchStatus(); if(action==='pause') fetchStatus(); }
  } catch(e) { alert('Request failed: ' + e); }
}

async function closePosition(coin) {
  if (!confirm('Close ' + coin + ' position now?')) return;
  try {
    const r = await fetch('/api/close/'+coin, {method:'POST'}).then(r=>r.json());
    if (!r.ok) alert('Close failed: '+(r.error||'unknown'));
    else fetchStatus();
  } catch(e) { alert('Request failed: '+e); }
}

async function toggleCoin(coin, el) {
  try {
    const r = await fetch('/api/coin/'+coin+'/toggle', {method:'POST'}).then(r=>r.json());
    if (!r.ok) { el.checked = !el.checked; alert('Toggle failed: '+(r.error||'')); }
  } catch(e) { el.checked = !el.checked; }
}

function confirmEmergency() { $('emerg-modal').classList.add('show'); }
async function doEmergency() {
  closeModal('emerg-modal');
  await botAction('emergency');
}

function openOptimizer() {
  $('opt-modal').classList.add('show');
  $('opt-result').style.display = 'none';
  $('opt-msg').textContent = 'This runs a full grid search on all active coins (3–10 min). Continue?';
  $('opt-run-btn').disabled = false;
  $('opt-run-btn').textContent = 'Run Optimizer';
}
function closeModal(id) { $(id).classList.remove('show'); }

async function runOptimizer() {
  const btn = $('opt-run-btn');
  btn.disabled = true;
  btn.textContent = 'Running…';
  $('opt-msg').textContent = 'Optimizer running — this will take a few minutes. Check back here.';
  try {
    const r = await fetch('/api/optimize', {method:'POST'}).then(r=>r.json());
    if (!r.ok) { $('opt-msg').textContent = 'Error: '+(r.error||'unknown'); btn.disabled=false; return; }
    pollOptimizer();
  } catch(e) { $('opt-msg').textContent = 'Request failed: '+e; btn.disabled=false; }
}

async function pollOptimizer() {
  const r = await fetch('/api/optimize/status').then(r=>r.json());
  $('opt-msg').textContent = r.message;
  if (r.running) { setTimeout(pollOptimizer, 5000); return; }
  $('opt-run-btn').disabled = false;
  $('opt-run-btn').textContent = 'Run Again';
  if (r.result) {
    const pre = $('opt-result');
    pre.style.display = 'block';
    pre.textContent = JSON.stringify(r.result, null, 2);
  }
}

// ── Init & intervals ───────────────────────────────────────────────────────
fetchStatus();
fetchPerformance();
fetchCoins();
fetchLog();
setInterval(fetchStatus,      5000);
setInterval(fetchPerformance, 30000);
setInterval(fetchLog,         5000);
setInterval(fetchCoins,       15000);
</script>
</body>
</html>"""
