"""Web page version of the app, built with Streamlit.

Run it with:
    .venv/bin/streamlit run app.py
It opens in your browser at a local address only you can see.

How Streamlit works: every time you change an input, Streamlit re-runs this
whole script from top to bottom and redraws the page. So the code reads like
a simple script: ask, then show. All the math lives in analysis.py.
"""
import html
import re
import time

import altair as alt
import pandas as pd
import streamlit as st
from streamlit_searchbox import st_searchbox

from analysis import (LEGAL_NOTES, SETUPS, VACATION_RENTAL_CAP, Property, airbnb_basis, analyze,
                      load_data, money, size_label)
from assumptions import defaults
from geocode import GeocodeError, coordinates, geocode, in_dc, suggest_addresses
from models import MIN_COMPS, PROPERTY_TYPES_FOR_INPUT

st.set_page_config(page_title="Airbnb vs. Rent in DC", page_icon="🏠")


# ---------- Data (loaded once, then reused) ----------

@st.cache_data
def cached_data():
    return load_data()


@st.cache_data(show_spinner="Looking up the address...")
def cached_geocode(address):
    return geocode(address)  # cached so the same address isn't sent twice


@st.cache_data(ttl="1d", show_spinner=False)
def cached_suggestions(text):
    return suggest_addresses(text)


def address_suggestions(text):
    """The dropdown under the address box: [(text shown, value returned when picked)]."""
    text = text.strip()
    if not text:
        return []
    st.session_state["address_error"] = False  # typing again clears the red "not found" box
    return [(s["label"], s) for s in cached_suggestions(text)]


# ---------- Helpers for showing results ----------

def lines_table(lines):
    """Income and cost lines (skipping zeros), plus net income, as a table."""
    rows = [(label, amount) for label, amount in lines if round(amount)]
    rows.append(("Net income", sum(amount for _, amount in lines)))
    return pd.DataFrame(
        {"": [label for label, _ in rows],
         "Per month": [("-" if amount < 0 else "") + money(abs(amount)) for _, amount in rows]})


def comps_table(comps, columns):
    table = comps.head(10).copy()
    table["Distance"] = table["miles"].map(lambda m: f"{m:.2f} mi")
    table["Size"] = table.apply(lambda c: f"{c['bedrooms']:.0f} bd / {c['bathrooms']:g} ba", axis=1)
    table["Type"] = table["property_type"]
    for column, (title, fmt) in columns.items():
        table[title] = table[column].map(fmt)
    return table[["Distance", "Size", "Type"] + [title for title, _ in columns.values()]]


def result_card(column, label, value, favorable):
    """A headline number. The more favorable option gets a green box and a note above the number."""
    note = "More favorable" if favorable else "&nbsp;"  # blank line keeps both cards the same height
    style = ("background: rgba(26, 127, 55, 0.15); border: 2px solid #1a7f37;" if favorable
             else "border: 2px solid transparent;")
    column.markdown(
        f"""<div style="{style} display: inline-block; border-radius: 0.6rem; padding: 0.8rem 1.2rem;">
              <div style="color: #1a7f37; font-weight: 600; font-size: 0.9rem;">{note}</div>
              <div style="font-size: 0.9rem; opacity: 0.8;">{label}</div>
              <div style="font-size: 2.2rem; line-height: 1.3;">{value}</div>
            </div>""",
        unsafe_allow_html=True,
    )


def pretty_address(place):
    """Split an address into its street line and the rest, and undo the Census's ALL CAPS:
    '1401 PENNSYLVANIA AVE SE, WASHINGTON, DC, 20003' -> ('1401 Pennsylvania Ave SE', 'Washington, DC 20003').
    """
    if place.startswith("("):  # typed coordinates, e.g. "(38.88, -76.98)"
        return place, ""
    street, _, rest = place.partition(",")
    rest = re.sub(r",\s*(\d{5})$", r" \1", rest.strip())  # "DC, 20003" -> "DC 20003"
    if place.isupper():
        keep_caps = {"NW", "NE", "SE", "SW", "DC"}
        fix = lambda text: " ".join(w if w in keep_caps else w.capitalize() for w in text.split(" "))
        street, rest = fix(street), fix(rest)
    return street.strip(), rest


