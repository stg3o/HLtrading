"""
web_server.py — Flask live dashboard + REST control API

Runs as a daemon thread inside the main bot process (call start() once).
All shared state is injected via init() before start() is called.

Endpoints
─────────
GET  /                       serve the live dashboard SPA
GET  /api/status             bot state + portfolio + open positions
GET  /api/performance        stats + equity series + coin P&L series
GET  /api/trades             last N closed trades
GET  /api/coins              per-coin config + enabled flag
GET  /api/log                rolling scan log (last N entries)
GET  /api/optimize/status    optimizer progress / results
POST /api/start              start bot loop
POST /api/stop               stop bot loop
POST /api/pause              toggle web-controlled pause
POST /api/emergency          stop bot + emergency close all
POST /api/close/<coin>       close a specific open position
POST /api/coin/<coin>/toggle enable / disable a coin in COINS dict
POST /api/optimize           run full optimizer in background thread
"""

from flask import Flask, jsonify, request, Response
from collections import deque
from datetime import datetime
import threading
import json
from interfaces.web_assets import WEB_DASHBOARD_HTML
from interfaces.web_services import (
    HLAccountCache,
    build_coin_pnl_payload,
    build_coins_payload,
    build_equity_payload,
    build_perf_stats,
    build_performance_payload,
    build_positions_data,
    build_recent_trades_payload,
    build_status_payload,
    get_live_price,
)

app = Flask(__name__)

# ── Injected by main.py via init() ───────────────────────────────────────────
_risk         = None   # RiskManager instance
_bot_running  = None   # threading.Event
_start_fn     = None   # start_bot()
_stop_fn      = None   # stop_bot()
_close_fn     = None   # close_trade(coin, risk, reason)
_emergency_fn = None   # emergency_close_all(risk)

# ── Web-controlled pause (independent of Telegram pause) ─────────────────────
_paused      = False
_paused_lock = threading.Lock()

# ── Scan log ring buffer ──────────────────────────────────────────────────────
_scan_log  = deque(maxlen=300)
_scan_lock = threading.Lock()

# ── Optimizer background state ────────────────────────────────────────────────
_opt_status = {"running": False, "message": "idle", "result": None}
_opt_lock   = threading.Lock()

# ── Web server started guard ──────────────────────────────────────────────────
_started = False


# ── Public API (called by main.py) ────────────────────────────────────────────

def init(risk, bot_running, start_fn, stop_fn, close_fn, emergency_fn):
    global _risk, _bot_running, _start_fn, _stop_fn, _close_fn, _emergency_fn
    _risk         = risk
    _bot_running  = bot_running
    _start_fn     = start_fn
    _stop_fn      = stop_fn
    _close_fn     = close_fn
    _emergency_fn = emergency_fn


def is_paused() -> bool:
    with _paused_lock:
        return _paused


def add_log(coin: str, action: str, reason: str = ""):
    """Called by the bot loop after each coin scan to populate the live log."""
    color = "green" if action in ("long", "short") else "muted"
    with _scan_lock:
        _scan_log.append({
            "ts":     datetime.now().strftime("%H:%M:%S"),
            "coin":   coin,
            "action": action,
            "reason": reason[:120],
            "color":  color,
        })


def start(host: str = "0.0.0.0", port: int = 5000):
    """Start the Flask server in a daemon thread. Safe to call multiple times."""
    global _started
    if _started:
        return
    _started = True
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    def _run():
        try:
            app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
        except OSError as e:
            print(f"  [web] Could not start on port {port}: {e}")

    t = threading.Thread(target=_run, daemon=True, name="web_server")
    t.start()
    print(f"  [web] Dashboard running at http://localhost:{port}")
    return t


# ── HL account balance cache (avoids hammering the API on every 5s poll) ─────
_hl_account_cache = HLAccountCache(ttl=30.0)

def _hl_account_cached() -> dict:
    """Return cached HL account info, refreshing if stale."""
    return _hl_account_cache.get()


# ── Data helpers ──────────────────────────────────────────────────────────────

def _live_price(coin: str):
    return get_live_price(coin)


def _positions_data() -> dict:
    return build_positions_data(_risk, live_price_fn=_live_price)


def _perf_stats() -> dict:
    return build_perf_stats()


