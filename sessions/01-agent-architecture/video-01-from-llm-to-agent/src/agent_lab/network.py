"""Shared certificate-verifying TLS configuration for optional HTTPS calls."""

import ssl


def verified_https_context():
    """Use system roots or certifi; never allow insecure certificate bypasses."""
    context = ssl.create_default_context()
    # Some Python distributions ship without the operating system CA store.
    if context.get_ca_certs():
        return context
    try:
        import certifi
    except ImportError as exc:
        raise RuntimeError(
            "No trusted CA roots are available; install the optional CA bundle from requirements-cloudflare.txt."
        ) from exc
    return ssl.create_default_context(cafile=certifi.where())
