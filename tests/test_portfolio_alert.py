import unittest
from unittest.mock import patch

from app.crypto.portfolio_alert import (
    build_message,
    classify_position,
    monitor_portfolio_alerts,
)


class PortfolioAlertRegimeCompatibilityTests(unittest.TestCase):
    def test_classify_accepts_string_market_regime_from_monitor(self):
        position = {
            "asset": "BTC",
            "unrealized_pnl_percent": 12.0,
            "market_regime": "BULLISH",
        }

        decision = classify_position(position)

        self.assertEqual(decision["action"], "TAKE_PROFIT_REVIEW")
        self.assertEqual(decision["priority"], "HIGH")

    def test_classify_still_accepts_legacy_dict_market_regime(self):
        position = {
            "asset": "BTC",
            "unrealized_pnl_percent": 1.0,
            "market_regime": {"status": "BEARISH"},
        }

        decision = classify_position(position)

        self.assertEqual(decision["action"], "EXIT_REVIEW")

    def test_message_accepts_string_market_regime(self):
        message = build_message(
            {
                "asset": "BTC",
                "market_regime": "BULLISH",
                "unrealized_pnl_percent": 12.0,
            },
            {
                "action": "TAKE_PROFIT_REVIEW",
                "priority": "HIGH",
                "reason": "test",
            },
        )

        self.assertIn("BULLISH", message)

    @patch("app.crypto.portfolio_alert.send_message")
    def test_monitor_returns_success_for_monitor_output_shape(self, send_message):
        result = monitor_portfolio_alerts(
            [
                {
                    "asset": "BTC",
                    "unrealized_pnl_percent": 12.0,
                    "market_regime": "BULLISH",
                }
            ],
            force=True,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["position_count"], 1)
        self.assertEqual(result["results"][0]["action"], "TAKE_PROFIT_REVIEW")
        self.assertTrue(result["results"][0]["sent"])
        send_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()
