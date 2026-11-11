"""Estimate a DC property's monthly income as an Airbnb vs. a long-term rental.

Run it and answer the questions:
    .venv/bin/python estimate.py

It asks, in order:
  1. Address (looked up with the free U.S. Census geocoder), or latitude, longitude.
  2. Setup: part of the home you live in (DC "hosted" rental, no night cap),
     or your whole home while you're away (DC "unhosted" rental, max 90 nights/year).
  3. Property type.
  4. Bedrooms in the space available to guests.
  5. Optionally, how many nights a year you expect guests to book. The question
     shows what similar listings get, and the cap if it applies. Press Enter
     to use the median of similar listings.

Any answer can be given as a flag instead, to skip its question, e.g.:
    .venv/bin/python estimate.py --address "1600 Pennsylvania Ave NW" --setup part --bedrooms 1 --type Apartment

Costs come from assumptions.py:
    .venv/bin/python estimate.py --assumptions               # list them, with sources
    .venv/bin/python estimate.py --set airbnb_fee_percent=3  # change one for this run

Uses the clean tables from clean_data.py, so run that first.
"""
import argparse

from analysis import (LEGAL_NOTES, SETUPS, Property, airbnb_basis, analyze, load_data,
                      money, size_label)
from assumptions import print_settings, with_overrides
from costs import net
from geocode import GeocodeError, coordinates, geocode, in_dc
from models import MIN_COMPS, PROPERTY_TYPES_FOR_INPUT

SHOW_COMPS = 5  # how many of the closest comps to print


# ---------- Asking questions ----------

def ask(question, convert, check=None, allow_blank=False):
    """Ask until the answer converts cleanly and passes `check`.

    With allow_blank=True, pressing Enter returns None.
    """
    while True:
        answer = input(question + " ").strip()
        if not answer and allow_blank:
            return None
        try:
            value = convert(answer)
            if check is None or check(value):
                return value
        except ValueError:
            pass
        print("  Sorry, I didn't understand that. Please try again.")


def ask_setup():
    print("Are you renting out:")
    print("  1) Part of the home you live in (a basement unit, carriage house...)")
    print("  2) Your whole home, while you're away")
    choice = ask("Enter 1 or 2:", int, check=lambda v: v in (1, 2))
    return "part" if choice == 1 else "whole"


def ask_type():
    print("Property type:")
    for i, name in enumerate(PROPERTY_TYPES_FOR_INPUT, start=1):
        print(f"  {i}) {name}")
    choice = ask(f"Enter 1-{len(PROPERTY_TYPES_FOR_INPUT)}:", int,
                 check=lambda v: 1 <= v <= len(PROPERTY_TYPES_FOR_INPUT))
    return PROPERTY_TYPES_FOR_INPUT[choice - 1]


def find_location(text):
    """An address or 'lat, lon' -> (lat, lon, description). Returns None, with a message, if not found."""
    coords = coordinates(text)
    if coords:
        if not in_dc(coords):
            print("  Those coordinates aren't in DC.")
            return None
        return coords[0], coords[1], f"({coords[0]}, {coords[1]})"
    try:
        place = geocode(text)
    except GeocodeError as e:
        print(f"  {e} You can enter latitude, longitude instead.")
        return None
    if place is None:
        print("  Couldn't find that DC address. Include the house number and street, "
              "e.g. 1600 Pennsylvania Ave NW.")
        return None
    return place["lat"], place["lon"], f"{place['address']} ({place['tract']})"


def ask_location():
    print("Address of the property (or latitude, longitude):")
    while True:
        found = find_location(input("Address: ").strip())
        if found is None:
            continue
        print(f"  Found: {found[2]}")
        if input("  Is that right? (press Enter for yes, or type n): ").strip().lower() not in ("n", "no"):
            return found


def fill_in_property(args):
    """Ask for anything about the property that wasn't given as a flag."""
    if args.address:
        found = find_location(args.address)
        if found is None:
            raise SystemExit(1)
        args.lat, args.lon, args.place = found
    elif args.lat is not None and args.lon is not None:
        args.place = f"({args.lat}, {args.lon})"
    else:
        args.lat, args.lon, args.place = ask_location()
    if args.setup is None:
        print()
        args.setup = ask_setup()
    if args.type is None:
        print()
        args.type = ask_type()
    if args.bedrooms is None:
        print()
        args.bedrooms = ask("Bedrooms in the space available to guests (0 for a studio):", int,
                            check=lambda v: 0 <= v <= 6)


def ask_nights(setup, typical, cap):
    """Optional guess of nights booked per year. None means use the typical (median)."""
    print()
    if setup == "part":
        print("Since you'd live on-site, DC doesn't cap how many nights you can host.")
        print(f"Similar hosted listings nearby are booked about {typical:.0f} nights a year.")
    else:
        print(f"DC caps whole-home vacation rentals at {cap} nights a year.")
        print(f"Most book fewer: a typical one in DC is booked about {typical:.0f} nights a year.")
    nights = ask(f"How many nights a year do you expect guests to book? (press Enter to use {typical:.0f}):",
                 int, check=lambda v: 0 < v <= 365, allow_blank=True)
    if nights and cap and nights > cap:
        print(f"  That's over DC's cap, so I'll use {cap}.")
        nights = cap
    return nights


# ---------- Printing results ----------

def print_comps(comps, columns):
    for _, c in comps.head(SHOW_COMPS).iterrows():
        size = f"{c['bedrooms']:.0f}bd/{c['bathrooms']:g}ba"
        details = "  ".join(fmt(c[col]) for col, fmt in columns)
        print(f"      {c['miles']:.2f} mi  {size:<10} {c['property_type']:<13}  {details}")


