import unittest
from unittest.mock import Mock, patch

from app.crypto.price import BINANCE_MARKET_BASES, get_json_with_fallback


class BinanceMarketDataFallbackTests(unittest.TestCase):
    @patch("app.crypto.price.requests.get")
    def test_falls_back_when_first_endpoint_returns_418(self, mock_get):
        blocked = Mock()
        blocked.raise_for_status.side_effect = Exception("418 Client Error")
        healthy = Mock()
        healthy.raise_for_status.return_value = None
        healthy.json.return_value = [{"symbol": "BTCUSDT", "quoteVolume": "123"}]
        mock_get.side_effect = [blocked, healthy]

        result = get_json_with_fallback("/api/v3/ticker/24hr", timeout=15)

        self.assertEqual(result[0]["symbol"], "BTCUSDT")
        self.assertEqual(mock_get.call_count, 2)
        self.assertIn("data-api.binance.vision", mock_get.call_args_list[0].args[0])
        self.assertIn(BINANCE_MARKET_BASES[1], mock_get.call_args_list[1].args[0])

    @patch("app.crypto.price.requests.get")
    def test_reports_error_only_after_all_endpoints_fail(self, mock_get):
        blocked = Mock()
        blocked.raise_for_status.side_effect = Exception("418 Client Error")
        mock_get.return_value = blocked

        with self.assertRaisesRegex(RuntimeError, "All Binance market-data endpoints failed"):
            get_json_with_fallback("/api/v3/klines", params={"symbol": "XRPUSDT"})

        self.assertEqual(mock_get.call_count, len(BINANCE_MARKET_BASES))


if __name__ == "__main__":
    unittest.main()
