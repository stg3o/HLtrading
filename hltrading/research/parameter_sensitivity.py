"""
parameter_sensitivity.py — Parameter sensitivity analysis framework
Analyzes how strategy performance varies with parameter changes
"""
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.model_selection import ParameterGrid
import matplotlib.pyplot as plt
import seaborn as sns
from colorama import Fore, Style

from backtester_enhanced import run_enhanced_backtest
from config import COINS


class ParameterSensitivityAnalyzer:
    """Analyze parameter sensitivity and find optimal parameter ranges."""

    def __init__(self, coin: str, coin_cfg: dict):
        self.coin = coin
        self.coin_cfg = coin_cfg
        self.results = []

    def analyze_sensitivity(self, param_ranges: dict, num_samples: int = 100) -> dict:
        """Analyze parameter sensitivity using grid search or random sampling."""
        print(f"\n{Fore.CYAN}Analyzing parameter sensitivity for {self.coin}...{Style.RESET_ALL}")

        # Generate parameter combinations
        param_combinations = self._generate_parameter_combinations(param_ranges, num_samples)

        # Test each combination
        results = []
        for i, params in enumerate(param_combinations):
            print(f"  Testing combination {i+1}/{len(param_combinations)}: {params}")

            result = run_enhanced_backtest(
                self.coin, self.coin_cfg,
                period="180d", params=params, silent=True
            )

            if "error" not in result:
                baseline = result["baseline"]
                results.append({
                    "params": params,
                    "return": baseline.get("pct_return", 0),
                    "sharpe": baseline.get("sharpe_ratio", 0),
                    "max_dd": baseline.get("max_drawdown", 0),
                    "win_rate": baseline.get("win_rate", 0),
                    "profit_factor": baseline.get("profit_factor", 0),
                    "overall_score": result.get("overall_score", 0)
                })

        # Analyze sensitivity
        sensitivity_analysis = self._analyze_sensitivity(results, param_ranges)

        return {
            "results": results,
            "sensitivity": sensitivity_analysis,
            "optimal_params": self._find_optimal_params(results),
            "robust_params": self._find_robust_params(results, param_ranges)
        }

    def _generate_parameter_combinations(self, param_ranges: dict, num_samples: int) -> list:
        """Generate parameter combinations for sensitivity analysis."""
        # For large parameter spaces, use random sampling instead of full grid
        if len(param_ranges) > 4 or num_samples < 1000:
            return self._random_sample_params(param_ranges, num_samples)
        else:
            return self._grid_search_params(param_ranges)

    def _random_sample_params(self, param_ranges: dict, num_samples: int) -> list:
        """Generate random parameter samples."""
        samples = []
        for _ in range(num_samples):
            sample = {}
            for param, (min_val, max_val) in param_ranges.items():
                if isinstance(min_val, int) and isinstance(max_val, int):
                    sample[param] = np.random.randint(min_val, max_val + 1)
                else:
                    sample[param] = np.random.uniform(min_val, max_val)
            samples.append(sample)
        return samples

    def _grid_search_params(self, param_ranges: dict) -> list:
        """Generate grid search parameter combinations."""
        # Create parameter grid
        param_grid = {}
        for param, (min_val, max_val) in param_ranges.items():
            if isinstance(min_val, int) and isinstance(max_val, int):
                param_grid[param] = list(range(min_val, max_val + 1))
            else:
                param_grid[param] = np.linspace(min_val, max_val, 5).tolist()

        # Generate combinations
        combinations = []
        for params in ParameterGrid(param_grid):
            combinations.append(params)

        return combinations

    def _analyze_sensitivity(self, results: list, param_ranges: dict) -> dict:
        """Analyze parameter sensitivity using correlation analysis."""
        if not results:
            return {"error": "No results to analyze"}

        # Convert results to DataFrame for analysis
        df = pd.DataFrame(results)

        sensitivity = {}

        # Analyze each parameter's impact on key metrics
        metrics = ["return", "sharpe", "max_dd", "win_rate", "profit_factor", "overall_score"]

        for metric in metrics:
            metric_sensitivity = {}

            for param in param_ranges.keys():
                if param in df.columns:
                    # Calculate correlation between parameter and metric
                    correlation = df[param].corr(df[metric])

                    # Calculate parameter importance (absolute correlation)
                    importance = abs(correlation)

                    # Calculate optimal range (where metric is highest)
                    optimal_range = self._find_optimal_range(df, param, metric)

                    metric_sensitivity[param] = {
                        "correlation": correlation,
                        "importance": importance,
                        "optimal_range": optimal_range
                    }

            sensitivity[metric] = metric_sensitivity

        return sensitivity

    def _find_optimal_range(self, df: pd.DataFrame, param: str, metric: str,
                          percentile: float = 0.8) -> tuple:
        """Find the parameter range that yields top percentile performance."""
        if df.empty or param not in df.columns or metric not in df.columns:
            return (0, 0)

        # Sort by metric and find threshold for top percentile
        threshold = df[metric].quantile(percentile)
        top_performers = df[df[metric] >= threshold]

        if top_performers.empty:
            return (0, 0)

        return (top_performers[param].min(), top_performers[param].max())

    def _find_optimal_params(self, results: list) -> dict:
        """Find parameters that maximize overall score."""
        if not results:
            return {}

        # Find best result by overall score
        best_result = max(results, key=lambda x: x["overall_score"])
        return {
            "params": best_result["params"],
            "score": best_result["overall_score"],
            "return": best_result["return"],
            "sharpe": best_result["sharpe"],
            "max_dd": best_result["max_dd"]
        }

    def _find_robust_params(self, results: list, param_ranges: dict) -> dict:
        """Find parameters that are robust across different market conditions."""
        if not results:
            return {}

        # Calculate robustness score for each parameter set
        robust_results = []
        for result in results:
            # Robustness = high performance + low variance across metrics
            performance_score = result["overall_score"]

            # Calculate coefficient of variation for key metrics
            metrics = [result["return"], result["sharpe"], result["win_rate"]]
            if all(m > 0 for m in metrics):
                cv = np.std(metrics) / np.mean(metrics)
                robustness_score = performance_score * (1 - min(cv, 0.5))
            else:
                robustness_score = 0

            robust_results.append({
                "params": result["params"],
                "robustness_score": robustness_score,
                "performance_score": performance_score
            })

        # Find most robust parameters
        best_robust = max(robust_results, key=lambda x: x["robustness_score"])
        return {
            "params": best_robust["params"],
            "robustness_score": best_robust["robustness_score"],
            "performance_score": best_robust["performance_score"]
        }

    def generate_sensitivity_report(self, analysis_result: dict) -> str:
        """Generate a comprehensive sensitivity analysis report."""
        report = f"\n{Fore.CYAN}{'='*80}\n"
        report += f"PARAMETER SENSITIVITY ANALYSIS REPORT: {self.coin}\n"
        report += f"{'='*80}{Style.RESET_ALL}\n\n"

        # Optimal parameters
        optimal = analysis_result.get("optimal_params", {})
        if optimal:
            report += f"{Fore.YELLOW}OPTIMAL PARAMETERS (Max Score){Style.RESET_ALL}\n"
            report += f"  Parameters: {optimal['params']}\n"
            report += f"  Overall Score: {optimal['score']:.1f}/100\n"
            report += f"  Return: {optimal['return']:.2f}%\n"
            report += f"  Sharpe: {optimal['sharpe']:.3f}\n"
            report += f"  Max DD: {optimal['max_dd']:.1f}%\n\n"

        # Robust parameters
        robust = analysis_result.get("robust_params", {})
        if robust:
            report += f"{Fore.YELLOW}ROBUST PARAMETERS (Best Risk-Adjusted){Style.RESET_ALL}\n"
            report += f"  Parameters: {robust['params']}\n"
            report += f"  Robustness Score: {robust['robustness_score']:.1f}/100\n"
            report += f"  Performance Score: {robust['performance_score']:.1f}/100\n\n"

        # Sensitivity analysis
        sensitivity = analysis_result.get("sensitivity", {})
        if sensitivity:
            report += f"{Fore.YELLOW}PARAMETER SENSITIVITY{Style.RESET_ALL}\n"

            for metric, params in sensitivity.items():
                if isinstance(params, dict):
                    report += f"\n  {Fore.CYAN}{metric.upper()} SENSITIVITY:{Style.RESET_ALL}\n"

                    # Sort parameters by importance
                    sorted_params = sorted(params.items(), key=lambda x: x[1].get("importance", 0), reverse=True)

                    for param, data in sorted_params:
                        corr = data.get("correlation", 0)
                        imp = data.get("importance", 0)
                        opt_range = data.get("optimal_range", (0, 0))

                        corr_symbol = "↑" if corr > 0 else "↓" if corr < 0 else "→"
                        importance_level = "HIGH" if imp > 0.5 else "MEDIUM" if imp > 0.2 else "LOW"

                        report += f"    {param}: {corr_symbol}{corr:+.3f} ({importance_level}) Optimal: {opt_range}\n"

        report += f"\n{Fore.CYAN}{'='*80}{Style.RESET_ALL}\n"

        return report

    def plot_sensitivity_analysis(self, analysis_result: dict, save_path: str = None):
        """Create visualizations for parameter sensitivity analysis."""
        results = analysis_result.get("results", [])
        if not results:
            print(f"{Fore.RED}No results to plot{Style.RESET_ALL}")
            return

        df = pd.DataFrame(results)

        # Create figure with subplots
        fig, axes = plt.subplots(2, 3, figsize=(15, 10))
        fig.suptitle(f'Parameter Sensitivity Analysis: {self.coin}', fontsize=16)

        # Plot 1: Overall Score vs Parameters
        ax1 = axes[0, 0]
        for param in df.columns:
            if param.startswith('param_'):
                param_name = param.replace('param_', '')
                ax1.scatter(df[param], df['overall_score'], alpha=0.6, label=param_name)
        ax1.set_xlabel('Parameter Value')
        ax1.set_ylabel('Overall Score')
        ax1.set_title('Score vs Parameters')
        ax1.legend()

        # Plot 2: Return vs Sharpe (Performance Scatter)
        ax2 = axes[0, 1]
        scatter = ax2.scatter(df['return'], df['sharpe'], c=df['overall_score'],
                             cmap='viridis', alpha=0.6)
        ax2.set_xlabel('Return (%)')
        ax2.set_ylabel('Sharpe Ratio')
        ax2.set_title('Return vs Sharpe (Color = Score)')
        plt.colorbar(scatter, ax=ax2)

        # Plot 3: Parameter Correlation Heatmap
        ax3 = axes[0, 2]
        param_cols = [col for col in df.columns if col.startswith('param_')]
        if param_cols:
            corr_matrix = df[param_cols].corr()
            sns.heatmap(corr_matrix, annot=True, cmap='coolwarm', ax=ax3)
            ax3.set_title('Parameter Correlations')

        # Plot 4: Performance Distribution
        ax4 = axes[1, 0]
        ax4.hist(df['overall_score'], bins=20, alpha=0.7, color='skyblue')
        ax4.axvline(df['overall_score'].mean(), color='red', linestyle='--',
                   label=f'Mean: {df["overall_score"].mean():.1f}')
        ax4.set_xlabel('Overall Score')
        ax4.set_ylabel('Frequency')
        ax4.set_title('Score Distribution')
        ax4.legend()

        # Plot 5: Sensitivity Radar Chart (if we have sensitivity data)
        ax5 = axes[1, 1]
        sensitivity = analysis_result.get("sensitivity", {})
        if sensitivity:
            metrics = list(sensitivity.keys())[:5]  # Limit to 5 metrics
            params = list(sensitivity[metrics[0]].keys()) if metrics else []

            if params:
                angles = np.linspace(0, 2 * np.pi, len(params), endpoint=False).tolist()
                angles += angles[:1]  # Complete the circle

                ax5 = plt.subplot(2, 3, 5, projection='polar')

                for metric in metrics:
                    values = [sensitivity[metric].get(param, {}).get("importance", 0) for param in params]
                    values += values[:1]  # Complete the circle
                    ax5.plot(angles, values, 'o-', linewidth=2, label=metric)

                ax5.set_xticks(angles[:-1])
                ax5.set_xticklabels(params)
                ax5.set_title('Parameter Importance')
                ax5.legend()

        # Plot 6: Optimal vs Robust Parameters
        ax6 = axes[1, 2]
        optimal = analysis_result.get("optimal_params", {})
        robust = analysis_result.get("robust_params", {})

        if optimal and robust:
            labels = list(optimal["params"].keys())
            optimal_values = [optimal["params"][label] for label in labels]
            robust_values = [robust["params"][label] for label in labels]

            x = np.arange(len(labels))
            width = 0.35

            ax6.bar(x - width/2, optimal_values, width, label='Optimal', alpha=0.8)
            ax6.bar(x + width/2, robust_values, width, label='Robust', alpha=0.8)
            ax6.set_xlabel('Parameters')
            ax6.set_ylabel('Parameter Values')
            ax6.set_title('Optimal vs Robust Parameters')
            ax6.set_xticks(x)
            ax6.set_xticklabels(labels)
            ax6.legend()

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"{Fore.GREEN}Sensitivity analysis plot saved to {save_path}{Style.RESET_ALL}")

        plt.show()


