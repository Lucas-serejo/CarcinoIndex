"""Load the repository .env for local CLI tools only; the backend stays environment-backed.

Supports the project's format: NAME=value, blank lines, # comments, optional
outer single/double quotes, split on the first "=". No variable expansion and
no end-of-line comments. Values are never printed.
"""

import os
import re
from pathlib import Path

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def parse_env_file(path: Path) -> dict[str, str]:
    values = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not separator or not _NAME.fullmatch(name):
            raise ValueError(f"Invalid entry on line {number} of {path.name}. Expected NAME=value.")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    return values


def load_local_env(path: Path) -> list[str]:
    """Add variables from path without overriding the process environment.

    A missing file is a no-op. The whole file is validated before anything is
    set. Returns the names that were loaded.
    """
    if not path.is_file():
        return []
    loaded = []
    for name, value in parse_env_file(path).items():
        if name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded
