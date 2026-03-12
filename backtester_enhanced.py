"""
backtester_enhanced.py — Enhanced backtester with walk-forward validation, 
overfitting detection, and statistical significance testing.

Key improvements:
1. Walk-forward validation framework
2. Robustness testing and parameter sensitivity analysis
3. Statistical significance testing
4. Improved backtest accuracy with proper data handling
5. Out-of-sample performance validation
"""
import math
import numpy as np
import pandas as pd
import yfinance as yf
import pandas_ta as ta
from colorama import Fore, Style
import warnings
warnings.filterwarnings('ignore')

from config import (
    KC_PERIOD, KC_SCALAR, MA_FAST, MA_SLOW, MA_TREND, RSI_PERIOD,
    STOP_LOSS_PCT, TAKE_PROFIT_PCT, RISK_PER_TRADE, PAPER_CAPITAL,
    RSI_OVERSOLD, RSI_OVERBOUGHT, COINS,
)
from backtester import _calc_kc_mid, _signal_for_window
from research.metrics import compute_core_backtest_stats
from research.validation import (
    RobustnessTester,
    StatisticalSignificanceTester,
    WalkForwardValidator,
    calculate_overall_score,
)
from research.simulator import run_mean_reversion_simulation, run_supertrend_simulation
from strategy import _safe, _hurst, _supertrend_arrays


# ─── ENHANCED SIMULATION PARAMETERS ───────────────────────────────────────────
_DEFAULT_SIM_PARAMS: dict = {
    "kc_scalar":         KC_SCALAR,
    "rsi_oversold":      RSI_OVERSOLD,
    "rsi_overbought":    RSI_OVERBOUGHT,
    "hurst_cap":         0.62,
    "ma_trend_filter":   True,
    "stop_loss_pct":     STOP_LOSS_PCT,
    "take_profit_pct":   TAKE_PROFIT_PCT,
    "min_rr_ratio":      1.2,
    "max_bars_in_trade": 36,
    "st_period":         10,
    "st_multiplier":     3.0,
}

_WARMUP = max(MA_TREND, KC_PERIOD, RSI_PERIOD) + 10


# ─── ENHANCED BACKTESTING FUNCTIONS ───────────────────────────────────────────

def run_enhanced_backtest(coin: str, coin_cfg: dict, period: str = "365d", 
                         params: dict | None = None, silent: bool = False) -> dict:
    """
    Enhanced backtest with accuracy improvements and comprehensive validation.
    
    Returns: {
        "baseline": baseline backtest results,
        "walk_forward": walk-forward validation results,
        "robustness": robustness testing results,
        "significance": statistical significance test results,
        "overall_score": composite performance score
    }
    """
    if not silent:
        print(f"\n  {Fore.CYAN}=== ENHANCED BACKTEST: {coin} ==={Style.RESET_ALL}")
    
    # 1. Run baseline backtest with improved accuracy
    baseline_result = run_baseline_backtest(coin, coin_cfg, period, params, silent)
    
    if baseline_result.get("total_trades", 0) < 10:
        return {"error": "Insufficient trades for comprehensive analysis", "baseline": baseline_result}
    
    # 2. Run walk-forward validation
    wfv = WalkForwardValidator(coin, coin_cfg, _simulate_validation_backtest, _compute_validation_metrics)
    walk_forward_result = wfv.run_walk_forward(params, silent)
    
    # 3. Run robustness testing
    rt = RobustnessTester(coin, coin_cfg, _simulate_validation_backtest, _compute_validation_metrics)
    robustness_result = rt.run_robustness_test(params or {}, num_scenarios=50)
    
    # 4. Run statistical significance testing
    sst = StatisticalSignificanceTester(coin, coin_cfg, _simulate_validation_backtest, _compute_validation_metrics)
    significance_result = sst.run_significance_test(params or {}, num_bootstraps=500)
    
    # 5. Calculate overall score
    overall_score = calculate_overall_score(baseline_result, walk_forward_result,
                                            robustness_result, significance_result)
    
    return {
        "coin": coin,
        "baseline": baseline_result,
        "walk_forward": walk_forward_result,
        "robustness": robustness_result,
        "significance": significance_result,
        "overall_score": overall_score,
        "timestamp": pd.Timestamp.now().isoformat()
    }


