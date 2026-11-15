"""Import credentials from an authorized HomeID account or exported database."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .client import DeviceConfig


def appliance_id(appliance: dict[str, Any]) -> str:
    """HAL appliances need not have an id field; resolve their self link."""
    if appliance.get("id"):
        return str(appliance["id"])
    href = appliance.get("_links", {}).get("self", {}).get("href", "")
    path = urlsplit(href).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if "/Appliance/" in path else ""


def from_appliance(appliance: dict[str, Any], *, host: str = "", use_https: bool = True,
                   refresh_token: str = "", thing_name: str = "") -> DeviceConfig:
    credentials = appliance.get("localCredentials") or {}
    if isinstance(credentials, str):
        credentials = json.loads(credentials)
    if not isinstance(credentials, dict):
        raise TypeError("Unexpected localCredentials format")
    client_id = appliance.get("clientId") or credentials.get("clientId") or credentials.get("client_id", "")
    secret = appliance.get("clientSecret") or credentials.get("clientSecret") or credentials.get("client_secret", "")
    config = DeviceConfig(
        host=host, model=appliance.get("ctn") or appliance.get("modelId") or "HD9285",
        device_id=appliance.get("externalDeviceId") or appliance.get("id", ""),
        appliance_id=appliance_id(appliance),
        transport="local" if client_id and secret and host else "fusion",
        use_https=use_https, client_id=client_id, client_secret=secret,
        encryption_key=credentials.get("encryptionKey") or credentials.get("encryption_key", ""),
        refresh_token=refresh_token, thing_name=thing_name or appliance.get("thingName", ""),
    )
    config.validate()
    return config


def from_database(path: Path, device_id: str | None = None,
                  host: str | None = None) -> DeviceConfig:
    """Read-only: schema comes from APK NetworkNodeDatabaseSchema.java."""
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute("SELECT * FROM network_node")]
    rows = [row for row in rows if row.get("client_id") and row.get("client_secret")]
    if device_id:
        rows = [row for row in rows if device_id in (str(row.get("cppid")), str(row.get("_id")), row.get("mac_address"))]
    if len(rows) != 1:
        raise ValueError(f"Expected one paired device, found {len(rows)}; select with --device-id")
    row = rows[0]
    config = DeviceConfig(
        host=host or row.get("ip_address") or "", model=row.get("model_id") or "HD9285",
        device_id=row.get("cppid") or "", client_id=row["client_id"],
        client_secret=row["client_secret"], encryption_key=row.get("encryption_key") or "",
        use_https=bool(row.get("https", 1)),
    )
    config.validate()
    return config