def _equity_series() -> dict:
    return build_equity_payload()


def _coin_pnl_series() -> dict:
    return build_coin_pnl_payload()


def _recent_trades(n: int = 50) -> list:
    return build_recent_trades_payload(n)


# ── REST routes ───────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    from config import HL_ENABLED

    hl_account = _hl_account_cached() if HL_ENABLED else {}
    return jsonify(build_status_payload(
        risk=_risk,
        bot_running=_bot_running,
        paused=is_paused(),
        hl_account=hl_account,
        last_updated=datetime.now().strftime("%H:%M:%S"),
    ))


@app.route("/api/performance")
def api_performance():
    return jsonify(build_performance_payload(
        stats=_perf_stats(),
        equity=_equity_series(),
        coins=_coin_pnl_series(),
    ))


@app.route("/api/trades")
def api_trades():
    return jsonify({"trades": _recent_trades(int(request.args.get("n", 50)))})


@app.route("/api/coins")
def api_coins():
    return jsonify(build_coins_payload(_risk))


@app.route("/api/log")
def api_log():
    n = int(request.args.get("n", 120))
    with _scan_lock:
        entries = list(_scan_log)[-n:]
    return jsonify({"log": entries})


@app.route("/api/optimize/status")
def api_opt_status():
    with _opt_lock:
        return jsonify(dict(_opt_status))


@app.route("/api/start", methods=["POST"])
def api_start():
    if not _start_fn:
        return jsonify({"ok": False, "error": "Not initialized"}), 500
    try:
        _start_fn()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/stop", methods=["POST"])
def api_stop():
    if not _stop_fn:
        return jsonify({"ok": False, "error": "Not initialized"}), 500
    try:
        _stop_fn()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/pause", methods=["POST"])
def api_pause():
    global _paused
    with _paused_lock:
        _paused = not _paused
        state = _paused
    return jsonify({"ok": True, "paused": state})


@app.route("/api/emergency", methods=["POST"])
def api_emergency():
    if not _emergency_fn or not _risk:
        return jsonify({"ok": False, "error": "Not initialized"}), 500
    try:
        if _stop_fn:
            _stop_fn()
        _emergency_fn(_risk)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/close/<coin>", methods=["POST"])
def api_close(coin):
    if not _close_fn or not _risk:
        return jsonify({"ok": False, "error": "Not initialized"}), 500
    try:
        ok = _close_fn(coin, _risk, reason="web_close")
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/coin/<coin>/toggle", methods=["POST"])
def api_coin_toggle(coin):
    from config import COINS
    if coin not in COINS:
        return jsonify({"ok": False, "error": f"Unknown coin: {coin}"}), 404
    COINS[coin]["enabled"] = not COINS[coin].get("enabled", True)
    return jsonify({"ok": True, "enabled": COINS[coin]["enabled"]})


@app.route("/api/optimize", methods=["POST"])
def api_optimize():
    global _opt_status
    with _opt_lock:
        if _opt_status["running"]:
            return jsonify({"ok": False, "error": "Optimizer already running"}), 409
        _opt_status = {"running": True, "message": "Starting…", "result": None}

    def _run():
        global _opt_status
        try:
            from optimizer import run_optimizer
            with _opt_lock:
                _opt_status["message"] = "Running grid search — this takes a few minutes…"
            results = run_optimizer()
            summary = {}
            for coin, res_list in results.items():
                if res_list:
                    top = res_list[0]
                    summary[coin] = {
                        "pf": round(top.get("profit_factor", 0), 2),
                        "wr": round(top.get("win_rate", 0), 1),
                        "trades": top.get("trades", 0),
                        "params": {k: top[k] for k in
                                   ("st_period", "st_multiplier", "kc_scalar",
                                    "rsi_oversold", "rsi_overbought", "stop_loss_pct")
                                   if k in top},
                    }
            with _opt_lock:
                _opt_status = {"running": False, "message": "Complete ✓", "result": summary}
        except Exception as ex:
            with _opt_lock:
                _opt_status = {"running": False, "message": f"Error: {ex}", "result": None}

    threading.Thread(target=_run, daemon=True, name="optimizer_web").start()
    return jsonify({"ok": True})


@app.route("/")
def index():
    return Response(WEB_DASHBOARD_HTML, mimetype="text/html")
