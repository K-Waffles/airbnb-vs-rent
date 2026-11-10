"""Turn a street address into latitude/longitude, using the U.S. Census geocoder.

The Census Bureau's geocoder is free and needs no API key:
    https://geocoding.geo.census.gov/geocoder/
It also returns the census tract, which we may use later to pick comps.

Note: the address you type is sent to the Census Bureau to look it up.
"""
import json
import urllib.parse
import urllib.request

API_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
DC_STATE_CODE = "11"  # DC's state code in Census data
TIMEOUT_SECONDS = 20


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
