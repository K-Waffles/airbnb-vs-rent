"""Turn a street address into latitude/longitude, using the U.S. Census geocoder.

The Census Bureau's geocoder is free and needs no API key:
    https://geocoding.geo.census.gov/geocoder/
It also returns the census tract, which we may use later to pick comps.

Note: the address you type is sent to the Census Bureau to look it up.
"""
import json
import re
import urllib.parse
import urllib.request

API_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
DC_STATE_CODE = "11"  # DC's state code in Census data
TIMEOUT_SECONDS = 20


def coordinates(text):
    """'38.8899, -76.9905' -> (38.8899, -76.9905), or None if the text isn't coordinates.

    Requires decimals, so an address like '1600 Pennsylvania Ave NW 20500' isn't mistaken for them.
    """
    match = re.fullmatch(r"\s*(-?\d+\.\d+)\s*,?\s*(-?\d+\.\d+)\s*", text)
    return (float(match[1]), float(match[2])) if match else None


def in_dc(location):  # a rough box around DC
    lat, lon = location
    return 38.7 <= lat <= 39.1 and -77.2 <= lon <= -76.8


class GeocodeError(Exception):
    """The lookup couldn't run (no internet, service down, ...)."""


def geocode(address):
    """Look up a DC address.

    Returns {"address", "lat", "lon", "tract"}, or None if no DC address matched.
    Raises GeocodeError if the lookup itself failed.
    """
    # Most people won't type the city, so add it if it's missing.
    if "dc" not in address.lower() and "washington" not in address.lower():
        address += ", Washington, DC"

    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "layers": "Census Tracts",
        "format": "json",
    }
    url = API_URL + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            matches = json.load(response)["result"]["addressMatches"]
    except (OSError, ValueError, KeyError) as e:
        raise GeocodeError(f"Couldn't reach the Census geocoder ({e}).") from e

    for match in matches:
        tracts = match.get("geographies", {}).get("Census Tracts", [])
        tract = tracts[0] if tracts else {}
        if tract.get("STATE") != DC_STATE_CODE:
            continue  # matched somewhere outside DC
        return {
            "address": match["matchedAddress"],
            "lat": match["coordinates"]["y"],
            "lon": match["coordinates"]["x"],
            "tract": tract.get("NAME"),
        }
    return None


# ---------- Suggestions while typing ----------
# The Census geocoder needs a complete address, so suggestions come from
# Photon, a free address search built on OpenStreetMap data (no key needed):
#     https://photon.komoot.io
# What you type is sent to Photon as you type. It's a shared free service,
# so the app waits for a pause in typing before asking.

PHOTON_URL = "https://photon.komoot.io/api/"
DC_BOX = "-77.12,38.79,-76.90,39.0"  # west, south, east, north


def suggest_addresses(text, limit=5):
    """Up to `limit` DC street addresses that match partly typed text.

    Returns [{"label", "lat", "lon"}]. Returns [] if nothing matches or the
    service can't be reached (suggestions are a nice-to-have, never required).
    """
    if not text.strip():
        return []
    params = {"q": text, "limit": limit * 3, "bbox": DC_BOX, "lang": "en"}
    url = PHOTON_URL + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            features = json.load(response)["features"]
    except (OSError, ValueError, KeyError):
        return []

    # If the text starts with a house number, only keep addresses whose number starts with it.
    # (Otherwise "555" also matches streets like "5th Street".)
    typed_number = re.match(r"\s*(\d+)", text)

    suggestions, seen = [], set()
    for f in features:
        p = f["properties"]
        # Only real street addresses in DC (the search box also covers bits of MD and VA).
        if p.get("state") != "District of Columbia" or not p.get("housenumber") or not p.get("street"):
            continue
        if typed_number and not str(p["housenumber"]).startswith(typed_number[1]):
            continue
        label = f"{p['housenumber']} {p['street']}, Washington, DC {p.get('postcode', '')}".strip()
        if label in seen:
            continue  # the same building often appears more than once
        seen.add(label)
        lon, lat = f["geometry"]["coordinates"]
        suggestions.append({"label": label, "lat": lat, "lon": lon})
        if len(suggestions) == limit:
            break
    return suggestions