def answers_summary(prop, nights):
    """The answers at the top of the results: the address in one box, the rest in a 2x2 grid."""
    street, rest = pretty_address(prop.place)
    size = "Studio" if prop.bedrooms == 0 else f"{prop.bedrooms} bedroom{'s' if prop.bedrooms > 1 else ''}"
    grid = [("Setup", SETUP_CHOICES[prop.setup].split(" (")[0]),
            ("Property type", prop.type),
            ("Size", size),
            ("Bookings", f"{nights} nights a year" if nights else "Typical for similar listings")]
    box = lambda label, value: (f'<div class="answer-box"><div class="answer-label">{label}</div>'
                                f'<div class="answer-value">{html.escape(value)}</div></div>')
    address = (f'<div class="answer-box"><div class="answer-label">Address</div>'
               f'<div class="answer-value answer-address">{html.escape(street)}</div>'
               f'<div class="answer-sub">{html.escape(rest)}</div></div>')
    st.markdown(f'<div class="answers">{address}<div class="answers-grid">'
                + "".join(box(label, value) for label, value in grid) + "</div></div>",
                unsafe_allow_html=True)


def stat_boxes(boxes, widths=None):
    """Boxes side by side, each with a small label, a big value, and a line of detail under it.

    Each box is (label, value, detail); a detail wrapped in *stars* is shown in italics.
    `widths` sets each box's share of the row, e.g. [1, 1.6, 1]; equal if left out.
    """
    widths = widths or [1] * len(boxes)
    columns = " ".join(f"{w}fr" for w in widths)
    def detail_html(detail):
        if detail.startswith("*") and detail.endswith("*"):
            return f"<em>{html.escape(detail[1:-1])}</em>"
        return html.escape(detail)

    st.markdown(f'<div class="stat-grid" style="--columns: {columns}">' + "".join(
        f'<div class="answer-box"><div class="answer-label">{html.escape(label)}</div>'
        f'<div class="stat-value">{html.escape(value)}</div>'
        f'<div class="answer-sub">{detail_html(detail)}</div></div>'
        for label, value, detail in boxes) + "</div>", unsafe_allow_html=True)


