#!/usr/bin/env python3
"""Download each live app's real App Store artwork into icons/<slug>.png.

Authoritative by construction: the bytes come from the same artwork Apple
serves on the listing. An app that is not live yields no file and is reported,
which is the intended outcome for MathPuzzlr until it ships.
"""
import json, pathlib, sys, urllib.request

SLUGS = {
    "huecheck": "6777696570",
    "countup": "6777696578",
    "memivo": "6797146656",
    "milestones": "6778199024",
    "noisenest": "6786730181",
    "subsnap": "6786732038",
}

OUT = pathlib.Path(__file__).resolve().parent.parent / "icons"


def lookup(app_id):
    url = f"https://itunes.apple.com/lookup?id={app_id}&country=us"
    raw = urllib.request.urlopen(url).read().decode("utf-8")
    # Apple's descriptions contain raw control characters that strict JSON rejects.
    return json.loads(raw, strict=False)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    missing = []
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
        dest = OUT / f"{slug}.png"
        dest.write_bytes(urllib.request.urlopen(art).read())
        print(f"OK    {slug:11} {dest.stat().st_size:>7} bytes  <- {art}")
    if missing:
        print(f"\nNot live, no icon written: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
