"""Bounded SSDP discovery on the current LAN; does not pair or change devices."""

import math
import socket
import time
from typing import Any


def discover(timeout: float = 3) -> list[dict[str, Any]]:
    if not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise ValueError("Discovery timeout must be 0..30 seconds")
    query = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
             'MAN: "ssdp:discover"\r\nMX: 2\r\n'
             "ST: urn:philips-com:device:DiProduct:1\r\n\r\n")
    results = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.sendto(query.encode(), ("239.255.255.250", 1900))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            sock.settimeout(max(0.001, deadline - time.monotonic()))
            try:
                payload, address = sock.recvfrom(8192)
            except TimeoutError:
                break
            lines = payload.decode(errors="replace").split("\r\n")
            headers = {key.strip().lower(): value.strip()
                       for line in lines[1:] if ":" in line
                       for key, value in [line.split(":", 1)]}
            if "philips" not in (headers.get("st", "") + headers.get("server", "")).lower():
                continue
            results[address[0]] = {"host": address[0], **headers}
    return list(results.values())