def bookings_chart(rows, rent_net):
    """Horizontal bars: Airbnb income after costs at each booking level, with long-term rent as a line.

    The level used in the estimate is dark brown; the others are a lighter tan (still 3:1
    against the page so they stay visible). Hover a bar for its nights and gross income.
    """
    ink, muted, grid = "#3a2c26", "#a38b75", "#e3d7ca"
    data = pd.DataFrame([{
        # Short names, e.g. "Low (42)", "Max (90)"
        "label": f"{row['level'].replace(' bookings', '').replace('Maximum allowed', 'Max')} ({row['nights']:.0f})",
        "nights": row["nights"],
        "net": row["net"],
        "Net / month": ("−" if row["net"] < 0 else "") + money(abs(row["net"])),
        "Gross / month": money(row["gross"]),
        "Nights / year": f"{row['nights']:.0f}",
        "chosen": row["chosen"],
        "color": ink if row["chosen"] else muted,
    } for row in sorted(rows, key=lambda r: r["nights"])])
    chosen = data.loc[data["chosen"], "label"].iloc[0]

    # "Nights booked" sits above the labels, lined up with their right edge.
    y = alt.Y("label:N", sort=list(data["label"]), title="Nights booked",
              axis=alt.Axis(ticks=False, domain=False, labelPadding=10, labelFontSize=13, labelColor=ink,
                            titleAngle=0, titleAlign="right", titleBaseline="bottom", titleX=-10,
                            titleY=-6, titleFontSize=12, titleFontWeight=600, titleColor=ink,
                            labelFontWeight=alt.condition(f"datum.value == '{chosen}'",
                                                          alt.value(700), alt.value(400))))
    x = alt.X("net:Q", title=None,
              axis=alt.Axis(format="$,.0f", tickCount=5, grid=True, gridColor=grid, gridWidth=1,
                            domain=False, ticks=False, labelColor=ink, labelOpacity=0.7))
    tooltip = ["label:N", "Nights / year:N", "Gross / month:N", "Net / month:N"]
    bars = alt.Chart(data).mark_bar(size=24, cornerRadiusEnd=4).encode(
        y=y, x=x, color=alt.Color("color:N", scale=None), tooltip=tooltip)
    # Dollar amount just past each bar's end. A loss's bar points left, toward the
    # labels, so its amount goes just right of $0 instead.
    values = alt.Chart(data).transform_calculate(at="max(datum.net, 0)").mark_text(
        align="left", dx=6, fontSize=13, color=ink).encode(
        y=y, x="at:Q", text="Net / month:N", tooltip=tooltip)
    rent = pd.DataFrame({"net": [rent_net], "text": [f"Long-term rent {money(rent_net)}"]})
    rent_line = alt.Chart(rent).mark_rule(color=ink, strokeWidth=2, strokeDash=[5, 4]).encode(x="net:Q")
    rent_label = alt.Chart(rent).mark_text(align="center", baseline="bottom", dy=-4, fontSize=12,
                                           color=ink).encode(x="net:Q", y=alt.value(0), text="text:N")
    return ((bars + values + rent_line + rent_label)
            .properties(height=48 * len(data), padding={"top": 22, "right": 50, "left": 5, "bottom": 5})
            .configure(font="Inter", background="transparent", view={"stroke": None}))


# ---------- One question at a time ----------
# The page remembers which question you're on ("step") and the answers so far
# in st.session_state, which survives each re-run. Only the current question
# is drawn. Buttons change the step through small "callback" functions that
# run before the page is redrawn.
#
# Transitions: each step is drawn inside a container named after it. CSS fades
# a newly drawn container in. To fade the old question out, the page first
# redraws it in a "leaving" container that fades out, waits a moment, then
# draws the next step.

STEPS = ["welcome", "address", "setup", "type", "bedrooms", "nights", "results"]
QUESTION_COUNT = 5  # address through nights; the welcome screen and results aren't questions
SETUP_CHOICES = {
    "part": "Part of the home you live in (e.g. an English basement, a detached home)",
    "whole": "The whole property",
}
FADE_SECONDS = 0.25
HOLD_SECONDS = 1.0  # how long a picked address stays on screen before fading out

