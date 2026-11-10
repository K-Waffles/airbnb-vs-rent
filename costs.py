"""Turn gross income into net income, using the settings in assumptions.py.

Each function returns a list of (label, dollars per month) lines: income is
positive, costs are negative, and the lines add up to net income.
"""


def cleaning_cost_per_stay(bedrooms, a):
    if bedrooms <= 1:
        return a["cleaning_cost_studio_1bd"]
    if bedrooms == 2:
        return a["cleaning_cost_2bd"]
    if bedrooms == 3:
        return a["cleaning_cost_3bd"]
    return a["cleaning_cost_4bd_plus"]


def furnishing_cost(bedrooms, setup, a):
    """One-time furnishing cost for the guest space."""
    if setup == "whole":
        return a["furnishing_whole_home"]  # you live there, so it's already furnished
    return a["furnishing_per_bedroom"] * max(bedrooms, 1) + a["furnishing_common_areas"]


def airbnb_lines(nightly_price, nights, bedrooms, setup, a):
    """Monthly income and costs for an Airbnb booked `nights` nights a year."""
    stays = nights / a["average_stay_nights"]
    cleaning = cleaning_cost_per_stay(bedrooms, a)
    managed = a["use_property_manager"] == 1

    bookings = nightly_price * nights
    cleaning_fees = stays * cleaning * a["cleaning_fee_covers_percent"] / 100
    gross = bookings + cleaning_fees  # Airbnb's and a manager's cut apply to both

    yearly = [
        ("Nightly bookings", bookings),
        ("Cleaning fees paid by guests", cleaning_fees),
        ("Airbnb host fee", -gross * a["airbnb_fee_percent"] / 100),
        ("Property manager", -gross * a["airbnb_manager_percent"] / 100 if managed else 0),
        ("Cleaning", -stays * cleaning),
        ("Supplies", -stays * a["supplies_per_stay"]),
        ("Utilities + internet", -a["utilities_part_of_home"] * 12 if setup == "part" else 0),
        ("Furnishing (spread over years)", -furnishing_cost(bedrooms, setup, a) / a["furnishing_years"]),
        ("License", -a["license_per_year"]),
        ("Extra insurance", -a["extra_insurance_per_year"]),
    ]
    return [(label, amount / 12) for label, amount in yearly]


def rental_lines(rent, a):
    """Monthly income and costs for a long-term rental at `rent` per month."""
    managed = a["use_property_manager"] == 1
    vacancy = rent * a["vacancy_percent"] / 100
    collected = rent - vacancy
    return [
        ("Rent", rent),
        ("Vacancy between tenants", -vacancy),
        ("Property manager", -collected * a["rental_manager_percent"] / 100 if managed else 0),
        ("Tenant placement fee", -rent * a["leasing_fee_months"] / (a["tenancy_years"] * 12) if managed else 0),
    ]


def net(lines):
    return sum(amount for _, amount in lines)


def airbnb_break_even_nights(nightly_price, bedrooms, setup, a, target_monthly):
    """Nights per year at which Airbnb's net income matches `target_monthly`.

    Net income grows in a straight line with nights booked, so two points
    (0 nights and 1 night) are enough to solve for it.
    """
    at_zero = net(airbnb_lines(nightly_price, 0, bedrooms, setup, a))
    per_night = net(airbnb_lines(nightly_price, 1, bedrooms, setup, a)) - at_zero
    if per_night <= 0:
        return float("inf")  # costs per stay exceed what a night earns
    return (target_monthly - at_zero) / per_night
