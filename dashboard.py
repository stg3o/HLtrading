"""
dashboard.py — HTML dashboard generator

Reads live data from:
  - trade_history.csv  (via trade_log.load_trades)
  - paper_state.json   (via risk_manager.load_state)

Generates a self-contained HTML file with Chart.js charts,
then opens it in the default browser via run().
"""
import json
from pathlib import Path
from datetime import datetime

from config import BASE_DIR, PAPER_CAPITAL


# ─── HTML TEMPLATE ────────────────────────────────────────────────────────────

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Keltner Bot Dashboard</title>
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
  .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px;margin-bottom:26px}}
  .card{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px}}
  .card .lbl{{color:var(--muted);font-size:.7rem;text-transform:uppercase;letter-spacing:.05em}}
  .card .val{{font-size:1.4rem;font-weight:600;margin-top:4px}}
  .green{{color:var(--green)}} .red{{color:var(--red)}} .yellow{{color:var(--yellow)}} .cyan{{color:var(--cyan)}}
  .charts{{display:grid;grid-template-columns:2fr 1fr;gap:12px;margin-bottom:26px}}
  .cbox{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px}}
  .cbox h2{{font-size:.72rem;color:var(--muted);margin-bottom:10px;text-transform:uppercase;letter-spacing:.05em}}
  canvas{{max-height:220px}}
  section{{margin-bottom:26px}}
  section h2{{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px}}
  table{{width:100%;border-collapse:collapse;font-size:.79rem}}
  th{{background:var(--surface);color:var(--muted);text-align:left;padding:7px 11px;border-bottom:1px solid var(--border);font-weight:500}}
  td{{padding:6px 11px;border-bottom:1px solid #21262d}}
  tr:hover td{{background:#1c2128}}
  .badge{{display:inline-block;padding:2px 7px;border-radius:4px;font-size:.68rem;font-weight:600}}
  .bl{{background:#1f3d2e;color:var(--green)}} .bs{{background:#3d1f1f;color:var(--red)}}
  .empty{{color:var(--muted);font-style:italic;padding:12px 0}}
  footer{{color:var(--muted);font-size:.7rem;margin-top:14px;text-align:right}}
  @media(max-width:720px){{.charts{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<h1>&#x1F916; Keltner Bot Dashboard</h1>
<p class="sub">Generated {generated_at} &middot; Paper Trading</p>

<div class="cards">
  <div class="card"><div class="lbl">Capital</div><div class="val cyan">${capital:,.2f}</div></div>
  <div class="card"><div class="lbl">Total P&amp;L</div><div class="val {pnl_class}">{pnl_str}</div></div>
  <div class="card"><div class="lbl">Return</div><div class="val {pnl_class}">{return_pct:+.2f}%</div></div>
  <div class="card"><div class="lbl">Win Rate</div><div class="val {wr_class}">{win_rate:.1f}%</div></div>
  <div class="card"><div class="lbl">Trades</div><div class="val">{total_trades}</div></div>
  <div class="card"><div class="lbl">Max Drawdown</div><div class="val {dd_class}">{max_dd:.1f}%</div></div>
  <div class="card"><div class="lbl">Status</div><div class="val {status_class}">{status}</div></div>
</div>

<div class="charts">
  <div class="cbox"><h2>Equity Curve</h2><canvas id="ec"></canvas></div>
  <div class="cbox"><h2>P&amp;L by Coin</h2><canvas id="cc"></canvas></div>
</div>

<section>
  <h2>Open Positions</h2>
  {positions_html}
</section>

<section>
  <h2>Trade History &mdash; last {shown} of {total_trades}</h2>
  {trades_html}
</section>

<footer>dashboard.py &middot; {generated_at}</footer>

<script>
const eq = {equity_json};
const co = {coin_json};
if(eq.labels.length){{
  new Chart(document.getElementById('ec'),{{type:'line',data:{{labels:eq.labels,datasets:[{{label:'Capital ($)',data:eq.values,borderColor:'#58a6ff',backgroundColor:'rgba(88,166,255,0.08)',fill:true,tension:.3,pointRadius:eq.values.length>60?0:3,borderWidth:2}}]}},options:{{responsive:true,maintainAspectRatio:true,plugins:{{legend:{{display:false}}}},scales:{{x:{{ticks:{{color:'#8b949e',maxTicksLimit:8}},grid:{{color:'#21262d'}}}},y:{{ticks:{{color:'#8b949e',callback:v=>'$'+v.toLocaleString()}},grid:{{color:'#21262d'}}}}}}}}}})}};
if(co.labels.length){{
  new Chart(document.getElementById('cc'),{{type:'bar',data:{{labels:co.labels,datasets:[{{label:'P&L ($)',data:co.values,backgroundColor:co.values.map(v=>v>=0?'#3fb950':'#f85149'),borderRadius:4}}]}},options:{{responsive:true,maintainAspectRatio:true,plugins:{{legend:{{display:false}}}},scales:{{x:{{ticks:{{color:'#8b949e'}},grid:{{color:'#21262d'}}}},y:{{ticks:{{color:'#8b949e',callback:v=>'$'+v}},grid:{{color:'#21262d'}}}}}}}}}})}};
</script>
</body>
</html>
"""


# ─── DATA HELPERS ─────────────────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        from risk_manager import load_state
        return load_state()
    except Exception:
        return {}


def _load_trades() -> list[dict]:
    try:
        from trade_log import load_trades
        return load_trades()
    except Exception:
        return []


def _positions_html(positions: dict) -> str:
    if not positions:
        return '<p class="empty">No open positions.</p>'
    rows = "".join(
        f"<tr><td>{coin}</td>"
        f'<td><span class="badge b{pos["side"][0]}">{pos["side"].upper()}</span></td>'
        f"<td>${float(pos.get('entry_price',0)):,.4f}</td>"
        f"<td>${float(pos.get('stop_loss',0)):,.4f}</td>"
        f"<td>${float(pos.get('take_profit',0)):,.4f}</td>"
        f"<td>{pos.get('size_units',0)} u</td>"
        f"<td>{str(pos.get('opened_at',''))[:16]}</td></tr>"
        for coin, pos in positions.items()
    )
    return (
        "<table><thead><tr><th>Coin</th><th>Side</th><th>Entry</th>"
        "<th>SL</th><th>TP</th><th>Size</th><th>Opened</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _trades_html(trades: list[dict]) -> str:
    if not trades:
        return '<p class="empty">No closed trades yet.</p>'
    rows = "".join(
        f"<tr><td>{str(t.get('timestamp',''))[:16]}</td>"
        f"<td>{t.get('coin','?')}</td>"
        f'<td><span class="badge b{str(t.get("side","?"))[0]}">{str(t.get("side","?")).upper()}</span></td>'
        f"<td>${float(t.get('entry_price',0)):,.4f}</td>"
        f"<td>${float(t.get('exit_price',0)):,.4f}</td>"
        f'<td class="{"green" if float(t.get("pnl",0))>=0 else "red"}">'
        f'${float(t.get("pnl",0)):+,.2f}</td>'
        f"<td>{float(t.get('pnl_pct',0)):+.2f}%</td>"
        f"<td>{t.get('duration_min','?')} min</td>"
        f"<td>{t.get('reason','')}</td></tr>"
        for t in reversed(trades[-100:])
    )
    return (
        "<table><thead><tr><th>Time</th><th>Coin</th><th>Side</th>"
        "<th>Entry</th><th>Exit</th><th>P&amp;L</th><th>%</th>"
        "<th>Duration</th><th>Reason</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _equity_series(trades: list[dict]) -> str:
    labels, values, cap = [], [], PAPER_CAPITAL
    for t in trades:
        cap += float(t.get("pnl", 0))
        labels.append(str(t.get("timestamp", ""))[:10])
        values.append(round(cap, 2))
    return json.dumps({"labels": labels, "values": values})


def _coin_series(trades: list[dict]) -> str:
    by: dict[str, float] = {}
    for t in trades:
        c = t.get("coin", "?")
        by[c] = round(by.get(c, 0.0) + float(t.get("pnl", 0)), 2)
    return json.dumps({"labels": list(by), "values": list(by.values())})


# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

def run() -> Path | None:
    """
    Generate dashboard.html from live trade data and open it in the browser.
    Returns the path to the file.
    """
    state  = _load_state()
    trades = _load_trades()

    capital   = float(state.get("capital",     PAPER_CAPITAL))
    peak      = float(state.get("equity_peak", PAPER_CAPITAL))
    positions = state.get("positions", {})
    total_tr  = int(state.get("total_trades",  len(trades)))
    wins_cnt  = int(state.get("wins", sum(1 for t in trades if float(t.get("pnl", 0)) > 0)))
    emergency = bool(state.get("emergency_stop", False))
    halted    = bool(state.get("trading_halted",  False))

    total_pnl  = capital - PAPER_CAPITAL
    return_pct = total_pnl / PAPER_CAPITAL * 100
    win_rate   = wins_cnt / total_tr * 100 if total_tr > 0 else 0.0

    if trades:
        cap, pk, max_dd = PAPER_CAPITAL, PAPER_CAPITAL, 0.0
        for t in trades:
            cap += float(t.get("pnl", 0))
            pk   = max(pk, cap)
            max_dd = max(max_dd, (pk - cap) / pk * 100 if pk else 0)
    else:
        max_dd = (peak - capital) / peak * 100 if peak > 0 else 0.0

    if emergency:
        status, status_class = "EMERGENCY STOP", "red"
    elif halted:
        status, status_class = "HALTED", "yellow"
    else:
        status, status_class = "ACTIVE", "green"

    shown = min(100, len(trades))
    html  = _HTML.format(
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M"),
        capital      = capital,
        pnl_str      = f"${total_pnl:+,.2f}",
        pnl_class    = "green" if total_pnl >= 0 else "red",
        return_pct   = return_pct,
        win_rate     = win_rate,
        wr_class     = "green" if win_rate >= 50 else "red",
        total_trades = total_tr,
        shown        = shown,
        max_dd       = max_dd,
        dd_class     = "red" if max_dd > 10 else "yellow" if max_dd > 5 else "green",
        status       = status,
        status_class = status_class,
        positions_html = _positions_html(positions),
        trades_html    = _trades_html(trades),
        equity_json    = _equity_series(trades),
        coin_json      = _coin_series(trades),
    )

    out = BASE_DIR / "dashboard.html"
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    p = run()
    if p:
        import webbrowser
        webbrowser.open(f"file://{p}")
        print(f"Dashboard written to {p}")
