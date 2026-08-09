#!/usr/bin/env python3
"""Validate both cross-promo feeds against Apple's live lookup API.

Exit codes are deliberately three-way, because "this feed is wrong" and "we
could not ask Apple today" are different events and must not share a signal:

  0   everything verified
  1   a real defect in a feed. Fix the feed.
  75  could not reach Apple after retries. Nothing was disproved. EX_TEMPFAIL.

This runs on every push and on a daily schedule, and it is the check that
exists because three fabricated App Store IDs shipped to production unnoticed.
A check that goes red on a transient network blip is a check people learn to
re-run without reading, which would rebuild the exact complacency it is meant
to prevent. So transient failures are retried, then reported as 75, and the
workflow surfaces that as a warning rather than a broken build.
"""
import json, pathlib, re, struct, sys, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
V2 = ROOT / "cross-promo-v2.json"
LEGACY = ROOT / "cross-promo.json"
ID_IN_URL = re.compile(r"/id(\d+)")
EXIT_TEMPFAIL = 75
LOOKUP_ATTEMPTS = 3

failures = []     # real defects in the feeds
unreachable = []  # could not ask Apple. Proves nothing either way.


def fail(msg):
    failures.append(msg)
    print(f"FAIL  {msg}")


def unavailable(msg):
    unreachable.append(msg)
    print(f"SKIP  {msg}")


def resolves(app_id):
    """Look up an app, retrying transient failures.

    Returns the decoded response, or None if Apple could not be reached or
    answered with something that is not the JSON we expect. None means
    "unknown", never "dead": the caller must not treat it as a defect.
    """
    url = f"https://itunes.apple.com/lookup?id={app_id}&country=us"
    for attempt in range(1, LOOKUP_ATTEMPTS + 1):
        try:
            raw = urllib.request.urlopen(url, timeout=20).read().decode("utf-8")
        except urllib.error.URLError as e:
            reason = f"{e}"
        else:
            try:
                data = json.loads(raw, strict=False)
            except json.JSONDecodeError as e:
                # A 200 carrying something that is not JSON, for example a
                # proxy or captive-portal interstitial.
                reason = f"response was not JSON ({e})"
            else:
                if "resultCount" not in data:
                    reason = "response had no resultCount field"
                else:
                    return data
        if attempt < LOOKUP_ATTEMPTS:
            time.sleep(2 ** attempt)
    unavailable(f"lookup for {app_id} could not reach Apple after "
                f"{LOOKUP_ATTEMPTS} attempts: {reason}")
    return None


def check_id(app_id, where):
    data = resolves(app_id)
    if data is None:
        return
    if not data["resultCount"]:
        fail(f"{where}: appStoreId {app_id} returns resultCount 0")
    else:
        name = data["results"][0].get("trackName", "(no trackName)")
        print(f"OK    {where:28} {app_id} -> {name}")


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


def em_dash_locations(node, trail=""):
    """Yield paths to decoded string values containing an em dash.

    This walks the DECODED structure rather than grepping the raw file, because
    `json.dumps` escapes non-ASCII by default: an em dash can sit in the file as
    the six characters \\u2014 and sail past a text search while still decoding
    to a real em dash in every app that reads the feed. Any tool that rewrites
    these files with the standard library produces exactly that form.
    """
    if isinstance(node, str):
        if "—" in node:
            yield trail or "(root)"
    elif isinstance(node, dict):
        for key, value in node.items():
            if "—" in key:
                yield f"{trail}.{key} (in the key itself)"
            yield from em_dash_locations(value, f"{trail}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from em_dash_locations(value, f"{trail}[{index}]")


def main():
    # Parse each feed once and reuse it.
    feeds = {path: json.loads(path.read_text()) for path in (V2, LEGACY)}

    for path, data in feeds.items():
        # Catch the raw character, and separately the escaped form, by checking
        # the decoded values. Either one reaches a user as an em dash.
        for where in em_dash_locations(data):
            fail(f"{path.name} contains an em dash at {where}")

    v2 = feeds[V2]
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

    legacy = feeds[LEGACY]
    if not isinstance(legacy, list):
        fail("legacy feed is no longer a flat array; shipped decoders will break")
    else:
        for entry in legacy:
            m = ID_IN_URL.search(entry["appStoreURL"])
            if not m:
                fail(f"legacy/{entry['id']}: appStoreURL has no /id<digits> segment")
            else:
                check_id(m.group(1), f"legacy/{entry['id']}")

    # A real defect always wins: if anything is genuinely wrong, say so, even
    # if some other lookup also happened to be unreachable.
    if failures:
        print(f"\n{len(failures)} failure(s).")
        return 1

    # Nothing was disproved, but nothing was fully proved either. Distinct exit
    # code so CI can warn instead of going red on someone else's outage.
    if unreachable:
        print(f"\nCould not verify {len(unreachable)} entr(y/ies): Apple was "
              f"unreachable. No defect was found. Exiting {EXIT_TEMPFAIL}.")
        return EXIT_TEMPFAIL

    print("\nAll feed entries resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
