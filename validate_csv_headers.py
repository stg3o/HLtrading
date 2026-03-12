#!/usr/bin/env python3
"""
Script to validate and fix CSV headers for the trading bot
"""
import csv
import os
import shutil
from datetime import datetime

def validate_csv_header(file_path, expected_headers):
    """Validate CSV header and fix if necessary"""
    if not os.path.exists(file_path):
        print(f"File {file_path} does not exist. Creating with headers.")
        with open(file_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(expected_headers)
        return True
    
    # Read current header
    with open(file_path, 'r', newline='') as f:
        reader = csv.reader(f)
        current_header = next(reader, [])
    
    if current_header == expected_headers:
        print(f"✓ {file_path} has correct headers")
        return True
    
    # Backup the file
    backup_path = f"{file_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(file_path, backup_path)
    print(f"Created backup: {backup_path}")
    
    # Read all data
    with open(file_path, 'r', newline='') as f:
        reader = csv.reader(f)
        all_rows = list(reader)
    
    # Remove old header and add new one
    data_rows = all_rows[1:] if all_rows else []
    
    # Write with new header
    with open(file_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(expected_headers)
        writer.writerows(data_rows)
    
    print(f"✗ {file_path} header fixed")
    print(f"  Old: {current_header}")
    print(f"  New: {expected_headers}")
    return False

def main():
    """Validate all CSV files used by the bot"""
    print("Validating CSV headers...")
    
    # Opportunities CSV
    # Note: opportunities.csv is from removed arbitrage functionality
    # This validation can be removed if arbitrage features are no longer needed
    # opportunities_headers = ['timestamp', 'pair', 'buy_exchange', 'buy_price', 'sell_exchange', 'sell_price', 'gross_spread_pct', 'net_spread_pct']
    # validate_csv_header('opportunities.csv', opportunities_headers)
    
    # Paper trades CSV
    trades_headers = ['timestamp', 'coin', 'action', 'price', 'size', 'pnl', 'reason']
    validate_csv_header('paper_trades.csv', trades_headers)
    
    # Signals log (if it exists)
    if os.path.exists('signals.log'):
        print("✓ signals.log exists (text file, no header validation needed)")
    
    print("\nCSV header validation complete!")

if __name__ == '__main__':
    main()