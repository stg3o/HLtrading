"""Research-only validation and robustness helpers for enhanced backtesting."""
from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf
from colorama import Fore, Style


class WalkForwardValidator:
    """Walk-forward validation framework for robust strategy testing."""

    def __init__(
        self,
        coin: str,
        coin_cfg: dict,
        simulate_backtest,
        compute_metrics,
        total_bars: int = 5000,
        lookback_bars: int = 1000,
        test_bars: int = 200,
    ):
        self.coin = coin
        self.coin_cfg = coin_cfg
        self.simulate_backtest = simulate_backtest
        self.compute_metrics = compute_metrics
        self.total_bars = total_bars
        self.lookback_bars = lookback_bars
        self.test_bars = test_bars
        self.validation_results = []

    def run_walk_forward(self, params: dict | None = None, silent: bool = False) -> dict:
        ticker = self.coin_cfg["ticker"]
        interval = self.coin_cfg["interval"]

        if not silent:
            print(f"  {Fore.CYAN}Fetching {self.coin} for walk-forward validation...{Style.RESET_ALL}")

        df = self._fetch_extended_data(ticker, interval)
        if df is None or len(df) < self.total_bars:
            return {"error": "Insufficient data for walk-forward validation"}

        max_start = len(df) - self.lookback_bars - self.test_bars
        if max_start < 0:
            return {"error": "Data too short for specified walk-forward parameters"}

        results = []
        for start_idx in range(0, max_start, self.test_bars):
            end_idx = start_idx + self.lookback_bars + self.test_bars
            window_df = df.iloc[start_idx:end_idx].copy()

            is_end = self.lookback_bars
            is_df = window_df.iloc[:is_end].copy()
            oos_df = window_df.iloc[is_end:].copy()

            is_result = self._run_single_backtest(is_df, params, "in-sample")
            oos_result = self._run_single_backtest(oos_df, params, "out-of-sample")

            if is_result and oos_result:
                results.append({
                    "is_result": is_result,
                    "oos_result": oos_result,
                    "period": f"{window_df.index[0].strftime('%Y-%m-%d')} to {window_df.index[-1].strftime('%Y-%m-%d')}",
                })

        return self._calculate_walk_forward_metrics(results)

    def _fetch_extended_data(self, ticker: str, interval: str) -> pd.DataFrame | None:
        try:
            df = yf.download(ticker, interval=interval, period="2y",
                             auto_adjust=True, progress=False, timeout=30)
            if df is None or df.empty:
                return None
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df.dropna(inplace=True)
            return df
        except Exception as exc:
            print(Fore.RED + f"  Data fetch error for {ticker}: {exc}")
            return None

    def _run_single_backtest(self, df: pd.DataFrame, params: dict | None, label: str) -> dict | None:
        if len(df) < 10:
            return None
        try:
            trades, final_capital, equity_curve = self.simulate_backtest(df, self.coin_cfg, params or {})
            return self.compute_metrics(df, trades, final_capital, equity_curve, label)
        except Exception as exc:
            print(Fore.RED + f"  Backtest error ({label}): {exc}")
            return None

    def _calculate_walk_forward_metrics(self, results: list) -> dict:
        if not results:
            return {"error": "No valid walk-forward iterations completed"}

        is_returns = []
        oos_returns = []
        is_sharpe = []
        oos_sharpe = []
        is_max_dd = []
        oos_max_dd = []

        for result in results:
            is_ret = result["is_result"]["pct_return"] / 100
            oos_ret = result["oos_result"]["pct_return"] / 100

            is_returns.append(is_ret)
            oos_returns.append(oos_ret)
            is_sharpe.append(result["is_result"]["sharpe_ratio"])
            oos_sharpe.append(result["oos_result"]["sharpe_ratio"])
            is_max_dd.append(result["is_result"]["max_drawdown"])
            oos_max_dd.append(result["oos_result"]["max_drawdown"])

        correlation = np.corrcoef(is_returns, oos_returns)[0, 1] if len(is_returns) > 1 else 0
        decay_factor = np.mean(oos_returns) / np.mean(is_returns) if np.mean(is_returns) != 0 else 0

        return {
            "iterations": len(results),
            "is_avg_return": np.mean(is_returns) * 100,
            "oos_avg_return": np.mean(oos_returns) * 100,
            "is_std_return": np.std(is_returns) * 100,
            "oos_std_return": np.std(oos_returns) * 100,
            "is_avg_sharpe": np.mean(is_sharpe),
            "oos_avg_sharpe": np.mean(oos_sharpe),
            "is_avg_max_dd": np.mean(is_max_dd),
            "oos_avg_max_dd": np.mean(oos_max_dd),
            "is_oos_correlation": correlation,
            "performance_decay": decay_factor,
            "overfitting_score": self._calculate_overfitting_score(is_returns, oos_returns),
            "results": results,
        }

    def _calculate_overfitting_score(self, is_returns: list, oos_returns: list) -> float:
        if not is_returns or not oos_returns:
            return 100

        is_mean = np.mean(is_returns)
        oos_mean = np.mean(oos_returns)
        if is_mean == 0:
            return 100

        decay_penalty = max(0, (is_mean - oos_mean) / is_mean) * 50
        correlation_penalty = (1 - abs(np.corrcoef(is_returns, oos_returns)[0, 1])) * 50 if len(is_returns) > 1 else 50
        return min(100, decay_penalty + correlation_penalty)


