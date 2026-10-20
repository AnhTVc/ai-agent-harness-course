"""HTTPS requests must retain normal certificate and hostname validation."""

import ssl
import unittest

from agent_lab.network import verified_https_context


class TrustedTLSContextTests(unittest.TestCase):
    """Keep the optional CA fallback secure instead of bypassing TLS checks."""

    def test_https_context_requires_certificate_and_hostname_verification(self):
        context = verified_https_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)


if __name__ == "__main__":
    unittest.main()
