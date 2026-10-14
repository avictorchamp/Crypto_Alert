import unittest
from unittest.mock import Mock, patch

from app.crypto.price import (
    BINANCE_MARKET_BASES,
    get_bybit_json,
    get_json_with_fallback,
)


class BinanceMarketDataFallbackTests(unittest.TestCase):
    @patch("app.crypto.price.requests.get")
    def test_stops_retrying_binance_hosts_after_418(self, mock_get):
        blocked = Mock()
        blocked.status_code = 418
        blocked.raise_for_status.side_effect = Exception("418 Client Error")
        mock_get.return_value = blocked

        with self.assertRaisesRegex(RuntimeError, "All Binance market-data endpoints failed"):
            get_json_with_fallback("/api/v3/ticker/24hr", timeout=15)

        # 418 is an IP ban signal; do not keep hitting alternate Binance hosts.
        self.assertEqual(mock_get.call_count, 1)
        self.assertIn("data-api.binance.vision", mock_get.call_args.args[0])

    @patch("app.crypto.price.requests.get")
    def test_bybit_public_market_data_response_is_accepted(self, mock_get):
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "retCode": 0,
            "retMsg": "OK",
            "result": {"list": [{"symbol": "BTCUSDT", "turnover24h": "123"}]},
        }
        mock_get.return_value = response

        result = get_bybit_json(
            "/v5/market/tickers",
            params={"category": "spot"},
        )

        self.assertEqual(result["retCode"], 0)
        self.assertEqual(result["result"]["list"][0]["symbol"], "BTCUSDT")
        self.assertIn("api.bybit.com/v5/market/tickers", mock_get.call_args.args[0])

    @patch("app.crypto.price.requests.get")
    def test_reports_error_only_after_non_rate_limit_failures_exhaust_hosts(self, mock_get):
        response = Mock()
        response.status_code = 503
        response.raise_for_status.side_effect = Exception("503 Service Unavailable")
        mock_get.return_value = response

        with self.assertRaisesRegex(RuntimeError, "All Binance market-data endpoints failed"):
            get_json_with_fallback("/api/v3/klines", params={"symbol": "XRPUSDT"})

        self.assertEqual(mock_get.call_count, len(BINANCE_MARKET_BASES))


if __name__ == "__main__":
    unittest.main()
