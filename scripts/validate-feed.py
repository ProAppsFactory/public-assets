#!/usr/bin/env python3
"""Validate both cross-promo feeds against Apple's live lookup API.

Fails on any appStoreId that returns resultCount 0, any icon that is missing
or not a real image, any placement referencing an unknown app, any app
promoting itself, and any em dash anywhere in either file.
"""
import json, pathlib, re, struct, sys, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
V2 = ROOT / "cross-promo-v2.json"
LEGACY = ROOT / "cross-promo.json"
ID_IN_URL = re.compile(r"/id(\d+)")

failures = []


def fail(msg):
    failures.append(msg)
    print(f"FAIL  {msg}")


def resolves(app_id):
    url = f"https://itunes.apple.com/lookup?id={app_id}&country=us"
    try:
        raw = urllib.request.urlopen(url, timeout=20).read().decode("utf-8")
    except urllib.error.URLError as e:
        fail(f"lookup for {app_id} could not reach Apple: {e}")
        return None
    return json.loads(raw, strict=False)


def check_id(app_id, where):
    data = resolves(app_id)
    if data is None:
        return
    if not data["resultCount"]:
        fail(f"{where}: appStoreId {app_id} returns resultCount 0")
    else:
        print(f"OK    {where:28} {app_id} -> {data['results'][0]['trackName']}")


def check_icon(path, where):
    """Validate an icon by its actual content, never by name or file size.

    File size is not a usable signal here: observed icons span 8KB to 101KB
    because a flat-design icon compresses to a fraction of a photographic one,
    so any "too small to be real" floor rejects valid artwork. The PNG
    signature rules out an HTML error page, and the IHDR header carries the
    true dimensions, which catches a truncated or wrong-size download.
    """
    if not path.exists():
        fail(f"{where}: icon {path.name} does not exist")
        return
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        fail(f"{where}: icon {path.name} is not a PNG, starts with {data[:4].hex()}")
        return
    if data[12:16] != b"IHDR":
        fail(f"{where}: icon {path.name} has no IHDR header")
        return
    width, height = struct.unpack(">II", data[16:24])
    if (width, height) != (256, 256):
        fail(f"{where}: icon {path.name} is {width}x{height}, expected 256x256")


def main():
    for path in (V2, LEGACY):
        if "—" in path.read_text():
            fail(f"{path.name} contains an em dash")

    v2 = json.loads(V2.read_text())
    for slug, app in sorted(v2["apps"].items()):
        check_id(app["appStoreId"], f"v2/{slug}")
        check_icon(ROOT / app["icon"], f"v2/{slug}")

    for src, targets in sorted(v2["placements"].items()):
        if src not in v2["apps"]:
            fail(f"v2/placements: source {src} is not in the catalogue")
        if src in targets:
            fail(f"v2/placements: {src} promotes itself")
        for t in targets:
            if t not in v2["apps"]:
                fail(f"v2/placements: {src} targets unknown app {t}")

    legacy = json.loads(LEGACY.read_text())
    if not isinstance(legacy, list):
        fail("legacy feed is no longer a flat array; shipped decoders will break")
    else:
        for entry in legacy:
            m = ID_IN_URL.search(entry["appStoreURL"])
            if not m:
                fail(f"legacy/{entry['id']}: appStoreURL has no /id<digits> segment")
            else:
                check_id(m.group(1), f"legacy/{entry['id']}")

    if failures:
        print(f"\n{len(failures)} failure(s).")
        return 1
    print("\nAll feed entries resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