class RobustnessTester:
    """Test strategy robustness across different market conditions and parameters."""

    def __init__(self, coin: str, coin_cfg: dict, simulate_backtest, compute_metrics):
        self.coin = coin
        self.coin_cfg = coin_cfg
        self.simulate_backtest = simulate_backtest
        self.compute_metrics = compute_metrics

    def run_robustness_test(self, base_params: dict, num_scenarios: int = 100) -> dict:
        print(f"  {Fore.CYAN}Running robustness test for {self.coin}...{Style.RESET_ALL}")

        param_ranges = {
            "kc_scalar": (base_params.get("kc_scalar", 2.0) * 0.8, base_params.get("kc_scalar", 2.0) * 1.2),
            "rsi_oversold": (base_params.get("rsi_oversold", 40) - 5, base_params.get("rsi_oversold", 40) + 5),
            "rsi_overbought": (base_params.get("rsi_overbought", 60) - 5, base_params.get("rsi_overbought", 60) + 5),
            "stop_loss_pct": (base_params.get("stop_loss_pct", 0.01) * 0.5, base_params.get("stop_loss_pct", 0.01) * 2.0),
            "take_profit_pct": (base_params.get("take_profit_pct", 0.02) * 0.5, base_params.get("take_profit_pct", 0.02) * 2.0),
        }

        results = []
        for _ in range(num_scenarios):
            test_params = {key: np.random.uniform(min_val, max_val) for key, (min_val, max_val) in param_ranges.items()}
            result = self._run_single_backtest(test_params)
            if result and result.get("total_trades", 0) > 10:
                results.append({
                    "params": test_params,
                    "return": result["pct_return"],
                    "sharpe": result["sharpe_ratio"],
                    "max_dd": result["max_drawdown"],
                    "win_rate": result["win_rate"],
                })

        if not results:
            return {"error": "No valid scenarios found"}

        returns = [r["return"] for r in results]
        sharpe_ratios = [r["sharpe"] for r in results]
        max_drawdowns = [r["max_dd"] for r in results]

        return {
            "scenarios_tested": len(results),
            "return_stats": {
                "mean": np.mean(returns),
                "std": np.std(returns),
                "min": np.min(returns),
                "max": np.max(returns),
                "percentile_5": np.percentile(returns, 5),
                "percentile_95": np.percentile(returns, 95),
            },
            "sharpe_stats": {
                "mean": np.mean(sharpe_ratios),
                "std": np.std(sharpe_ratios),
                "min": np.min(sharpe_ratios),
                "max": np.max(sharpe_ratios),
            },
            "drawdown_stats": {
                "mean": np.mean(max_drawdowns),
                "std": np.std(max_drawdowns),
                "max": np.max(max_drawdowns),
            },
            "robustness_score": self._calculate_robustness_score(returns, sharpe_ratios),
            "results": results,
        }

    def _run_single_backtest(self, params: dict) -> dict | None:
        try:
            ticker = self.coin_cfg["ticker"]
            interval = self.coin_cfg["interval"]

            df = yf.download(ticker, interval=interval, period="180d",
                             auto_adjust=True, progress=False, timeout=30)
            if df is None or df.empty:
                return None

            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df.dropna(inplace=True)
            if len(df) < 10:
                return None

            trades, final_capital, equity_curve = self.simulate_backtest(df, self.coin_cfg, params)
            return self.compute_metrics(df, trades, final_capital, equity_curve, "robustness")
        except Exception:
            return None

    def _calculate_robustness_score(self, returns: list, sharpe_ratios: list) -> float:
        if not returns or not sharpe_ratios:
            return 0

        return_std = np.std(returns) / np.mean(returns) if np.mean(returns) != 0 else float("inf")
        sharpe_std = np.std(sharpe_ratios) / np.mean(sharpe_ratios) if np.mean(sharpe_ratios) != 0 else float("inf")
        return_score = max(0, 100 - (return_std * 50))
        sharpe_score = max(0, 100 - (sharpe_std * 50))
        return (return_score + sharpe_score) / 2


