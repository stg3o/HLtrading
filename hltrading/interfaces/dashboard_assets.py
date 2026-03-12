"""Static assets for the HTML dashboard."""

DASHBOARD_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ArbyBot Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:#0d1117; --surface:#161b22; --border:#30363d;
    --green:#3fb950; --red:#f85149; --yellow:#d29922;
    --cyan:#58a6ff; --text:#c9d1d9; --muted:#8b949e;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;padding:24px}}
  h1{{color:var(--cyan);font-size:1.4rem;margin-bottom:4px}}
  .sub{{color:var(--muted);font-size:.85rem;margin-bottom:24px}}
  .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:26px}}
  .card{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px}}
  .card .lbl{{color:var(--muted);font-size:.7rem;text-transform:uppercase;letter-spacing:.05em}}
  .card .val{{font-size:1.35rem;font-weight:600;margin-top:4px}}
  .card .sub2{{color:var(--muted);font-size:.72rem;margin-top:3px}}
  .green{{color:var(--green)}} .red{{color:var(--red)}}
  .yellow{{color:var(--yellow)}} .cyan{{color:var(--cyan)}}
  .charts{{display:grid;grid-template-columns:2fr 1fr;gap:12px;margin-bottom:26px}}
  .charts2{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:26px}}
  .cbox{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px}}
  .cbox h2{{font-size:.72rem;color:var(--muted);margin-bottom:10px;text-transform:uppercase;letter-spacing:.05em}}
  canvas{{max-height:200px}}
  
  /* Collapsible sections */
  .collapsible-section{{margin-bottom:26px;border:1px solid var(--border);border-radius:8px;overflow:hidden}}
  .collapsible-header{{
    background:var(--surface);padding:14px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border);
  }}
  .collapsible-header:hover{{background:#1c2128}}
  .collapsible-title{{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;font-weight:600}}
  .collapsible-icon{{color:var(--cyan);font-size:1.2rem}}
  .collapsible-content{{padding:14px;background:var(--surface);display:none}}
  .collapsible-content.active{{display:block}}
  
  section{{margin-bottom:26px}}
  section h2{{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px}}
  table{{width:100%;border-collapse:collapse;font-size:.79rem}}
  th{{background:var(--surface);color:var(--muted);text-align:left;padding:7px 11px;border-bottom:1px solid var(--border);font-weight:500}}
  td{{padding:6px 11px;border-bottom:1px solid #21262d}}
  tr:hover td{{background:#1c2128}}
  .badge{{display:inline-block;padding:2px 7px;border-radius:4px;font-size:.68rem;font-weight:600}}
  .bl{{background:#1f3d2e;color:var(--green)}} .bs{{background:#3d1f1f;color:var(--red)}}
  .pill{{display:inline-block;padding:2px 6px;border-radius:3px;font-size:.68rem;font-weight:600}}
  .pill-tp{{background:#1f3d2e;color:var(--green)}}
  .pill-sl{{background:#3d1f1f;color:var(--red)}}
  .pill-mb{{background:#2d2a1f;color:var(--yellow)}}
  .pill-mc{{background:#1f2a3d;color:var(--cyan)}}
  .outcome-bar{{display:flex;height:8px;border-radius:4px;overflow:hidden;margin-top:6px;gap:2px}}
  .ob-tp{{background:var(--green)}} .ob-sl{{background:var(--red)}}
  .ob-mb{{background:var(--yellow)}} .ob-mc{{background:var(--cyan)}}
  .empty{{color:var(--muted);font-style:italic;padding:12px 0}}
  footer{{color:var(--muted);font-size:.7rem;margin-top:14px;display:flex;justify-content:space-between;align-items:center}}
  .refresh-btn{{background:var(--surface);border:1px solid var(--border);color:var(--cyan);
    padding:4px 12px;border-radius:4px;cursor:pointer;font-size:.75rem}}
  .refresh-btn:hover{{background:#1c2128}}
  @media(max-width:720px){{.charts,.charts2{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<h1>&#x1F916; ArbyBot Dashboard</h1>
<p class="sub">Generated {generated_at} &middot; {mode_label} &middot; {net_label}</p>

<div class="cards">
  <div class="card"><div class="lbl">Capital</div><div class="val cyan">${capital:,.2f}</div></div>
  <div class="card"><div class="lbl">Total P&L</div><div class="val {pnl_class}">{pnl_str}</div><div class="sub2">{return_pct:+.2f}% return</div></div>
  <div class="card"><div class="lbl">Fees Paid</div><div class="val {fees_class}">{fees_str}</div><div class="sub2">{fees_source}</div></div>
  <div class="card"><div class="lbl">Win Rate</div><div class="val {wr_class}">{win_rate:.1f}%</div><div class="sub2">{wins}/{total_trades} trades</div></div>
  <div class="card"><div class="lbl">Profit Factor</div><div class="val {pf_class}">{pf_str}</div><div class="sub2">gross profit / loss</div></div>
  <div class="card"><div class="lbl">Avg Win</div><div class="val green">{avg_win_str}</div><div class="sub2">Avg Loss: <span class="red">{avg_loss_str}</span></div></div>
  <div class="card"><div class="lbl">Max Drawdown</div><div class="val {dd_class}">{max_dd:.1f}%</div></div>
  <div class="card"><div class="lbl">Status</div><div class="val {status_class}">{status}</div></div>
</div>

<div class="charts">
  <div class="cbox"><h2>Equity Curve</h2><canvas id="ec"></canvas></div>
  <div class="cbox"><h2>P&amp;L by Coin</h2><canvas id="cc"></canvas></div>
</div>

<div class="charts2">
  <div class="cbox">
    <h2>Trade Outcomes</h2>
    <canvas id="oc"></canvas>
    <div class="outcome-bar" style="margin-top:10px">
      <div class="ob-tp" style="flex:{tp_pct}"></div>
      <div class="ob-sl" style="flex:{sl_pct}"></div>
      <div class="ob-mb" style="flex:{mb_pct}"></div>
      <div class="ob-mc" style="flex:{mc_pct}"></div>
    </div>
    <div style="display:flex;gap:10px;margin-top:6px;flex-wrap:wrap">
      <span class="pill pill-tp">TP {tp_pct:.0f}%</span>
      <span class="pill pill-sl">SL {sl_pct:.0f}%</span>
      <span class="pill pill-mb">Timeout {mb_pct:.0f}%</span>
      <span class="pill pill-mc">Manual {mc_pct:.0f}%</span>
    </div>
  </div>
  <div class="cbox"><h2>Duration Distribution (min)</h2><canvas id="dc"></canvas></div>
</div>

<div class="collapsible-section">
  <div class="collapsible-header">
    <span class="collapsible-title">Per-Coin Performance</span>
    <span class="collapsible-icon">▼</span>
  </div>
  <div class="collapsible-content active">
    {coin_breakdown_html}
  </div>
</div>

<div class="collapsible-section">
  <div class="collapsible-header">
    <span class="collapsible-title">Open Positions</span>
    <span class="collapsible-icon">▼</span>
  </div>
  <div class="collapsible-content active">
    {positions_html}
  </div>
</div>

<div class="collapsible-section">
  <div class="collapsible-header">
    <span class="collapsible-title">Trade History &mdash; last {shown} of {total_trades}</span>
    <span class="collapsible-icon">▼</span>
  </div>
  <div class="collapsible-content active">
    {trades_html}
  </div>
</div>

<footer>
  <span>dashboard.py &middot; {generated_at}</span>
  <button class="refresh-btn" onclick="location.reload()">&#x21bb; Refresh</button>
</footer>

<script>
// Collapsible sections functionality
document.addEventListener('DOMContentLoaded', function() {{
  // Use a more robust selector to find all collapsible headers
  const headers = document.querySelectorAll('.collapsible-header');
  
  headers.forEach(header => {{
    const icon = header.querySelector('.collapsible-icon');
    const content = header.nextElementSibling;
    
    if (icon && content) {{
      header.addEventListener('click', function() {{
        content.classList.toggle('active');
        icon.textContent = content.classList.contains('active') ? '▼' : '▶';
      }});
    }}
  }});
}});

const eq = {equity_json};
if(eq.labels.length){{
  new Chart(document.getElementById('ec'),{{type:'line',data:{{labels:eq.labels,datasets:[{{label:'Capital ($)',data:eq.values,borderColor:'#58a6ff',backgroundColor:'rgba(88,166,255,0.08)',fill:true,tension:.3,pointRadius:eq.values.length>60?0:3,borderWidth:2}}]}},options:{{responsive:true,maintainAspectRatio:true,plugins:{{legend:{{display:false}}}},scales:{{x:{{ticks:{{color:'#8b949e',maxTicksLimit:8}},grid:{{color:'#21262d'}}}},y:{{ticks:{{color:'#8b949e',callback:v=>'$'+v.toLocaleString()}},grid:{{color:'#21262d'}}}}}}}}}})}};

const co = {coin_json};
if(co.labels.length){{
  new Chart(document.getElementById('cc'),{{type:'bar',data:{{labels:co.labels,datasets:[{{label:'P&L ($)',data:co.values,backgroundColor:co.values.map(v=>v>=0?'#3fb950':'#f85149'),borderRadius:4}}]}},options:{{responsive:true,maintainAspectRatio:true,plugins:{{legend:{{display:false}}}},scales:{{x:{{ticks:{{color:'#8b949e'}},grid:{{color:'#21262d'}}}},y:{{ticks:{{color:'#8b949e',callback:v=>'$'+v}},grid:{{color:'#21262d'}}}}}}}}}})}};

const oc = {outcome_json};
if(oc.values.some(v=>v>0)){{
  new Chart(document.getElementById('oc'),{{type:'doughnut',data:{{labels:oc.labels,datasets:[{{data:oc.values,backgroundColor:['#3fb950','#f85149','#d29922','#58a6ff'],borderWidth:0,hoverOffset:4}}]}},options:{{responsive:true,maintainAspectRatio:true,cutout:'65%',plugins:{{legend:{{position:'right',labels:{{color:'#8b949e',font:{{size:11}}}}}}}}}}}})}};

const dh = {duration_json};
if(dh.labels.length){{
  new Chart(document.getElementById('dc'),{{type:'bar',data:{{labels:dh.labels,datasets:[{{label:'Trades',data:dh.values,backgroundColor:'rgba(88,166,255,0.5)',borderRadius:3,borderWidth:0}}]}},options:{{responsive:true,maintainAspectRatio:true,plugins:{{legend:{{display:false}}}},scales:{{x:{{ticks:{{color:'#8b949e'}},grid:{{color:'#21262d'}}}},y:{{ticks:{{color:'#8b949e',stepSize:1}},grid:{{color:'#21262d'}}}}}}}}}})}};
</script>
</body>
</html>
"""
