#!/usr/bin/env python3
"""Download each live app's real App Store artwork into icons/<slug>.png.

Authoritative by construction: the bytes come from the same artwork Apple
serves on the listing. An app that is not live yields no file and is reported,
which is the intended outcome for MathPuzzlr until it ships.
"""
import json, pathlib, struct, sys, urllib.request

SLUGS = {
    "huecheck": "6777696570",
    "countup": "6777696578",
    "memivo": "6797146656",
    "milestones": "6778199024",
    "noisenest": "6786730181",
    "subsnap": "6786732038",
    "angrymath": "6765843459",
    "mathbell": "6818749420",
}

OUT = pathlib.Path(__file__).resolve().parent.parent / "icons"


def lookup(app_id):
    url = f"https://itunes.apple.com/lookup?id={app_id}&country=us"
    raw = urllib.request.urlopen(url).read().decode("utf-8")
    # Apple's descriptions contain raw control characters that strict JSON rejects.
    return json.loads(raw, strict=False)


def png_problem(payload):
    """Describe why `payload` is not a 256x256 PNG, or None if it is one.

    Checks content, never file size: these icons legitimately range from about
    8KB to 100KB because a flat-design icon compresses to a fraction of a
    photographic one, so a size floor rejects valid artwork. The signature
    catches an HTML error page or a JPEG, and IHDR catches a truncated or
    wrong-size image.
    """
    if payload[:8] != b"\x89PNG\r\n\x1a\n":
        return f"not a PNG, starts with {payload[:4].hex()}"
    if payload[12:16] != b"IHDR":
        return "no IHDR header"
    width, height = struct.unpack(">II", payload[16:24])
    if (width, height) != (256, 256):
        return f"is {width}x{height}, expected 256x256"
    return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    missing = []
    corrupt = []
    for slug, app_id in sorted(SLUGS.items()):
        data = lookup(app_id)
        if not data["resultCount"]:
            missing.append(f"{slug} ({app_id})")
            print(f"SKIP  {slug:11} not live, resultCount 0")
            continue
        # artworkUrl512 points at ".../512x512bb.jpg". Apple's image CDN honours
        # both the size and the extension in that last path component, so ask it
        # for a 256px PNG instead: lossless, and a quarter the bytes of the 512
        # PNG. 256px covers the 52pt settings row at 3x with headroom.
        art = data["results"][0]["artworkUrl512"].rsplit("/", 1)[0] + "/256x256bb.png"
        payload = urllib.request.urlopen(art).read()

        # Validate before writing, never after. This transform assumes Apple's
        # "WxHbb.ext" URL convention; if that ever changes, the request still
        # returns 200 with something that is not the image we asked for, and
        # without this guard the script would commit it silently.
        problem = png_problem(payload)
        if problem:
            corrupt.append(f"{slug} ({problem})")
            print(f"FAIL  {slug:11} {problem}  <- {art}")
            continue

        dest = OUT / f"{slug}.png"
        dest.write_bytes(payload)
        print(f"OK    {slug:11} {dest.stat().st_size:>7} bytes  <- {art}")
    if missing:
        print(f"\nNot live, no icon written: {', '.join(missing)}")

    # An unreleased app is expected and exits 0. A download that came back as
    # something other than a 256x256 PNG is a real failure and must not be
    # mistaken for one, so it exits non-zero even when run unattended.
    if corrupt:
        print(f"\nBad artwork, not written: {', '.join(corrupt)}")
        print("The Apple CDN URL convention may have changed. Do not commit.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
