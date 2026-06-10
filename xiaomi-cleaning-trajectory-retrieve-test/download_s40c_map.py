#!/usr/bin/env python3
import json
from pathlib import Path

from token_extractor import QrCodeXiaomiCloudConnector, args


MODEL = "xiaomi.vacuum.e101gb"


def api(connector, server, path, data):
    url = connector.get_api_url(server) + path
    return connector.execute_api_call_encrypted(url, {"data": json.dumps(data, separators=(",", ":"))})


def find_vacuum(connector, server):
    homes = connector.get_homes(server)
    if not homes:
        return None

    for home in homes.get("result", {}).get("homelist", []):
        devices = connector.get_devices(server, home["id"], connector.userId)
        for device in (devices or {}).get("result", {}).get("device_info", []) or []:
            if device.get("model") == MODEL:
                return device
    return None


def get_map_name(connector, server, did):
    # S40C uses the standard Xiaomi vacuum map property. Extra candidates are
    # read-only fallbacks used by closely related firmware variants.
    candidates = [(10, 1), (10, 2), (9, 1), (7, 1)]
    params = [{"did": str(did), "siid": siid, "piid": piid} for siid, piid in candidates]
    response = api(connector, server, "/miotspec/prop/get", {"params": params})
    for prop in (response or {}).get("result", []):
        value = prop.get("value")
        if not value:
            continue
        if isinstance(value, int):
            return str(value)
        try:
            value = json.loads(value).get("obj_name", value)
        except (json.JSONDecodeError, TypeError):
            pass
        if isinstance(value, str):
            return value.rsplit("/", 1)[-1]
    return None


def main():
    server = args.server or "de"
    output = args.output or "logs/s40c_map.zlib.enc"

    connector = QrCodeXiaomiCloudConnector()
    if not connector.login():
        raise SystemExit("Cloud QR login failed")

    vacuum = find_vacuum(connector, server)
    if not vacuum:
        raise SystemExit(f"{MODEL} was not found on the {server} server")

    map_name = get_map_name(connector, server, vacuum["did"])
    if not map_name:
        raise SystemExit("Vacuum found, but Xiaomi Cloud did not return its current map name")

    obj_name = f'{connector.userId}/{vacuum["did"]}/{map_name}'
    response = api(connector, server, "/v2/home/get_interim_file_url_pro", {"obj_name": obj_name})
    url = (response or {}).get("result", {}).get("url")
    if not url:
        raise SystemExit("Map name found, but Xiaomi Cloud did not return a download URL")

    raw_map = connector._session.get(url, timeout=30).content
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw_map)
    print(f"Downloaded {len(raw_map)} bytes to {output}")


if __name__ == "__main__":
    main()