def run_baseline_backtest(coin: str, coin_cfg: dict, period: str = "365d",
                         params: dict | None = None, silent: bool = False) -> dict:
    """Run baseline backtest with improved accuracy."""
    p = {**_DEFAULT_SIM_PARAMS, **(params or {})}
    ticker = coin_cfg["ticker"]
    interval = coin_cfg["interval"]

    if not silent:
        print(f"  {Fore.CYAN}Fetching {coin} ({ticker}, {interval}, {period})…{Style.RESET_ALL}")
    
    # Enhanced data fetching with error handling
    df = _fetch_enhanced(ticker, interval, period)
    if df is None:
        return {"coin": coin, "total_trades": 0, "error": "data download failed"}

    min_bars = _WARMUP + 20
    if len(df) < min_bars:
        return {"coin": coin, "total_trades": 0,
                "error": f"only {len(df)} bars — need {min_bars} minimum"}

    try:
        date_range_days = (df.index[-1] - df.index[0]).days
    except Exception:
        date_range_days = 365

    if not silent:
        print(f"  {Fore.WHITE}{len(df)} bars ({date_range_days}d).{Style.RESET_ALL}")

    # Run appropriate strategy
    if coin_cfg.get("strategy_type") == "supertrend":
        trades, final_capital, equity_curve = _run_supertrend_sim(df, p)
    else:
        trades, final_capital, equity_curve = _run_mean_reversion_sim(df, p)

    stats = _compute_enhanced_stats(coin, trades, final_capital, equity_curve,
                                   period, date_range_days)
    stats["strategy_type"] = coin_cfg.get("strategy_type", "mean_reversion")
    stats["interval"] = interval
    
    # Add parameter tracking
    for key, value in p.items():
        stats[f"param_{key}"] = value
    
    return stats


def _fetch_enhanced(ticker: str, interval: str, period: str) -> pd.DataFrame | None:
    """Enhanced data fetching with better error handling and validation."""
    try:
        df = yf.download(ticker, interval=interval, period=period,
                        auto_adjust=True, progress=False, timeout=60)
        if df is None or df.empty:
            return None
        
        # Validate data quality
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df.dropna(inplace=True)
        
        # Check for sufficient data and reasonable price ranges
        if len(df) < 100:
            return None
        
        price_range = df["Close"].max() - df["Close"].min()
        if price_range <= 0:
            return None
        
        # Remove extreme outliers (likely data errors)
        q1 = df["Close"].quantile(0.25)
        q3 = df["Close"].quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - 3 * iqr
        upper_bound = q3 + 3 * iqr
        df = df[(df["Close"] >= lower_bound) & (df["Close"] <= upper_bound)]
        
        return df
    except Exception as e:
        print(Fore.RED + f"  Enhanced data fetch error for {ticker}: {e}")
        return None


def _run_mean_reversion_sim(df: pd.DataFrame, p: dict) -> tuple[list, float, list]:
    """Compatibility wrapper for the shared mean-reversion simulation loop."""
    return run_mean_reversion_simulation(
        df,
        p,
        paper_capital=PAPER_CAPITAL,
        risk_per_trade=RISK_PER_TRADE,
        warmup=_WARMUP,
        calc_kc_mid=_calc_kc_mid,
        signal_for_window=_signal_for_window,
        include_timestamps=True,
    )


def _run_supertrend_sim(df: pd.DataFrame, p: dict) -> tuple[list, float, list]:
    """Compatibility wrapper for the shared Supertrend simulation loop."""
    return run_supertrend_simulation(
        df,
        p,
        paper_capital=PAPER_CAPITAL,
        risk_per_trade=RISK_PER_TRADE,
        supertrend_arrays=_supertrend_arrays,
        include_timestamps=True,
    )


def _compute_enhanced_stats(coin: str, trades: list, final_capital: float,
                           equity_curve: list, period: str,
                           date_range_days: int = 60) -> dict:
    """Enhanced statistics computation with additional metrics."""
    core_stats = compute_core_backtest_stats(
        coin=coin,
        trades=trades,
        final_capital=final_capital,
        equity_curve=equity_curve,
        period=period,
        date_range_days=date_range_days,
        starting_capital=PAPER_CAPITAL,
    )
    if core_stats.get("total_trades", 0) == 0:
        return core_stats

    pnls = [t["pnl"] for t in trades]

    # Enhanced drawdown calculation
    peak = equity_curve[0] if equity_curve else float(PAPER_CAPITAL)
    max_dd = 0.0
    dd_duration = 0
    max_dd_duration = 0
    current_dd_duration = 0
    
    for v in equity_curve:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)
        
        if dd > 0:
            current_dd_duration += 1
            max_dd_duration = max(max_dd_duration, current_dd_duration)
        else:
            current_dd_duration = 0

    # Additional enhanced metrics
    calmar_ratio = core_stats["pct_return"] / max_dd if max_dd > 0 else 0
    ulcer_index = math.sqrt(sum((dd / 100) ** 2 for dd in equity_curve) / len(equity_curve)) if equity_curve else 0
    max_risk_exposure = max(sum(1 for t in trades if t["bars"] <= i) for i in range(max(t["bars"] for t in trades) + 1)) if trades else 0

    return {
        **core_stats,
        "max_drawdown": round(max_dd, 1),
        "max_drawdown_duration": max_dd_duration,
        "calmar_ratio": round(calmar_ratio, 3),
        "ulcer_index": round(ulcer_index, 4),
        "max_risk_exposure": max_risk_exposure,
        "enhanced_metrics": True,
    }


def _simulate_validation_backtest(df: pd.DataFrame, coin_cfg: dict, params: dict) -> tuple[list, float, list]:
    if coin_cfg.get("strategy_type") == "supertrend":
        return _run_supertrend_sim(df, params)
    return _run_mean_reversion_sim(df, params)