def print_lines(title, lines):
    """Print income and cost lines (skipping zeros) and their total."""
    print(f"  {title}")
    for label, amount in lines:
        if round(amount):
            text = ("-" if amount < 0 else "") + money(abs(amount))
            print(f"    {label:<32} {text:>9}")
    print(f"    {'Net income':<32} {money(net(lines)):>9} per month")


def print_rent(r, prop):
    print("LONG-TERM RENTAL")
    if r is None:
        print("  No comparable rentals found.\n")
        return
    low, high = r["typical_range"]
    print(f"  Typical rent: {money(r['estimate'])}/month   "
          f"(80% sure the typical comp is {money(low)}-{money(high)})")
    print(f"  Based on {len(r['comps'])} {size_label(prop.bedrooms)} rentals within {r['radius']} mi.")
    print(f"  Individual rentals vary more: the middle half rent for "
          f"{money(r['middle_half'][0])}-{money(r['middle_half'][1])}.")
    note = "agrees" if r["check_agrees"] else "disagrees, so treat this estimate with caution"
    print(f"  Cross-check (regression using property type too): "
          f"{money(r['check'])} ({r['check_gap']:+.0f}%, {note})")
    if r["few_comps"]:
        print(f"  Warning: fewer than {MIN_COMPS} comps, so this estimate is shaky.")
    print("  Closest comps:")
    print_comps(r["comps"], [("monthly_income", lambda v: f"{money(v)}/mo")])
    print()
    print_lines("After costs:", r["lines"])
    print()


def print_airbnb(b, ab, prop):
    print("AIRBNB")
    if b is None:
        print("  No comparable Airbnbs found.\n")
        return
    low, high = b["price_range"]
    print(f"  Nightly price: {money(b['price'])}   (80% sure the typical comp is {money(low)}-{money(high)})")
    print(f"  Based on {len(b['comps'])} {size_label(prop.bedrooms)} Airbnbs within {b['radius']} mi.")
    print(f"  Nights booked per year, from {b['source']}.")
    print("  Closest comps:")
    print_comps(b["comps"], [("nightly_price", lambda v: f"{money(v)}/night"),
                             ("nights_booked", lambda v: f"{v:.0f} nights")])
    print()
    print(f"  Monthly income, averaged over the year:  {'gross':>8} {'net':>9}")
    for row in ab["rows"]:
        marker = "  <- used below" if row["chosen"] else ""
        print(f"    {row['level']:<18} {row['nights']:>4.0f} nights/year  "
              f"{money(row['gross']):>8} {money(row['net']):>9}{marker}")
    print()
    print_lines(f"After costs, at {ab['chosen_nights']:.0f} nights/year:", ab["lines"])
    print()


def print_recommendation(rec):
    print("RECOMMENDATION (after costs)")
    print(f"  {rec['headline']}")
    if rec["winner"] is None:
        return
    for note in rec["notes"]:
        print(f"  {note}")
    print("  Costs are assumptions: see them with --assumptions, change one with --set KEY=VALUE.")
    for note in LEGAL_NOTES:
        print(f"  {note}")


def parse_overrides(pairs):
    """['airbnb_fee_percent=3', ...] -> {'airbnb_fee_percent': 3.0}"""
    overrides = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        try:
            overrides[key.strip()] = float(value)
        except ValueError:
            raise SystemExit(f"--set needs KEY=NUMBER, got: {pair}")
    return overrides


def main():
    parser = argparse.ArgumentParser(description="Compare Airbnb vs. long-term rent for a DC property. "
                                                 "Any answer not given as a flag is asked for.")
    parser.add_argument("--setup", choices=SETUPS,
                        help="part: part of your home, while you live there; whole: whole home while away")
    parser.add_argument("--address", help='street address in DC, e.g. "1600 Pennsylvania Ave NW"')
    parser.add_argument("--lat", type=float, help="latitude, e.g. 38.8899 (instead of an address)")
    parser.add_argument("--lon", type=float, help="longitude, e.g. -76.9905")
    parser.add_argument("--bedrooms", type=int, help="bedrooms in the space you'd rent out (0 for a studio)")
    parser.add_argument("--type", choices=PROPERTY_TYPES_FOR_INPUT)
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="change a cost assumption for this run (repeatable)")
    parser.add_argument("--assumptions", action="store_true", help="list the cost assumptions and exit")
    args = parser.parse_args()

    try:
        a = with_overrides(parse_overrides(args.set))
    except ValueError as e:
        raise SystemExit(f"{e}. See them all with --assumptions.")
    if args.assumptions:
        print_settings(a)
        return

    fill_in_property(args)
    prop = Property(lat=args.lat, lon=args.lon, setup=args.setup, bedrooms=args.bedrooms,
                    type=args.type, place=args.place)
    airbnb, rentals = load_data()
    basis = airbnb_basis(airbnb, prop)
    nights = ask_nights(prop.setup, basis["typical"], basis["cap"]) if basis else None
    result = analyze(prop, nights, a, airbnb, rentals, basis)

    print(f"\nProperty: {size_label(prop.bedrooms)} {prop.type}")
    print(f"Location: {prop.place}")
    print(f"Renting out: {SETUPS[prop.setup]}\n")
    print_rent(result["rent"], prop)
    print_airbnb(result["basis"], result["airbnb"], prop)
    print_recommendation(result["recommendation"])


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):  # Ctrl+C, or input ended
        print("\nCancelled.")
        raise SystemExit(1)
