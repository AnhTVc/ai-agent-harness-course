"""Load small local configuration files without adding a runtime dependency."""

import os
from pathlib import Path


def load_env_file(path):
    """Load simple KEY=VALUE lines while preserving explicit shell settings.

    This intentionally supports only the format used by the lesson's .env
    example. It does not evaluate shell syntax, variable expansion, or commands.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        # Ignore blank lines and comments before parsing any key-value content.
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        # Restrict names to portable environment identifiers and keep shell
        # values authoritative when both a shell and local file define a key.
        if (
            not key
            or not key.replace("_", "").isalnum()
            or key[0].isdigit()
            or key in os.environ
        ):
            continue
        # Strip matching outer quotes only; no shell interpolation is performed.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ[key] = value
