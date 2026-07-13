import unittest


class TestCachedProperty(unittest.TestCase):
    def test_cached_property(self):
        class Example:
            def __init__(self, value):
                self.value = value
                self.value2 = 5

            @property
            def expensive_computation(self):
                return self.value * 2 + self.value2  # Expensive calculation

        obj = Example(10)

        # First access should compute the value
        result1 = obj.expensive_computation
        self.assertEqual(result1, 25)

        # Second access should use cache
        result2 = obj.expensive_computation
        self.assertEqual(result2, 25)  # Should be same as before, no recomputation

        # Modify attribute, should invalidate cache
        obj.value = 15
        result3 = obj.expensive_computation
        self.assertEqual(result3, 35)  # Recalculated

        # Cache should hold the new value now
        result4 = obj.expensive_computation
        self.assertEqual(result4, 35)  # Still cached

        obj.value2 = 10
        obj.value = 20
        result5 = obj.expensive_computation  # Recalculated
        self.assertEqual(result5, 50)
