"""Compatibility facade for secure-config setup helpers."""

from hltrading.config.setup_secure_config import (
    main,
    os,
    setup_secure_config,
    sys,
)

__all__ = [
    "os",
    "sys",
    "setup_secure_config",
    "main",
]
