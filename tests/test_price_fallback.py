import unittest
from unittest.mock import Mock, patch

import requests

from app.crypto import price


class BinanceRateLimitCircuitTests(unittest.TestCase):
    def setUp(self):
        price._binance_blocked_until = 0.0
        price._binance_block_reason = ""
        price._binance_fallback_logged = False

    def tearDown(self):
        price._binance_blocked_until = 0.0
        price._binance_block_reason = ""
        price._binance_fallback_logged = False

    def test_http_418_opens_circuit_and_suppresses_followup_requests(self):
        response = Mock()
        response.status_code = 418
        response.raise_for_status.side_effect = requests.HTTPError("418 I'm a teapot")

        with patch.object(price.requests, "get", return_value=response) as get:
            with self.assertRaisesRegex(RuntimeError, "All Binance market-data endpoints failed"):
                price.get_json_with_fallback(price.BINANCE_KLINES_PATH, params={"symbol": "XRPUSDT"})

            self.assertEqual(get.call_count, 1)
            self.assertGreater(price._binance_blocked_until, price.time.time())

            with self.assertRaisesRegex(RuntimeError, "Binance circuit open"):
                price.get_json_with_fallback(price.BINANCE_KLINES_PATH, params={"symbol": "BTCUSDT"})

            # A single IP-ban response must prevent a request storm across
            # the remaining symbols in the scanner's universe.
            self.assertEqual(get.call_count, 1)

    def test_http_429_also_opens_circuit(self):
        response = Mock()
        response.status_code = 429
        response.raise_for_status.side_effect = requests.HTTPError("429 Too Many Requests")

        with patch.object(price.requests, "get", return_value=response) as get:
            with self.assertRaises(RuntimeError):
                price.get_json_with_fallback(price.BINANCE_24HR_PATH)

        self.assertEqual(get.call_count, 1)
        self.assertIn("HTTP 429", price._binance_block_reason)


if __name__ == "__main__":
    unittest.main()
