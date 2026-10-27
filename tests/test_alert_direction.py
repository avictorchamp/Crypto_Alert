import unittest

from app.main import evaluate_watchlist_alert


class AlertDirectionSafetyTests(unittest.TestCase):
    def test_sell_watch_is_not_routed_with_long_only_trade_plan(self):
        result = evaluate_watchlist_alert(
            {
                "signal": "SELL WATCH",
                "quality_score": 90,
                "risk_reward": 2.0,
            },
            {"status": "BEARISH"},
            {"status": "IN_ENTRY"},
        )
        self.assertFalse(result["allowed"])
        self.assertIn("short-side trade plan", result["reason"])

    def test_strong_sell_is_not_routed_with_long_only_trade_plan(self):
        result = evaluate_watchlist_alert(
            {
                "signal": "STRONG SELL",
                "quality_score": 95,
                "risk_reward": 3.0,
            },
            {"status": "BEARISH"},
            {"status": "IN_ENTRY"},
        )
        self.assertFalse(result["allowed"])
        self.assertIn("short-side trade plan", result["reason"])

    def test_valid_buy_can_still_pass_existing_gates(self):
        result = evaluate_watchlist_alert(
            {
                "signal": "BUY SETUP",
                "quality_score": 80,
                "risk_reward": 1.5,
            },
            {"status": "BULLISH"},
            {"status": "IN_ENTRY"},
        )
        self.assertTrue(result["allowed"])


if __name__ == "__main__":
    unittest.main()
