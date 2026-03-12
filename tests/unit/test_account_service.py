#!/usr/bin/env python3
"""Focused regression tests for read-only account service helpers."""
import unittest
from unittest.mock import patch

from execution import account_service


class TestAccountService(unittest.TestCase):
    def test_get_hl_positions_delegates_to_client(self):
        with patch("execution.account_service._get_hl_positions", return_value=[{"coin": "ETH"}]) as mocked:
            result = account_service.get_hl_positions()

        mocked.assert_called_once_with()
        self.assertEqual(result, [{"coin": "ETH"}])

    def test_get_hl_account_info_delegates_to_client(self):
        payload = {"account_value": 123.0, "positions": []}
        with patch("execution.account_service._get_hl_account_info", return_value=payload) as mocked:
            result = account_service.get_hl_account_info()

        mocked.assert_called_once_with()
        self.assertEqual(result, payload)

    def test_get_hl_fees_delegates_to_client(self):
        payload = {"total_fees": 1.25, "currency": "USDC"}
        with patch("execution.account_service._get_hl_fees", return_value=payload) as mocked:
            result = account_service.get_hl_fees()

        mocked.assert_called_once_with()
        self.assertEqual(result, payload)


if __name__ == "__main__":
    unittest.main()
