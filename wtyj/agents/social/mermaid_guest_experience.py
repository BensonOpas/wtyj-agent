"""Shared guest-facing facts for chat, checkout and reservation documents."""
from datetime import datetime
from shared import mermaid_catalog
from agents.social.mermaid_reservation_store import _money_snapshot


def guest_copy(locale):
    copies = mermaid_catalog.get_catalog()["guest_copy"]
    return copies.get(locale, copies["en"])


def transport_text(intake, locale, money=None):
    copy = guest_copy(locale)
    if intake.get("pickup_preference") == "pickup_requested":
        money = intake_money(intake) if money is None else money
        if money.get("pickup_amount") is not None:
            return copy["pickup_priced"].format(
                location=intake.get("pickup_location") or copy["hotel"],
                currency=money["currency"], amount=f"{money['pickup_amount']:,.2f}",
            )
        return copy["pickup_pending"].format(location=intake.get("pickup_location") or copy["hotel"])
    service = mermaid_catalog.get_catalog()["service"]
    return copy["pier_arrival"].format(place=service["meeting_point"], time=service["arrival_time"])


def price_text(money, intake, locale):
    copy = guest_copy(locale)
    label = copy["trip_total"]
    if intake.get("pickup_preference") == "pickup_requested":
        label = copy["pickup_total"] if money.get("pickup_amount") is not None else copy["trip_only"]
    return f"{label}: {money['currency']} {int(money['total']):,.2f}"


def intake_money(intake):
    return _money_snapshot(intake, mermaid_catalog.get_catalog())


def guest_date(value, locale="en"):
    # Human-readable English dates; ISO remains unambiguous in other locales.
    if locale == "en":
        return datetime.strptime(value, "%Y-%m-%d").strftime("%A %d %B %Y").replace(" 0", " ")
    return value


def party_text(intake, locale):
    copy = guest_copy(locale)
    parts = []
    for key in ("adults", "children", "infants"):
        count = intake.get(key, 0)
        if count:
            template = copy.get(key + "_one", copy[key]) if count == 1 else copy[key]
            parts.append(template.format(count=count))
    return ", ".join(parts)
