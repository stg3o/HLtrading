"""Compatibility facade for configuration validation helpers."""

from hltrading.config import config_validator as _impl
from hltrading.config.config_validator import *  # noqa: F401,F403

logging = _impl.logging
Any = _impl.Any
Dict = _impl.Dict
List = _impl.List
Optional = _impl.Optional
Union = _impl.Union
InputValidator = _impl.InputValidator
ValidationError = _impl.ValidationError
logger = _impl.logger
config_validator = _impl.config_validator