def run_comprehensive_sensitivity_analysis():
    """Run comprehensive parameter sensitivity analysis for all coins."""
    print(f"{Fore.CYAN}Starting comprehensive parameter sensitivity analysis...{Style.RESET_ALL}")

    # Define parameter ranges for testing
    param_ranges = {
        "kc_scalar": (1.0, 4.0),
        "rsi_oversold": (30, 50),
        "rsi_overbought": (50, 70),
        "stop_loss_pct": (0.005, 0.020),
        "take_profit_pct": (0.010, 0.040),
        "min_rr_ratio": (1.0, 2.0),
        "hurst_cap": (0.5, 0.8),
    }

    # Test coins
    test_coins = ["SOL", "ETH", "BTC"]

    for coin in test_coins:
        if coin not in COINS:
            print(f"{Fore.RED}Skipping {coin} - not in COINS config{Style.RESET_ALL}")
            continue

        print(f"\n{Fore.YELLOW}Analyzing {coin}...{Style.RESET_ALL}")

        coin_cfg = COINS[coin]
        analyzer = ParameterSensitivityAnalyzer(coin, coin_cfg)

        # Run sensitivity analysis
        analysis_result = analyzer.analyze_sensitivity(param_ranges, num_samples=50)

        # Generate report
        report = analyzer.generate_sensitivity_report(analysis_result)
        print(report)

        # Save report to file
        filename = f"sensitivity_analysis_{coin}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(filename, 'w') as f:
            f.write(report)
        print(f"{Fore.GREEN}Report saved to {filename}{Style.RESET_ALL}")

        # Create visualization
        plot_filename = f"sensitivity_plot_{coin}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.png"
        analyzer.plot_sensitivity_analysis(analysis_result, save_path=plot_filename)


def main():
    """Run parameter sensitivity analysis."""
    try:
        run_comprehensive_sensitivity_analysis()

        print(f"\n{Fore.GREEN}{'='*80}")
        print(f"Parameter sensitivity analysis completed successfully!")
        print(f"Key features implemented:")
        print(f"  ✓ Parameter sensitivity analysis using correlation")
        print(f"  ✓ Optimal parameter identification")
        print(f"  ✓ Robust parameter selection")
        print(f"  ✓ Comprehensive reporting and visualization")
        print(f"  ✓ Grid search and random sampling support")
        print(f"  ✓ Multi-metric sensitivity analysis")
        print(f"{'='*80}{Style.RESET_ALL}")

    except Exception as e:
        print(f"\n{Fore.RED}Error during sensitivity analysis: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