class StatisticalSignificanceTester:
    """Test statistical significance of strategy performance."""

    def __init__(self, coin: str, coin_cfg: dict, simulate_backtest, compute_metrics):
        self.coin = coin
        self.coin_cfg = coin_cfg
        self.simulate_backtest = simulate_backtest
        self.compute_metrics = compute_metrics

    def run_significance_test(self, params: dict, num_bootstraps: int = 1000) -> dict:
        print(f"  {Fore.CYAN}Running significance test for {self.coin}...{Style.RESET_ALL}")

        baseline_result = self._get_baseline_performance(params)
        if not baseline_result:
            return {"error": "Could not get baseline performance"}

        baseline_return = baseline_result["pct_return"]
        bootstrap_returns = []
        for _ in range(num_bootstraps):
            bootstrap_return = self._bootstrap_sample(params)
            if bootstrap_return is not None:
                bootstrap_returns.append(bootstrap_return)

        if not bootstrap_returns:
            return {"error": "Bootstrap sampling failed"}

        p_value = sum(1 for value in bootstrap_returns if value >= baseline_return) / len(bootstrap_returns)
        ci_lower = np.percentile(bootstrap_returns, 2.5)
        ci_upper = np.percentile(bootstrap_returns, 97.5)

        return {
            "baseline_return": baseline_return,
            "bootstrap_mean": np.mean(bootstrap_returns),
            "bootstrap_std": np.std(bootstrap_returns),
            "p_value": p_value,
            "significant_95": p_value < 0.05,
            "confidence_interval_95": (ci_lower, ci_upper),
            "effect_size": self._calculate_cohens_d(baseline_return, bootstrap_returns),
            "bootstrap_samples": len(bootstrap_returns),
        }

    def _get_baseline_performance(self, params: dict) -> dict | None:
        try:
            ticker = self.coin_cfg["ticker"]
            interval = self.coin_cfg["interval"]

            df = yf.download(ticker, interval=interval, period="365d",
                             auto_adjust=True, progress=False, timeout=30)
            if df is None or df.empty:
                return None

            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df.dropna(inplace=True)
            if len(df) < 10:
                return None

            trades, final_capital, equity_curve = self.simulate_backtest(df, self.coin_cfg, params)
            return self.compute_metrics(df, trades, final_capital, equity_curve, "baseline")
        except Exception:
            return None

    def _bootstrap_sample(self, params: dict) -> float | None:
        try:
            ticker = self.coin_cfg["ticker"]
            interval = self.coin_cfg["interval"]

            df = yf.download(ticker, interval=interval, period="365d",
                             auto_adjust=True, progress=False, timeout=30)
            if df is None or df.empty:
                return None

            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df.dropna(inplace=True)
            if len(df) < 10:
                return None

            block_size = 10
            blocks = [df.iloc[i:i + block_size].copy() for i in range(0, len(df) - block_size, block_size)]
            np.random.shuffle(blocks)
            bootstrap_df = pd.concat(blocks, ignore_index=True)
            if len(bootstrap_df) < 10:
                return None

            trades, final_capital, equity_curve = self.simulate_backtest(bootstrap_df, self.coin_cfg, params)
            metrics = self.compute_metrics(bootstrap_df, trades, final_capital, equity_curve, "bootstrap")
            return metrics["pct_return"]
        except Exception:
            return None

    def _calculate_cohens_d(self, baseline_return: float, bootstrap_returns: list) -> float:
        if not bootstrap_returns:
            return 0

        bootstrap_mean = np.mean(bootstrap_returns)
        bootstrap_std = np.std(bootstrap_returns)
        if bootstrap_std == 0:
            return 0
        return abs(baseline_return - bootstrap_mean) / bootstrap_std


def calculate_overall_score(baseline: dict, walk_forward: dict, robustness: dict, significance: dict) -> float:
    """Calculate composite performance score (0-100)."""
    score = 0

    if baseline.get("total_trades", 0) > 10:
        return_score = min(100, baseline.get("pct_return", 0) * 2)
        sharpe_score = min(100, baseline.get("sharpe_ratio", 0) * 20)
        dd_score = max(0, 100 - baseline.get("max_drawdown", 0) * 5)
        score += (return_score * 0.4 + sharpe_score * 0.4 + dd_score * 0.2) * 0.3

    if isinstance(walk_forward, dict) and "is_oos_correlation" in walk_forward:
        wf_score = max(0, walk_forward["is_oos_correlation"] * 100)
        decay_score = max(0, (1 - walk_forward.get("performance_decay", 1)) * 100)
        overfit_score = max(0, (100 - walk_forward.get("overfitting_score", 100)))
        score += (wf_score * 0.4 + decay_score * 0.3 + overfit_score * 0.3) * 0.3

    if isinstance(robustness, dict) and "robustness_score" in robustness:
        score += robustness["robustness_score"] * 0.2

    if isinstance(significance, dict) and "significant_95" in significance:
        sig_score = 100 if significance["significant_95"] else 0
        p_value_score = max(0, (1 - significance.get("p_value", 1)) * 100)
        score += (sig_score * 0.6 + p_value_score * 0.4) * 0.2

    return round(score, 1)


__all__ = [
    "WalkForwardValidator",
    "RobustnessTester",
    "StatisticalSignificanceTester",
    "calculate_overall_score",
]