st.markdown("""<style>
@keyframes fade-in  { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
@keyframes fade-out { from { opacity: 1; } to { opacity: 0; transform: translateY(-10px); } }
[class*="st-key-step_"]    { animation: fade-in 0.35s ease-out; }
[class*="st-key-leaving_"] { animation: fade-out 0.25s ease-in forwards; }
/* Hide Streamlit's top bar, and tighten the space it leaves. */
header[data-testid="stHeader"] { display: none; }
[data-testid="stMainBlockContainer"] { padding-top: 2.5rem; }
/* Progress bar pinned to the bottom of the window. */
.st-key-progress_bar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 100;
                       padding: 0 1.5rem 1rem 1.5rem; }
/* Back button pinned to the bottom-left, just above the progress bar. */
.st-key-back_nav { position: fixed; left: 1.5rem; bottom: 2.25rem; z-index: 100; width: auto; }
/* Center each question in the window: vertically (fill the window's height and
   center inside it) and its headings and text horizontally. */
[class*="st-key-step_"]:not(.st-key-step_results), [class*="st-key-leaving_"], .st-key-holding_address {
    min-height: calc(100vh - 9rem); justify-content: center; }
[class*="st-key-step_"]:not(.st-key-step_results) :is(h1, h2, h3, p),
[class*="st-key-leaving_"] :is(h1, h2, h3, p), .st-key-holding_address :is(h1, h2, h3, p) {
    text-align: center; }
/* Bigger, easier-to-tap buttons on the question cards. */
[class*="st-key-step_"]:not(.st-key-step_results) button,
[class*="st-key-leaving_"] button { min-height: 3rem; }
/* The answers at the top of the results: the address box, then a 2x2 grid of boxes. */
.answers { display: flex; flex-direction: column; gap: 0.6rem; margin-bottom: 0.4rem; }
.answers-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; }
.answer-box { background: #f3ebe2; border: 1px solid #e3d7ca; border-radius: 0.6rem; padding: 0.7rem 1rem; }
.answer-label { font-size: 0.75rem; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase;
                opacity: 0.65; }
.answer-value { font-weight: 500; line-height: 1.35; }
.answer-address { font-size: 1.25rem; font-weight: 600; }
.answer-sub { font-size: 0.9rem; opacity: 0.75; }
.stat-value { font-size: 1.6rem; font-weight: 600; line-height: 1.3; }
/* Number boxes in the results, side by side (column widths set per row); stacked on phones. */
.stat-grid { display: grid; grid-template-columns: var(--columns); gap: 0.6rem; }
@media (max-width: 640px) { .stat-grid { grid-template-columns: 1fr; } }
</style>""", unsafe_allow_html=True)

state = st.session_state
state.setdefault("step", "welcome")
state.setdefault("answers", {})
answers = state["answers"]


def move_to(next_step):
    """Go to another step, fading out the current question (if it's one of the button questions)."""
    if state["step"] in ("welcome", "setup", "type", "bedrooms", "nights"):
        state["leaving"] = state["step"]
    state["step"] = next_step


def answer(name, value, next_step):
    answers[name] = value
    move_to(next_step)


def back():
    move_to(STEPS[STEPS.index(state["step"]) - 1])
    if state["step"] == "address":
        state.pop("address", None)  # start the address box fresh


def start_over():
    state["step"] = "welcome"
    state["answers"] = {}
    state.pop("address", None)


def save_nights():
    answers["nights"] = state.get("nights_box")  # None (blank) means "use the typical"
    move_to("results")


def question_header(step, question):
    st.subheader(question)


def show_back(step):
    """The Back button, pinned to the bottom-left of the window above the progress bar."""
    if step not in ("welcome", "address"):  # Back first appears once the address is answered
        with st.container(key="back_nav"):  # pinned by the .st-key-back_nav CSS rule
            back_button("back_nav_button")


def show_progress(step):
    """A bar pinned to the bottom of the window showing how far through the questions you are."""
    if step == "welcome":
        return  # the welcome screen isn't a question
    with st.container(key="progress_bar"):  # pinned by the .st-key-progress_bar CSS rule
        st.progress(STEPS.index(step) / QUESTION_COUNT)  # address = 1 of 5, ...


def answer_buttons(name, choices, next_step, columns=1, icons=None):
    """One button per choice; clicking saves the answer and moves on.

    choices: {value: label}. icons: optional {value: ":material/icon_name:"}
    (icon names from https://fonts.google.com/icons).
    """
    icons = icons or {}
    cols = st.columns(columns)
    for i, (value, label) in enumerate(choices.items()):
        cols[i % columns].button(label, on_click=answer, args=(name, value, next_step), icon=icons.get(value),
                                 width="stretch", key=f"{name}_{value}")


def back_button(key, **kwargs):
    st.button("Back", on_click=back, icon=":material/arrow_back:", key=key, **kwargs)


def current_property():
    return Property(lat=answers["lat"], lon=answers["lon"], setup=answers["setup"],
                    bedrooms=answers["bedrooms"], type=answers["type"], place=answers["place"])


