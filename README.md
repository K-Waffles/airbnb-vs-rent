# Airbnb vs. long-term rent in DC

Should you list a Washington, DC property on Airbnb or rent it out long-term? This app estimates the monthly income of each option after costs, shows the comparable listings behind the estimate, and highlights which one comes out ahead.

It's a learning project: built step by step to learn how to build a simple data app with AI tools.

## How it works

You answer five questions: the address, whether you're renting part of the home you live in or the whole property, the property type, the number of bedrooms, and (optionally) how many nights a year you expect guests to book.

- **Long-term rent:** the median rent of nearby rentals with the same number of bedrooms, found in the smallest circle around the address (0.5 to 3 miles) that has at least 10 of them.
- **Airbnb:** nightly price × nights booked. The nightly price comes from nearby Airbnbs with the same bedrooms. Nights booked come from your answer, or else the typical (median) nights for similar listings.
- **DC's rules:** DC only allows short-term rentals of your primary residence. Renting part of the home you live in has no night cap; renting the whole property while you're away is capped at 90 nights a year. The app follows both rules.
- **Costs:** Airbnb host fee, cleaning, supplies, utilities, furnishing, license, insurance, and vacancy for rentals. Every cost is an assumption listed in [assumptions.py](assumptions.py) with its source.

### How accurate is it?

Tested by hiding listings and predicting them from the rest ([evaluate.py](evaluate.py)):

| Estimate | Typical miss |
|---|---|
| Long-term rent | about 14% (~$350/month) |
| Airbnb nightly price | about 18% |
| Airbnb monthly income, if your nights estimate is right | about 18% |

Airbnb income without a nights estimate is much less certain (about 37%), because similar listings nearby are often booked very different numbers of nights.

## Setup

You need Python 3.11 or newer.

```bash
git clone https://github.com/K-Waffles/airbnb-vs-rent.git
cd airbnb-vs-rent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Get the data

The data isn't included in this repository, so you'll need to download it:

1. **Airbnb listings:** download the Washington, DC `listings.csv.gz` from [Inside Airbnb](https://insideairbnb.com/get-the-data/) and save it as `data/listings.csv` (or pass its path to `clean_data.py`).
2. **Rental listings:** get a free API key from [RentCast](https://www.rentcast.io/api), create a file named `.env` containing `RENTCAST_API_KEY=your-key`, then run:
   ```bash
   .venv/bin/python fetch_rentals.py
   ```
   It asks before each API call; all of DC takes about 6 calls.
3. **Clean both datasets:**
   ```bash
   .venv/bin/python clean_data.py
   ```

## Run it

Web page:

```bash
.venv/bin/streamlit run app.py
```

Or in the terminal:

```bash
.venv/bin/python estimate.py
.venv/bin/python estimate.py --assumptions   # list the cost assumptions
```

## Files

| File | What it does |
|---|---|
| `app.py` | The web page (Streamlit) |
| `estimate.py` | The same app in the terminal |
| `analysis.py` | All the calculations, shared by both |
| `models.py` | Comparable-listing search and the regression cross-check |
| `costs.py`, `assumptions.py` | Costs and their assumptions |
| `geocode.py` | Address lookup and suggestions |
| `clean_data.py`, `fetch_rentals.py` | Getting and cleaning the data |
| `evaluate.py` | The accuracy test |

## Data and credits

- Airbnb listings: [Inside Airbnb](https://insideairbnb.com/), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Rental listings: [RentCast](https://www.rentcast.io/).
- Address suggestions: [Photon](https://photon.komoot.io/), © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.
- Address lookup: [U.S. Census Bureau Geocoder](https://geocoding.geo.census.gov/geocoder/).

Estimates are for learning and exploration, not financial or legal advice. Check DC's current short-term rental rules with the [Department of Licensing and Consumer Protection](https://dlcp.dc.gov/page/operating-short-term-rental-district-columbia).
