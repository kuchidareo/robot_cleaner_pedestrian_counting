#!/usr/bin/env python3
import json
from datetime import datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


token_module_path = Path(__file__).with_name("0_token_extractor.py")
token_module_spec = spec_from_file_location("token_extractor", token_module_path)
token_module = module_from_spec(token_module_spec)
token_module_spec.loader.exec_module(token_module)
QrCodeXiaomiCloudConnector = token_module.QrCodeXiaomiCloudConnector
args = token_module.args


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


def get_map_properties(connector, server, did):
    # Service 10 exposes the map and the separately uploaded trajectory file.
    candidates = {"map": (10, 1), "trajectory": (10, 2), "clean_record": (10, 3)}
    params = [
        {"did": str(did), "siid": siid, "piid": piid}
        for siid, piid in candidates.values()
    ]
    response = api(connector, server, "/miotspec/prop/get", {"params": params})
    properties = {}
    for prop in (response or {}).get("result", []):
        value = prop.get("value")
        if not value:
            continue
        key = next(
            (name for name, ids in candidates.items()
             if ids == (prop.get("siid"), prop.get("piid"))),
            None,
        )
        if not key:
            continue
        if key == "clean_record":
            try:
                properties[key] = json.loads(value) if isinstance(value, str) else value
            except json.JSONDecodeError:
                properties[key] = value
            continue

        # Object names must be cloud paths/identifiers, not status integers.
        if isinstance(value, int):
            continue
        try:
            value = json.loads(value).get("obj_name", value)
        except (json.JSONDecodeError, TypeError):
            pass
        if isinstance(value, str):
            if key == "trajectory" and value.isdigit():
                continue
            properties[key] = value.rsplit("/", 1)[-1]
    return properties


def download_object(connector, server, did, object_name, output):
    obj_name = f"{connector.userId}/{did}/{object_name}"
    response = api(connector, server, "/v2/home/get_interim_file_url_pro", {"obj_name": obj_name})
    url = (response or {}).get("result", {}).get("url")
    if not url:
        raise RuntimeError(f"Xiaomi Cloud did not return a URL for {object_name}")

    download = connector._session.get(url, timeout=30)
    download.raise_for_status()
    raw_object = download.content
    if raw_object.startswith(b"Object Not Found:"):
        raise RuntimeError(f"Xiaomi Cloud object does not exist: {object_name}")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw_object)
    print(f"Downloaded {len(raw_object)} bytes to {output}")


def main():
    server = args.server or "de"
    if args.output:
        output = Path(args.output)
        run_directory = output.parent
    else:
        run_directory = Path("logs") / datetime.now().strftime("%Y%m%d%H%M%S")
        output = run_directory / "s40c_map.zlib.enc"
    run_directory.mkdir(parents=True, exist_ok=True)

    connector = QrCodeXiaomiCloudConnector()
    if not connector.login():
        raise SystemExit("Cloud QR login failed")

    vacuum = find_vacuum(connector, server)
    if not vacuum:
        raise SystemExit(f"{MODEL} was not found on the {server} server")

    properties = get_map_properties(connector, server, vacuum["did"])
    if "map" not in properties:
        raise SystemExit("Vacuum found, but Xiaomi Cloud did not return its current map name")

    download_object(connector, server, vacuum["did"], properties["map"], output)
    if "clean_record" in properties:
        record_output = run_directory / "s40c_clean_record.json"
        record_output.write_text(json.dumps(properties["clean_record"], indent=2) + "\n")
        print(f"Saved cleaning record to {record_output}")
    else:
        print("Xiaomi Cloud did not return a cleaning record")

    if "trajectory" in properties:
        download_object(
            connector,
            server,
            vacuum["did"],
            properties["trajectory"],
            run_directory / "s40c_trajectory.zlib.enc",
        )
    else:
        print("Xiaomi Cloud did not return a separate trajectory object name")

    print(f"Saved this download under {run_directory}")
    print(
        "Extract it with:\n"
        f"  python 2_extract_s40c_trajectory.py {output}"
    )


if __name__ == "__main__":
    main()