# ---------- The questions ----------

def show_address():
    question_header("address", "Where is the property?")
    # A dropdown of suggestions appears as you type. Picking one returns its
    # details (a dict). Nothing is looked up until something is picked.
    not_found = state.get("address_error", False)
    # While the suggestions are open, the box and the list share one outline:
    # the box's bottom corners and the list's top corners are squared off, the
    # list is pulled up to touch the box, and both use the same neutral border
    # (so it works in light and dark mode).
    outline = "1px solid rgba(128, 128, 128, 0.5)"
    open_menu = "&:has(input[aria-expanded='true'])"  # the box, while its list is showing
    control = {open_menu: {"border": outline, "borderBottomLeftRadius": 0, "borderBottomRightRadius": 0}}
    searchbox_style = {
        "optionEmpty": "hidden",
        "menuList": {"border": outline, "borderTop": "none",
                     # Match the dropdown's built-in 4px corners so its light background
                     # doesn't show at the bottom corners.
                     "borderRadius": "0 0 4px 4px",
                     "marginTop": "-9px",  # cancels the built-in gap above the list
                     "boxShadow": "0 8px 16px rgba(58, 44, 38, 0.15)", "padding": "0.2rem 0",
                     "overflow": "hidden"},
        "control": control,
    }
    red = "2px solid #ff4b4b"
    if not_found:  # last address wasn't found: red border, red message inside the box
        control.update({"border": red, "&:hover": {"border": red}})
        searchbox_style["placeholder"] = {"color": "#ff4b4b"}
    choice = st_searchbox(
        address_suggestions,
        placeholder="Address not found" if not_found else "Property address",
        debounce=150,          # wait for a short pause in typing before looking up suggestions
        style_absolute=True,   # float the dropdown over the page instead of pushing it down
        style_overrides={"clear": {"clearable": "always"},
                         "dropdown": {"display": "none"},  # hide the arrow on the right
                         "searchbox": searchbox_style},
        key="address",
    )
    if not choice:
        return
    suggested = choice if isinstance(choice, dict) else None
    address = suggested["label"] if suggested else choice
    coords = coordinates(address)
    found = None
    if coords:
        if in_dc(coords):
            found = {"lat": coords[0], "lon": coords[1], "place": f"({coords[0]}, {coords[1]})"}
    else:
        try:
            census = cached_geocode(address)
        except GeocodeError as e:
            st.error(f"{e} You can enter latitude, longitude instead.")
            return
        if census:
            found = {"lat": census["lat"], "lon": census["lon"],
                     "place": census["address"], "tract": census["tract"]}  # tract kept for later use
        elif suggested:
            # The Census doesn't know this suggestion; use the suggestion's own location.
            found = {"lat": suggested["lat"], "lon": suggested["lon"], "place": suggested["label"]}
    if not found:
        # Not a DC address: clear the box and show it red with "Address not found".
        state["address_error"] = True
        state.pop("address", None)
        st.rerun()
    if found:
        state["address_error"] = False
        answers.update(found)
        state["holding"] = "address"  # show the picked address for a moment, then fade
        state["step"] = "setup"
        state.pop("address", None)  # so the box starts fresh if you come back
        st.rerun()


def show_address_answered():
    """A stand-in for the address question while it fades out.

    The real address box clears itself once an address is picked, so this
    shows the same question with the picked address in a plain box instead.
    """
    question_header("address", "Where is the property?")
    # Drawn as a plain box (not a real input) so it can be styled green.
    st.markdown(
        f"""<div style="border: 2px solid #1a7f37; background: rgba(26, 127, 55, 0.12);
                        border-radius: 0.5rem; padding: 0.55rem 0.75rem; margin-bottom: 1rem;">
              {answers["place"]}
            </div>""",
        unsafe_allow_html=True,
    )


def show_setup():
    question_header("setup", "What are you renting out?")
    answer_buttons("setup", SETUP_CHOICES, "type",
                   icons={"part": ":material/door_front:", "whole": ":material/home:"})


