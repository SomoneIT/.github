import unittest

import _path  # noqa: F401
import copilot_autofix_limit as limit


class AutofixLimitTests(unittest.TestCase):
    def test_count_attempts(self):
        comments = [{"body": "hi"}, {"body": f"fix {limit.DEFAULT_MARKER}"}, {"body": None}]
        self.assertEqual(limit.count_attempts(comments, limit.DEFAULT_MARKER), 1)

    def test_is_allowed(self):
        self.assertTrue(limit.is_allowed(2, 3))
        self.assertFalse(limit.is_allowed(3, 3))

    def test_missing_env(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(limit.main(), 2)


if __name__ == "__main__":
    unittest.main()
