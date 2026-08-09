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

# Floors on catalogue size, so an empty or truncated feed cannot pass by
# vacuous success. These are the counts as of the last deliberate edit to
# either feed; shrinking the catalogue on purpose means editing these too.
MIN_LEGACY_ENTRIES = 5
MIN_V2_APPS = 6

# The legacy decoder declares all five fields non-optional and decodes the
# whole array with try?, so one entry missing any field drops every app.
REQUIRED_LEGACY_KEYS = ("id", "name", "tagline", "iconURL", "appStoreURL")

# Legacy icons are referenced by absolute raw.githubusercontent.com URL. Only
# a URL under this repo's own main branch can be resolved back to a local
# path and checked with check_icon.
LEGACY_ICON_PREFIX = (
    "https://raw.githubusercontent.com/ProAppsFactory/public-assets/main/"
)

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


def check_id(app_id, where, expected_name):
    """Confirm the id resolves, and that it resolves to the app we mean.

    Existence alone is not identity: a numerically adjacent sibling id (this
    portfolio's ids run in pairs like 6777696570 / 6777696578) resolves fine
    and prints a plausible looking name while pointing at the wrong app. The
    feed's own name must prefix the live trackName, case insensitively, or
    this is a defect, not a pass.
    """
    data = resolves(app_id)
    if data is None:
        return
    if not data["resultCount"]:
        fail(f"{where}: appStoreId {app_id} returns resultCount 0")
        return
    name = data["results"][0].get("trackName", "(no trackName)")
    if not name.lower().startswith(expected_name.lower()):
        fail(f"{where}: appStoreId {app_id} resolves to '{name}', which does "
             f"not start with the feed's name '{expected_name}'. Wrong id?")
        return
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
    if len(v2["apps"]) < MIN_V2_APPS:
        fail(f"v2 feed has only {len(v2['apps'])} app entries, expected at "
             f"least {MIN_V2_APPS}. An empty or truncated feed must not pass.")
    for slug, app in sorted(v2["apps"].items()):
        check_id(app["appStoreId"], f"v2/{slug}", app["name"])
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
    legacy_ids = {}  # slug -> appStoreId extracted from appStoreURL, for H3
    if not isinstance(legacy, list):
        fail("legacy feed is no longer a flat array; shipped decoders will break")
    else:
        if len(legacy) < MIN_LEGACY_ENTRIES:
            fail(f"legacy feed has only {len(legacy)} entries, expected at "
                 f"least {MIN_LEGACY_ENTRIES}. An empty or truncated feed "
                 f"must not pass.")
        for entry in legacy:
            eid = entry.get("id", "(entry with no id)")

            # The legacy decoder decodes all five fields as non-optional with
            # try?, so a single missing or blank field drops every app in the
            # array, not just this one. Check this before anything else reads
            # these keys, so a malformed entry fails loudly instead of
            # crashing the validator.
            missing = [k for k in REQUIRED_LEGACY_KEYS
                       if not isinstance(entry.get(k), str)
                       or not entry.get(k).strip()]
            if missing:
                fail(f"legacy/{eid}: missing or empty required key(s): "
                     f"{', '.join(missing)}")
                continue

            m = ID_IN_URL.search(entry["appStoreURL"])
            if not m:
                fail(f"legacy/{eid}: appStoreURL has no /id<digits> segment")
            else:
                check_id(m.group(1), f"legacy/{eid}", entry["name"])
                legacy_ids[eid] = m.group(1)

            icon_url = entry["iconURL"]
            if not icon_url.startswith(LEGACY_ICON_PREFIX):
                fail(f"legacy/{eid}: iconURL does not start with the "
                     f"expected prefix {LEGACY_ICON_PREFIX}: {icon_url}")
            else:
                rel = icon_url[len(LEGACY_ICON_PREFIX):]
                check_icon(ROOT / rel, f"legacy/{eid}")

    # The two feeds are maintained separately and nothing else relates them.
    # noisenest is deliberately v2 only, so this compares only the slugs
    # present in both, not the full catalogues.
    for slug in sorted(set(legacy_ids) & set(v2["apps"])):
        v2_id = v2["apps"][slug]["appStoreId"]
        legacy_id = legacy_ids[slug]
        if v2_id != legacy_id:
            fail(f"{slug}: v2 appStoreId {v2_id} does not match legacy "
                 f"appStoreId {legacy_id}. The two feeds disagree.")

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