def show_type():
    question_header("type", "What type of property is it?")
    answer_buttons("type", {t: t for t in PROPERTY_TYPES_FOR_INPUT}, "bedrooms", columns=2,
                   icons={"Apartment": ":material/apartment:", "Condo": ":material/domain:",
                          "Townhouse": ":material/holiday_village:", "Single Family": ":material/house:"})


def show_bedrooms():
    question_header("bedrooms", "How many bedrooms are in the space available to guests?")
    answer_buttons("bedrooms", {n: "Studio" if n == 0 else str(n) for n in range(7)}, "nights", columns=7)


def show_nights():
    question_header("nights", "How many nights a year do you expect guests to book?")
    prop = current_property()
    basis = airbnb_basis(airbnb, prop)
    if basis:
        if prop.setup == "part":
            st.write("Since you'd live on-site, DC doesn't cap how many nights you can host. "
                     f"Similar hosted listings nearby are booked about **{basis['typical']:.0f} nights** a year.")
        else:
            st.write(f"DC caps whole-home vacation rentals at **{VACATION_RENTAL_CAP} nights** a year. "
                     f"Most book fewer: a typical one in DC is booked about **{basis['typical']:.0f} nights** a year.")
        st.number_input("Nights per year (optional)", min_value=1, max_value=basis["cap"] or 365,
                        value=answers.get("nights"), step=1, key="nights_box",
                        placeholder=f"Leave blank to use {basis['typical']:.0f}")
    st.button("See results", on_click=save_nights, type="primary", icon=":material/insights:",
              width="stretch")


def show_welcome():
    st.title("Airbnb vs. long-term rent in DC")
    st.write("Estimate what a property in Washington, DC would earn each month as an Airbnb "
             "vs. a regular rental, after costs.")
    with st.container(horizontal_alignment="right"):  # button on the right, under the text
        st.button("Let's go!", on_click=move_to, args=("address",), type="primary",
                  icon=":material/arrow_forward:")


QUESTIONS = {"welcome": show_welcome, "address": show_address, "setup": show_setup, "type": show_type,
             "bedrooms": show_bedrooms, "nights": show_nights}

airbnb, rentals = cached_data()

# After an address is picked: keep it on screen for a moment before fading out.
if state.pop("holding", None):
    with st.container(key="holding_address"):
        show_address_answered()
    show_progress("address")
    time.sleep(HOLD_SECONDS)
    state["leaving"] = "address"
    st.rerun()

# Fade out the question just answered, then start over with the next one.
leaving = state.pop("leaving", None)
if leaving:
    with st.container(key=f"leaving_{leaving}"):
        (show_address_answered if leaving == "address" else QUESTIONS[leaving])()
    show_back(leaving)
    show_progress(leaving)
    time.sleep(FADE_SECONDS)
    st.rerun()

step = state["step"]
if step in QUESTIONS:
    with st.container(key=f"step_{step}"):
        QUESTIONS[step]()
    show_back(step)
    show_progress(step)
    st.stop()  # only the results step continues past here


# ---------- The results ----------
# Rebuilt from the saved answers, inside a container so it fades in like the questions.