def _compute_validation_metrics(df: pd.DataFrame, trades: list, final_capital: float,
                                equity_curve: list, label: str) -> dict:
    try:
        date_range_days = (df.index[-1] - df.index[0]).days
    except Exception:
        date_range_days = 365
    return _compute_enhanced_stats("validation", trades, final_capital, equity_curve,
                                   label, date_range_days)


def print_enhanced_results(result: dict) -> None:
    """Print comprehensive enhanced backtest results."""
    if "error" in result:
        print(f"\n  {Fore.RED}Error: {result['error']}{Style.RESET_ALL}")
        return
    
    coin = result["coin"]
    baseline = result["baseline"]
    
    print(f"\n  {Fore.CYAN}{'='*60}")
    print(f"  {Fore.CYAN}ENHANCED BACKTEST RESULTS: {coin}")
    print(f"  {Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    
    # Baseline results
    print(f"\n  {Fore.YELLOW}BASELINE PERFORMANCE{Style.RESET_ALL}")
    if baseline.get("total_trades", 0) > 0:
        pnl_c = Fore.GREEN if baseline["total_pnl"] >= 0 else Fore.RED
        print(f"  Total trades: {baseline['total_trades']}")
        print(f"  Win rate: {baseline['win_rate']:.1f}%")
        print(f"  Total P&L: {pnl_c}${baseline['total_pnl']:+,.2f} ({baseline['pct_return']:+.1f}%){Style.RESET_ALL}")
        print(f"  Profit factor: {baseline['profit_factor']:.2f}")
        print(f"  Sharpe ratio: {baseline['sharpe_ratio']}")
        print(f"  Sortino ratio: {baseline['sortino_ratio']}")
        print(f"  Max drawdown: {baseline['max_drawdown']:.1f}%")
        print(f"  Calmar ratio: {baseline['calmar_ratio']:.3f}")
    else:
        print(f"  {Fore.RED}No trades generated{Style.RESET_ALL}")
    
    # Walk-forward validation
    print(f"\n  {Fore.YELLOW}WALK-FORWARD VALIDATION{Style.RESET_ALL}")
    wf = result.get("walk_forward", {})
    if isinstance(wf, dict) and "iterations" in wf:
        print(f"  Iterations: {wf['iterations']}")
        print(f"  In-sample avg return: {wf['is_avg_return']:.2f}%")
        print(f"  Out-of-sample avg return: {wf['oos_avg_return']:.2f}%")
        print(f"  IS/OOS correlation: {wf['is_oos_correlation']:.3f}")
        print(f"  Performance decay: {wf['performance_decay']:.3f}")
        print(f"  Overfitting score: {wf['overfitting_score']:.1f}/100")
    else:
        print(f"  {Fore.RED}Walk-forward validation failed{Style.RESET_ALL}")
    
    # Robustness testing
    print(f"\n  {Fore.YELLOW}ROBUSTNESS TESTING{Style.RESET_ALL}")
    rob = result.get("robustness", {})
    if isinstance(rob, dict) and "scenarios_tested" in rob:
        print(f"  Scenarios tested: {rob['scenarios_tested']}")
        print(f"  Robustness score: {rob['robustness_score']:.1f}/100")
        print(f"  Return std dev: {rob['return_stats']['std']:.2f}%")
        print(f"  Sharpe std dev: {rob['sharpe_stats']['std']:.3f}")
    else:
        print(f"  {Fore.RED}Robustness testing failed{Style.RESET_ALL}")
    
    # Statistical significance
    print(f"\n  {Fore.YELLOW}STATISTICAL SIGNIFICANCE{Style.RESET_ALL}")
    sig = result.get("significance", {})
    if isinstance(sig, dict) and "p_value" in sig:
        print(f"  Baseline return: {sig['baseline_return']:.2f}%")
        print(f"  P-value: {sig['p_value']:.4f}")
        print(f"  95% significant: {'Yes' if sig['significant_95'] else 'No'}")
        print(f"  Effect size (Cohen's d): {sig['effect_size']:.3f}")
        ci = sig['confidence_interval_95']
        print(f"  95% CI: ({ci[0]:.2f}%, {ci[1]:.2f}%)")
    else:
        print(f"  {Fore.RED}Significance testing failed{Style.RESET_ALL}")
    
    # Overall score
    print(f"\n  {Fore.CYAN}OVERALL SCORE: {result['overall_score']:.1f}/100{Style.RESET_ALL}")
    
    # Interpretation
    score = result['overall_score']
    if score >= 80:
        interpretation = f"{Fore.GREEN}Excellent{Style.RESET_ALL} - Strategy shows strong performance with good robustness"
    elif score >= 60:
        interpretation = f"{Fore.YELLOW}Good{Style.RESET_ALL} - Strategy performs well but may need refinement"
    elif score >= 40:
        interpretation = f"{Fore.YELLOW}Fair{Style.RESET_ALL} - Strategy shows potential but has significant issues"
    else:
        interpretation = f"{Fore.RED}Poor{Style.RESET_ALL} - Strategy needs major improvements"
    
    print(f"  Assessment: {interpretation}")
    print(f"\n  {Fore.CYAN}{'='*60}{Style.RESET_ALL}")
