"""Estimate a DC property's monthly income as an Airbnb vs. a long-term rental.

Run it and answer the questions:
    .venv/bin/python estimate.py

It asks, in order:
  1. Location (latitude, longitude).
  2. Setup: part of the home you live in (DC "hosted" rental, no night cap),
     or your whole home while you're away (DC "unhosted" rental, max 90 nights/year).
  3. Property type.
  4. Bedrooms and bathrooms in the space available to guests.
  5. Optionally, how many nights a year you expect guests to book. The question
     shows what similar listings get, and the cap if it applies. Press Enter
     to use the median of similar listings.

Any answer can be given as a flag instead, to skip its question, e.g.:
    .venv/bin/python estimate.py --setup part --lat 38.8899 --lon -76.9905 --bedrooms 1 --bathrooms 1 --type Apartment

Costs come from assumptions.py:
    .venv/bin/python estimate.py --assumptions               # list them, with sources
    .venv/bin/python estimate.py --set airbnb_fee_percent=3  # change one for this run

Uses the clean tables from clean_data.py, so run that first.
"""
import argparse
import re

import pandas as pd

from assumptions import print_settings, with_overrides
from costs import airbnb_break_even_nights, airbnb_lines, net, rental_lines
from models import (MIN_COMPS, PROPERTY_TYPES_FOR_INPUT, booking_levels, find_comps,
                    median_range, regression_predict)

AIRBNB_CLEAN = "data/clean/airbnb.csv"
RENTALS_CLEAN = "data/clean/rentals.csv"

VACATION_RENTAL_CAP = 90  # DC's yearly night cap for unhosted (whole-home) rentals
DISAGREE_PERCENT = 15      # flag the rent estimate if the two methods differ by more
SHOW_COMPS = 5             # how many of the closest comps to print

SETUPS = {
    "part": "part of your home, while you live there (hosted: no night cap)",
    "whole": f"your whole home, while you're away (unhosted: max {VACATION_RENTAL_CAP} nights/year)",
}


def money(x):
    return f"${x:,.0f}"


def size_label(bedrooms):
    return "studio" if bedrooms == 0 else f"{bedrooms}-bedroom"


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


def two_numbers(text):
    """Pull exactly two numbers out of text: '38.89, -76.99' or '2 bed 1.5 bath'."""
    numbers = re.findall(r"-?\d+(?:\.\d+)?", text)
    if len(numbers) != 2:
        raise ValueError
    return float(numbers[0]), float(numbers[1])


def in_dc(location):  # a rough box around DC
    lat, lon = location
    return 38.7 <= lat <= 39.1 and -77.2 <= lon <= -76.8


def sensible_size(size):
    beds, baths = size
    return beds == int(beds) and 0 <= beds <= 6 and 0 < baths <= 6


def fill_in_property(args):
    """Ask for anything about the property that wasn't given as a flag."""
    if args.lat is None or args.lon is None:
        print("Location: latitude and longitude (in Google Maps, right-click the spot to copy them).")
        args.lat, args.lon = ask("Location (e.g. 38.8899, -76.9905):", two_numbers, check=in_dc)
    if args.setup is None:
        print()
        args.setup = ask_setup()
    if args.type is None:
        print()
        args.type = ask_type()
    if args.bedrooms is None or args.bathrooms is None:
        print()
        beds, baths = ask("Bedrooms and bathrooms in the space available to guests "
                          "(e.g. 2 bed 1.5 bath; 0 bedrooms for a studio):", two_numbers, check=sensible_size)
        args.bedrooms, args.bathrooms = int(beds), baths


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


# ---------- Printing helpers ----------

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


# ---------- Long-term rental ----------

def estimate_rent(rentals, args, a):
    """Print the rent estimate and costs. Returns (gross rent, net rent)."""
    comps, radius = find_comps(rentals, args.lat, args.lon, args.bedrooms)
    print("LONG-TERM RENTAL")
    if comps.empty:
        print("  No comparable rentals found.\n")
        return None, None

    rent = comps["monthly_income"]
    estimate = rent.median()
    low, high = median_range(rent)
    print(f"  Typical rent: {money(estimate)}/month   "
          f"(80% sure the typical comp is {money(low)}-{money(high)})")
    print(f"  Based on {len(comps)} {size_label(args.bedrooms)} rentals within {radius} mi.")
    print(f"  Individual rentals vary more: the middle half rent for "
          f"{money(rent.quantile(0.25))}-{money(rent.quantile(0.75))}.")

    check, _, _ = regression_predict(rentals, args.lat, args.lon, args.bedrooms,
                                     args.bathrooms, args.type)
    gap = (check - estimate) / estimate * 100
    note = "agrees" if abs(gap) <= DISAGREE_PERCENT else "disagrees, so treat this estimate with caution"
    print(f"  Cross-check (regression using bathrooms and type too): {money(check)} ({gap:+.0f}%, {note})")
    if len(comps) < MIN_COMPS:
        print(f"  Warning: fewer than {MIN_COMPS} comps, so this estimate is shaky.")
    print("  Closest comps:")
    print_comps(comps, [("monthly_income", lambda v: f"{money(v)}/mo")])
    print()
    lines = rental_lines(estimate, a)
    print_lines("After costs:", lines)
    print()
    return estimate, net(lines)


# ---------- Airbnb ----------

