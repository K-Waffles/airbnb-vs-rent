"""Cost assumptions: every number the app assumes rather than gets from data.

All of them live here so they're easy to find and change. Each setting has a
label, unit and source, so a future "advanced settings" screen can list them
and let the user adjust them. Until then:
    .venv/bin/python estimate.py --assumptions                  # list them all
    .venv/bin/python estimate.py --set airbnb_fee_percent=3     # change one for a run

Only costs that DIFFER between Airbnb and long-term renting are included.
Mortgage, property tax, HOA and basic home insurance are the same either way,
so they don't change which option earns more.

Values were researched in November 2026; check the sources for updates.
"""
from dataclasses import dataclass


@dataclass
class Setting:
    key: str
    label: str
    value: float
    unit: str
    group: str    # "Airbnb", "Long-term rental" or "Both"
    source: str


SETTINGS = [
    # ---------- Airbnb ----------
    Setting("airbnb_fee_percent", "Airbnb host service fee", 15.5, "% of booking", "Airbnb",
            "Airbnb's host-only fee, now standard for most hosts (2025-2026). Some hosts on the "
            "older split fee pay 3%. hostfully.com, pricelabs.co"),
    Setting("average_stay_nights", "Average guest stay", 5, "nights", "Airbnb",
            "DC estimates range from 5 (cozycozy.com) to 6.3 nights (airroi.com). Used to turn "
            "per-stay costs into per-night costs."),
    Setting("cleaning_cost_studio_1bd", "Cleaning per stay: studio / 1 bedroom", 110, "$ per stay", "Airbnb",
            "National $80-110 (cleanestimator.com); DC runs higher. Educated default."),
    Setting("cleaning_cost_2bd", "Cleaning per stay: 2 bedrooms", 140, "$ per stay", "Airbnb",
            "DC benchmark $137 (airroi.com); national $105-145 (cleanestimator.com)"),
    Setting("cleaning_cost_3bd", "Cleaning per stay: 3 bedrooms", 185, "$ per stay", "Airbnb",
            "DC benchmark $183 (airroi.com)"),
    Setting("cleaning_cost_4bd_plus", "Cleaning per stay: 4+ bedrooms", 230, "$ per stay", "Airbnb",
            "DC benchmark $231 (airroi.com)"),
    Setting("cleaning_fee_covers_percent", "Share of cleaning cost charged to guests as a cleaning fee",
            100, "%", "Airbnb",
            "Most hosts charge a cleaning fee about equal to their cost. Set to 0 if you won't "
            "charge one. Airbnb's fee applies to it too."),
    Setting("supplies_per_stay", "Supplies per stay (toiletries, coffee, restocking)", 15, "$ per stay", "Airbnb",
            "Restocking adds $12-18 per turnover (cleanestimator.com)"),
    Setting("utilities_part_of_home", "Utilities + internet for the guest space (part of home)", 300,
            "$ per month", "Airbnb",
            "DC 1-bedroom: $200-250 electric/gas/water plus $65-80 internet (energysage.com, "
            "utilitycheck.co). A long-term tenant would usually pay these. For a whole home you "
            "live in, you pay them anyway, so 0 extra is assumed."),
    Setting("furnishing_per_bedroom", "Furnishing per bedroom (part of home)", 4000, "$ one-time", "Airbnb",
            "Mid-range guest-ready bedroom $2,500-6,000 (awning.com, strnumbers.com). A studio "
            "counts as one bedroom."),
    Setting("furnishing_common_areas", "Furnishing kitchen + living area (part of home)", 3000, "$ one-time",
            "Airbnb", "Educated default; 2-3 bedroom homes total $15,000-35,000 (vaultstr.com, awning.com)"),
    Setting("furnishing_whole_home", "Guest-ready extras for a whole home you live in", 1000, "$ one-time",
            "Airbnb", "Already furnished; covers linens, lockbox, safety gear. Educated default."),
    Setting("furnishing_years", "Years to spread furnishing cost over", 5, "years", "Airbnb",
            "Educated default for furniture life under guest use."),
    Setting("license_per_year", "DC short-term rental license", 50, "$ per year", "Airbnb",
            "$99 for a two-year license (dlcp.dc.gov)"),
    Setting("extra_insurance_per_year", "Extra insurance for Airbnb vs. a long-term rental", 500,
            "$ per year", "Airbnb",
            "Short-term rental policies run $1,000-3,500/yr vs. landlord policies ~$1,500-1,900/yr "
            "(airdna.co, steadily.com). Educated default for the difference."),
    Setting("airbnb_manager_percent", "Airbnb property manager fee (if used)", 20, "% of booking", "Airbnb",
            "Short-term managers charge 15-30% (maverickstr.co, baselane.com)"),

    # ---------- Long-term rental ----------
    Setting("vacancy_percent", "Vacancy between tenants", 5, "% of rent", "Long-term rental",
            "DC apartment vacancy ~5.2% (Northmarq, end of 2025); occupancy 94.7% (realpage.com, Feb 2026)"),
    Setting("rental_manager_percent", "Long-term property manager fee (if used)", 9, "% of rent",
            "Long-term rental", "DC managers charge 8-10% of rent (nomadicrealestate.com, gordonjamesrealty.com)"),
    Setting("leasing_fee_months", "Tenant placement fee (if using a manager)", 0.75, "months of rent",
            "Long-term rental", "DC: 50-100% of one month's rent (nomadicrealestate.com)"),
    Setting("tenancy_years", "Average years a tenant stays", 2, "years", "Long-term rental",
            "Educated default; spreads the placement fee across the tenancy."),

    # ---------- Both ----------
    Setting("use_property_manager", "Use a property manager? (1 = yes, 0 = no)", 0, "yes/no", "Both",
            "Off by default: assumes you manage it yourself."),
]


def defaults():
    """{key: value} for every setting."""
    return {s.key: s.value for s in SETTINGS}


def with_overrides(overrides):
    """Defaults, with some values replaced, e.g. {"airbnb_fee_percent": 3}."""
    values = defaults()
    unknown = set(overrides) - set(values)
    if unknown:
        raise ValueError(f"Unknown setting(s): {', '.join(sorted(unknown))}")
    values.update(overrides)
    return values


def print_settings(values=None):
    values = values or defaults()
    for group in ["Airbnb", "Long-term rental", "Both"]:
        print(f"\n{group.upper()}")
        for s in SETTINGS:
            if s.group == group:
                changed = "  (changed)" if values[s.key] != s.value else ""
                print(f"  {s.key} = {values[s.key]:g}  [{s.unit}]{changed}")
                print(f"      {s.label}")
                print(f"      Source: {s.source}")