with st.container(key="step_results"):
    prop = current_property()
    lat, lon = prop.lat, prop.lon
    basis = airbnb_basis(airbnb, prop)
    nights = answers.get("nights")

    answers_summary(prop, nights)
    left, right = st.columns(2)
    with left:
        back_button("back_results", width="stretch")
    right.button("Start over", on_click=start_over, icon=":material/restart_alt:", width="stretch")


    a = defaults()
    result = analyze(prop, nights, a, airbnb, rentals, basis)
    rent, ab, rec = result["rent"], result["airbnb"], result["recommendation"]

    st.divider()
    st.header("Results")

    if rec["winner"] is None:
        st.warning(rec["headline"])
        st.stop()

    # Headline numbers
    left, right = st.columns(2)
    result_card(left, "Airbnb, after costs", f"{money(ab['net'])}/mo", ab["net"] > rent["net"])
    result_card(right, "Long-term rent, after costs", f"{money(rent['net'])}/mo", rent["net"] > ab["net"])

    # Airbnb details
    st.subheader("Airbnb")
    low, high = basis["price_spread"]
    beds = "Studios" if prop.bedrooms == 0 else f"{prop.bedrooms} bed{'s' if prop.bedrooms > 1 else ''}"
    stat_boxes([("Nightly price", money(basis["price"]), "median"),
                ("Similar properties are between", f"{money(low)}–{money(high)}", "*80% range*"),
                (f"{len(basis['comps'])} similar Airbnbs", beds, f"within {basis['radius']} miles")],
               widths=[1, 1.6, 1])  # the middle box holds the longest label and value
    st.altair_chart(bookings_chart(ab["rows"], rent["net"]), width="stretch")
    with st.expander(f"Costs at {ab['chosen_nights']:.0f} nights a year"):
        st.dataframe(lines_table(ab["lines"]), hide_index=True, width="stretch")

    # Rental details
    st.subheader("Long-term rental")
    low, high = rent["typical_range"]
    st.write(f"Typical rent: **{money(rent['estimate'])}/month** (80% sure the typical comp is "
             f"{money(low)}-{money(high)}), from {len(rent['comps'])} {size_label(prop.bedrooms)} "
             f"rentals within {rent['radius']} mi.")
    st.write(f"Individual rentals vary more: the middle half rent for "
             f"{money(rent['middle_half'][0])}-{money(rent['middle_half'][1])}.")
    check_note = "agrees" if rent["check_agrees"] else "disagrees, so treat this estimate with caution"
    st.caption(f"Cross-check (regression using property type too): {money(rent['check'])} "
               f"({rent['check_gap']:+.0f}%, {check_note})")
    if rent["few_comps"]:
        st.warning(f"Fewer than {MIN_COMPS} comparable rentals, so this estimate is shaky.")
    with st.expander("Costs"):
        st.dataframe(lines_table(rent["lines"]), hide_index=True, width="stretch")

    # Comparable listings: map and tables
    st.subheader("Comparable listings")
    points = pd.concat([
        pd.DataFrame({"lat": [lat], "lon": [lon], "color": ["#d62728"], "size": [60]}),        # the property
        basis["comps"].assign(color="#ff5a5f", size=25)[["latitude", "longitude", "color", "size"]]
            .rename(columns={"latitude": "lat", "longitude": "lon"}),                             # Airbnbs
        rent["comps"].assign(color="#1f77b4", size=25)[["latitude", "longitude", "color", "size"]]
            .rename(columns={"latitude": "lat", "longitude": "lon"}),                             # rentals
    ])
    st.map(points, latitude="lat", longitude="lon", color="color", size="size")
    st.caption("Dark red: the property. Pink: comparable Airbnbs. Blue: comparable rentals.")
    with st.expander("Closest comparable Airbnbs"):
        st.dataframe(comps_table(basis["comps"], {
            "nightly_price": ("Price / night", money),
            "nights_booked": ("Nights booked / year", lambda v: f"{v:.0f}"),
        }), hide_index=True, width="stretch")
    with st.expander("Closest comparable rentals"):
        st.dataframe(comps_table(rent["comps"], {
            "monthly_income": ("Rent / month", money),
        }), hide_index=True, width="stretch")

    st.divider()
    for note in LEGAL_NOTES:
        st.caption(note)
    st.caption("Data: Airbnb listings from Inside Airbnb (insideairbnb.com); rental listings from RentCast; "
               "address suggestions via Photon (© OpenStreetMap contributors); addresses located with the "
               "U.S. Census Bureau geocoder. Costs are assumptions; see assumptions.py.")
