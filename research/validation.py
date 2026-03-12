"""Compatibility facade for research validation helpers."""

import numpy as np
import pandas as pd
import yfinance as yf
from colorama import Fore, Style

from hltrading.research.validation import (
    RobustnessTester,
    StatisticalSignificanceTester,
    WalkForwardValidator,
    calculate_overall_score,
)

__all__ = [
    "np",
    "pd",
    "yf",
    "Fore",
    "Style",
    "WalkForwardValidator",
    "RobustnessTester",
    "StatisticalSignificanceTester",
    "calculate_overall_score",
]
