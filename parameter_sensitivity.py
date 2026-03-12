"""Compatibility facade for parameter sensitivity analysis helpers."""

from hltrading.research.parameter_sensitivity import (
    ParameterSensitivityAnalyzer,
    main,
    run_comprehensive_sensitivity_analysis,
)

__all__ = [
    "ParameterSensitivityAnalyzer",
    "run_comprehensive_sensitivity_analysis",
    "main",
]
