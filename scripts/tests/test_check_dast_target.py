import unittest

import _path  # noqa: F401
import check_dast_target as dast

CONTEXT = """<configuration><context><name>c</name>
<incregexes>https://staging.example.com.*</incregexes></context></configuration>"""


class DastTargetTests(unittest.TestCase):
    def test_extract(self):
        self.assertEqual(dast.extract_target(CONTEXT), "https://staging.example.com")

    def test_extract_missing(self):
        with self.assertRaises(dast.TargetError):
            dast.extract_target("<configuration/>")

    def test_validate_ok(self):
        self.assertEqual(dast.validate_target("https://staging.example.com"), "https://staging.example.com")

    def test_validate_rejects(self):
        for url in ["http://example.com", "https://localhost", "https://10.0.0.1", "https://127.0.0.1", "https://svc.internal"]:
            with self.subTest(url=url), self.assertRaises(dast.TargetError):
                dast.validate_target(url)

    def test_allowed_hosts(self):
        with self.assertRaises(dast.TargetError):
            dast.validate_target("https://a.example.com", ["b.example.com"])
        dast.validate_target("https://a.example.com", ["A.example.com"])


if __name__ == "__main__":
    unittest.main()
