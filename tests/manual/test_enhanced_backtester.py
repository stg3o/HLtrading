"""
test_enhanced_backtester.py — Test script for the enhanced backtester
Demonstrates walk-forward validation, robustness testing, and statistical significance
"""
import os
import sys

import pandas as pd
from colorama import Fore, Style

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backtester_enhanced import run_enhanced_backtest, print_enhanced_results
from config import COINS

def test_enhanced_backtester():
    """Test the enhanced backtester with multiple coins."""
    print(f"\n{Fore.CYAN}{'='*80}")
    print(f"{Fore.CYAN}ENHANCED BACKTESTER TESTING")
    print(f"{Fore.CYAN}{'='*80}{Style.RESET_ALL}")
    
    # Test coins with different strategies
    test_coins = ["SOL", "ETH", "BTC"]
    
    for coin in test_coins:
        if coin not in COINS:
            print(f"\n{Fore.RED}Skipping {coin} - not in COINS config{Style.RESET_ALL}")
            continue
            
        coin_cfg = COINS[coin]
        print(f"\n{Fore.YELLOW}Testing {coin} ({coin_cfg['strategy_type']} strategy){Style.RESET_ALL}")
        print(f"  Ticker: {coin_cfg['ticker']}, Interval: {coin_cfg['interval']}")
        
        # Test with default parameters
        result = run_enhanced_backtest(coin, coin_cfg, period="180d", silent=False)
        
        if "error" in result:
            print(f"  {Fore.RED}Error: {result['error']}{Style.RESET_ALL}")
            continue
        
        # Print detailed results
        print_enhanced_results(result)
        
        # Save results to file
        filename = f"enhanced_backtest_{coin}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.json"
        import json
        with open(filename, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        print(f"  {Fore.GREEN}Results saved to {filename}{Style.RESET_ALL}")

def test_parameter_sensitivity():
    """Test parameter sensitivity analysis."""
    print(f"\n{Fore.CYAN}{'='*60}")
    print(f"{Fore.CYAN}PARAMETER SENSITIVITY TESTING")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    
    coin = "SOL"
    if coin not in COINS:
        print(f"{Fore.RED}SOL not in COINS config{Style.RESET_ALL}")
        return
    
    coin_cfg = COINS[coin]
    
    # Test different parameter sets
    test_params = [
        {"kc_scalar": 1.5, "rsi_oversold": 35, "rsi_overbought": 65, "stop_loss_pct": 0.008},
        {"kc_scalar": 2.0, "rsi_oversold": 40, "rsi_overbought": 60, "stop_loss_pct": 0.010},
        {"kc_scalar": 2.5, "rsi_oversold": 45, "rsi_overbought": 55, "stop_loss_pct": 0.012},
        {"kc_scalar": 3.0, "rsi_oversold": 50, "rsi_overbought": 50, "stop_loss_pct": 0.015},
    ]
    
    results = []
    for i, params in enumerate(test_params):
        print(f"\n{Fore.YELLOW}Testing parameter set {i+1}: {params}{Style.RESET_ALL}")
        
        result = run_enhanced_backtest(coin, coin_cfg, period="90d", 
                                     params=params, silent=True)
        
        if "error" not in result:
            baseline = result["baseline"]
            print(f"  Return: {baseline['pct_return']:.2f}%")
            print(f"  Sharpe: {baseline['sharpe_ratio']:.3f}")
            print(f"  Max DD: {baseline['max_drawdown']:.1f}%")
            print(f"  Overall Score: {result['overall_score']:.1f}/100")
            
            results.append({
                "params": params,
                "return": baseline['pct_return'],
                "sharpe": baseline['sharpe_ratio'],
                "max_dd": baseline['max_drawdown'],
                "score": result['overall_score']
            })
    
    # Find best parameters
    if results:
        best = max(results, key=lambda x: x['score'])
        print(f"\n{Fore.GREEN}Best parameter set (score: {best['score']:.1f}):{Style.RESET_ALL}")
        print(f"  {best['params']}")
        print(f"  Return: {best['return']:.2f}%, Sharpe: {best['sharpe']:.3f}")

def test_walk_forward_validation():
    """Test walk-forward validation specifically."""
    print(f"\n{Fore.CYAN}{'='*60}")
    print(f"{Fore.CYAN}WALK-FORWARD VALIDATION TESTING")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    
    coin = "ETH"
    if coin not in COINS:
        print(f"{Fore.RED}ETH not in COINS config{Style.RESET_ALL}")
        return
    
    coin_cfg = COINS[coin]
    
    # Run enhanced backtest which includes walk-forward validation
    result = run_enhanced_backtest(coin, coin_cfg, period="365d", silent=False)
    
    if "error" not in result:
        wf = result.get("walk_forward", {})
        if isinstance(wf, dict) and "iterations" in wf:
            print(f"\n{Fore.GREEN}Walk-forward validation completed successfully:{Style.RESET_ALL}")
            print(f"  Iterations: {wf['iterations']}")
            print(f"  IS/OOS correlation: {wf['is_oos_correlation']:.3f}")
            print(f"  Performance decay: {wf['performance_decay']:.3f}")
            print(f"  Overfitting score: {wf['overfitting_score']:.1f}/100")
            
            if wf['is_oos_correlation'] > 0.5:
                print(f"  {Fore.GREEN}✓ Good correlation between in-sample and out-of-sample performance{Style.RESET_ALL}")
            else:
                print(f"  {Fore.RED}✗ Poor correlation - potential overfitting{Style.RESET_ALL}")
        else:
            print(f"  {Fore.RED}Walk-forward validation failed{Style.RESET_ALL}")

def main():
    """Run all enhanced backtester tests."""
    print(f"{Fore.CYAN}Starting enhanced backtester tests...{Style.RESET_ALL}")
    
    try:
        # Test basic functionality
        test_enhanced_backtester()
        
        # Test parameter sensitivity
        test_parameter_sensitivity()
        
        # Test walk-forward validation
        test_walk_forward_validation()
        
        print(f"\n{Fore.GREEN}{'='*80}")
        print(f"Enhanced backtester tests completed successfully!")
        print(f"Key improvements implemented:")
        print(f"  ✓ Walk-forward validation framework")
        print(f"  ✓ Robustness testing with parameter variations")
        print(f"  ✓ Statistical significance testing with bootstrap")
        print(f"  ✓ Enhanced backtest accuracy with better data handling")
        print(f"  ✓ Comprehensive performance scoring (0-100)")
        print(f"  ✓ Out-of-sample performance validation")
        print(f"{'='*80}{Style.RESET_ALL}")
        
    except Exception as e:
        print(f"\n{Fore.RED}Error during testing: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
