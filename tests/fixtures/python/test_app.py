import unittest
from app import greet


class GreetingTest(unittest.TestCase):
    def test_greeting(self):
        self.assertEqual(greet("Tram"), "Hello, Tram!")


if __name__ == "__main__":
    unittest.main()