def airbnb_basis(airbnb, args):
    """Everything the Airbnb estimate needs before asking about nights.

    Returns None if there are no comparable listings.
    """
    # Nightly price: what similar listings nearby charge. Price depends on the
    # property, so every license type counts.
    comps, radius = find_comps(airbnb, args.lat, args.lon, args.bedrooms)
    if comps.empty:
        return None

    # Nights booked: depends on the setup, because DC's rules differ.
    if args.setup == "part":
        hosted, hosted_radius = find_comps(airbnb[airbnb["license_type"] == "hosted"],
                                           args.lat, args.lon, args.bedrooms)
        cap = None
        levels = booking_levels(hosted["nights_booked"])
        source = f"{len(hosted)} hosted listings within {hosted_radius} mi"
    else:
        unhosted = airbnb[airbnb["license_type"] == "unhosted"]  # too few to use only nearby ones
        cap = VACATION_RENTAL_CAP
        levels = booking_levels(unhosted["nights_booked"], cap=cap)
        source = f"all {len(unhosted)} unhosted listings in DC"

    return {
        "comps": comps, "radius": radius, "cap": cap, "source": source,
        "price": comps["nightly_price"].median(),
        "price_range": median_range(comps["nightly_price"]),
        "low": levels[0], "typical": levels[1], "strong": levels[2],
    }


def estimate_airbnb(b, args, nights, a):
    """Print the Airbnb estimate and costs. Returns net monthly income at the chosen nights."""
    print("AIRBNB")
    if b is None:
        print("  No comparable Airbnbs found.\n")
        return None
    price = b["price"]
    low, high = b["price_range"]
    print(f"  Nightly price: {money(price)}   (80% sure the typical comp is {money(low)}-{money(high)})")
    print(f"  Based on {len(b['comps'])} {size_label(args.bedrooms)} Airbnbs within {b['radius']} mi.")
    print(f"  Nights booked per year, from {b['source']}.")
    print("  Closest comps:")
    print_comps(b["comps"], [("nightly_price", lambda v: f"{money(v)}/night"),
                             ("nights_booked", lambda v: f"{v:.0f} nights")])
    print()

    rows = [("Low bookings", b["low"]), ("Typical bookings", b["typical"]), ("Strong bookings", b["strong"])]
    if b["cap"]:
        rows.append(("Maximum allowed", b["cap"]))
    if nights is not None:
        rows.append(("Your estimate", nights))
    # The row the recommendation uses: the user's estimate, or else the typical (median).
    chosen_row = "Your estimate" if nights is not None else "Typical bookings"
    chosen = nights if nights is not None else b["typical"]

    def lines_at(n):
        return airbnb_lines(price, n, args.bedrooms, args.setup, a)

    print(f"  Monthly income, averaged over the year:  {'gross':>8} {'net':>9}")
    for name, n in rows:
        marker = "  <- used below" if name == chosen_row else ""
        gross = lines_at(n)[0][1]  # nightly bookings only
        print(f"    {name:<18} {n:>4.0f} nights/year  {money(gross):>8} {money(net(lines_at(n))):>9}{marker}")
    print()
    print_lines(f"After costs, at {chosen:.0f} nights/year:", lines_at(chosen))
    print()
    return net(lines_at(chosen))


# ---------- Recommendation ----------

def recommend(rent_net, airbnb_net, b, nights, args, a):
    print("RECOMMENDATION (after costs)")
    if rent_net is None or airbnb_net is None:
        print("  Not enough comparable listings to compare.")
        return

    basis = "your estimate of nights" if nights is not None else "typical bookings"
    winner = "Airbnb" if airbnb_net > rent_net else "Long-term renting"
    print(f"  With {basis}: {winner} earns more "
          f"(Airbnb {money(airbnb_net)} vs. rent {money(rent_net)} per month, after costs).")

    # Break-even: how many nights Airbnb needs to match renting, after costs.
    break_even = airbnb_break_even_nights(b["price"], args.bedrooms, args.setup, a, rent_net)
    if b["cap"] and break_even > b["cap"]:
        print(f"  Even at DC's {b['cap']}-night maximum, renting earns more. "
              f"Airbnb would need about {break_even:.0f} nights.")
    elif break_even > 365:
        print("  Airbnb can't match renting here, even booked every night.")
    else:
        print(f"  Airbnb earns more than renting if booked more than about {break_even:.0f} nights a year.")

    print("  Not counted: your own time hosting, and income tax (which applies to both).")
    if args.setup == "whole":
        print("  Keep in mind: renting long-term means moving out. A vacation rental earns money")
        print(f"  only while you're away, up to {VACATION_RENTAL_CAP} nights a year.")
    print("  Costs are assumptions: see them with --assumptions, change one with --set KEY=VALUE.")
    print("  DC allows short-term rentals only in your primary residence, with a license.")
    print("  Rules change, so check with DC's Department of Licensing and Consumer Protection.")


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
    parser.add_argument("--lat", type=float, help="latitude, e.g. 38.8899")
    parser.add_argument("--lon", type=float, help="longitude, e.g. -76.9905")
    parser.add_argument("--bedrooms", type=int, help="bedrooms in the space you'd rent out (0 for a studio)")
    parser.add_argument("--bathrooms", type=float, help="e.g. 1.5")
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
    b = airbnb_basis(pd.read_csv(AIRBNB_CLEAN), args)
    nights = ask_nights(args.setup, b["typical"], b["cap"]) if b else None

    print(f"\nProperty: {args.bedrooms} bd / {args.bathrooms:g} ba {args.type} at ({args.lat}, {args.lon})")
    print(f"Renting out: {SETUPS[args.setup]}\n")
    _, rent_net = estimate_rent(pd.read_csv(RENTALS_CLEAN), args, a)
    airbnb_net = estimate_airbnb(b, args, nights, a)
    recommend(rent_net, airbnb_net, b, nights, args, a)


if __name__ == "__main__":
    main()
