import unittest

from app.crypto.strategy import generate_signal


class StrategyTests(unittest.TestCase):
    def base(self, **overrides):
        values = {
            "rsi": 50,
            "ema20": 105,
            "ema50": 100,
            "price": 100,
            "support": 99.8,
            "resistance": 106,
            "volume_ratio": 1.8,
            "momentum_6h": 0.01,
        }
        values.update(overrides)
        return generate_signal(**values)

    def test_strong_setup_requires_volume(self):
        result = self.base()
        self.assertIn(result["signal"], {"BUY SETUP", "STRONG BUY"})

        weak = self.base(volume_ratio=0.7)
        self.assertNotIn(weak["signal"], {"BUY SETUP", "STRONG BUY"})

    def test_negative_momentum_blocks_buy(self):
        result = self.base(momentum_6h=-0.02)
        self.assertNotIn(result["signal"], {"BUY SETUP", "STRONG BUY"})

    def test_price_above_entry_zone_is_not_buy(self):
        result = self.base(price=101.0)
        self.assertNotIn(result["signal"], {"BUY SETUP", "STRONG BUY"})

    def test_low_rr_is_not_buy(self):
        result = self.base(resistance=100.2)
        self.assertNotIn(result["signal"], {"BUY SETUP", "STRONG BUY"})

    def test_backward_compatible_api_without_optional_data(self):
        result = generate_signal(50, 105, 100, 100, 99.8, 106)
        self.assertIn(result["signal"], {"WAIT", "BUY SETUP", "STRONG BUY", "SELL WATCH"})
        self.assertIsNone(result["volume_ratio"])
        self.assertIsNone(result["momentum_6h"])


if __name__ == "__main__":
    unittest.main()
