import unittest

import _path  # noqa: F401
import check_dast_target as dast

CONTEXT = """<configuration><context><name>c</name>
<incregexes>https://staging.example.com.*</incregexes></context></configuration>"""


def public(_host):
    return ["93.184.216.34"]


class DastTargetTests(unittest.TestCase):
    def test_extract(self):
        self.assertEqual(dast.extract_target(CONTEXT), "https://staging.example.com")

    def test_extract_missing(self):
        with self.assertRaises(dast.TargetError):
            dast.extract_target("<configuration/>")

    def test_validate_ok(self):
        self.assertEqual(dast.validate_target("https://staging.example.com", resolver=public), "https://staging.example.com")

    def test_validate_rejects(self):
        for url in ["http://example.com", "https://localhost", "https://10.0.0.1", "https://127.0.0.1", "https://svc.internal"]:
            with self.subTest(url=url), self.assertRaises(dast.TargetError):
                dast.validate_target(url)

    def test_rejects_hostname_resolving_to_non_public(self):
        for address in ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1"]:
            with self.subTest(address=address), self.assertRaises(dast.TargetError):
                dast.validate_target("https://evil.example.com", resolver=lambda _h, a=address: [a])
        with self.assertRaises(dast.TargetError):
            dast.validate_target("https://evil.example.com", resolver=lambda _h: ["93.184.216.34", "10.0.0.5"])

    def test_allowed_hosts(self):
        with self.assertRaises(dast.TargetError):
            dast.validate_target("https://a.example.com", ["b.example.com"], resolver=public)
        dast.validate_target("https://a.example.com", ["A.example.com"], resolver=public)


if __name__ == "__main__":
    unittest.main()
