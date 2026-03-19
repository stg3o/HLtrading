"""Compatibility facade for read-only Hyperliquid REST client helpers."""

import json as _json
import urllib as _urllib

from colorama import Fore as _Fore
from hltrading.execution import hyperliquid_client as _impl
from hltrading.execution.hyperliquid_client import *  # noqa: F401,F403

json = _json
urllib = _urllib
Fore = _Fore
TESTNET = _impl.TESTNET
HL_WALLET_ADDRESS = _impl.HL_WALLET_ADDRESS
_hl_post = _impl._hl_post


def get_hl_price(coin: str):
    original = _impl._hl_post
    _impl._hl_post = _hl_post
    try:
        return _impl.get_hl_price(coin)
    finally:
        _impl._hl_post = original


def get_hl_obi(coin: str, levels: int = 10):
    original = _impl._hl_post
    _impl._hl_post = _hl_post
    try:
        return _impl.get_hl_obi(coin, levels=levels)
    finally:
        _impl._hl_post = original


def get_hl_funding_rate(coin: str):
    original = _impl._hl_post
    _impl._hl_post = _hl_post
    try:
        return _impl.get_hl_funding_rate(coin)
    finally:
        _impl._hl_post = original


def get_hl_open_interest(coin: str):
    original = _impl._hl_post
    _impl._hl_post = _hl_post
    try:
        return _impl.get_hl_open_interest(coin)
    finally:
        _impl._hl_post = original


def get_hl_open_orders():
    original = _impl._hl_post
    _impl._hl_post = _hl_post
    try:
        return _impl.get_hl_open_orders()
    finally:
        _impl._hl_post = original


def get_hl_mark_oracle(coin: str):
    original = _impl._hl_post
    _impl._hl_post = _hl_post
    try:
        return _impl.get_hl_mark_oracle(coin)
    finally:
        _impl._hl_post = original


def get_hl_positions():
    original = _impl._hl_post
    _impl._hl_post = _hl_post
    try:
        return _impl.get_hl_positions()
    finally:
        _impl._hl_post = original


def get_hl_account_info():
    original = _impl._hl_post
    _impl._hl_post = _hl_post
    try:
        return _impl.get_hl_account_info()
    finally:
        _impl._hl_post = original


def get_hl_fees():
    original = _impl._hl_post
    _impl._hl_post = _hl_post
    try:
        return _impl.get_hl_fees()
    finally:
        _impl._hl_post = original
