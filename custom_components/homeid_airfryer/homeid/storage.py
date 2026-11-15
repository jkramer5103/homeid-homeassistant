"""Atomic credential storage; never print secrets in normal command output."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def save_private(path: Path, data: dict[str, Any]) -> None:
    path = path.expanduser()
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o700)
    fd, temp_name = tempfile.mkstemp(prefix=".homeid-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(data, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_private(path: Path) -> dict[str, Any]:
    with path.expanduser().open() as source:
        result = json.load(source)
    if not isinstance(result, dict):
        raise TypeError("Configuration must be a JSON object")
    return result


def redacted(value: Any) -> Any:
    if isinstance(value, dict):
        secret_keys = {"clientid", "clientsecret", "encryptionkey", "credentials",
                       "localcredentials", "accesstoken", "refreshtoken", "idtoken",
                       "sessiontoken", "cookievalue", "signature", "pin", "vtoken"}
        return {key: "<redacted>" if key.lower().replace("_", "") in secret_keys
                else redacted(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redacted(item) for item in value]
    return value
