"""Validate customer-supplied ages without deriving ages from fare bands."""


def age_months(age):
    return age["value"] * (12 if age["unit"] == "years" else 1)


def age_band(age):
    return "infants" if age_months(age) < 48 else "children"


def normalize_child_ages(value, counts=None):
    if not isinstance(value, list) or len(value) > 100:
        return None
    result = []
    for age in value:
        if not isinstance(age, dict) or set(age) != {"value", "unit"}:
            return None
        if type(age["value"]) is not int or age["value"] < 0 or age["unit"] not in {"months", "years"}:
            return None
        if age_months(age) >= 156:
            return None
        result.append({"value": age["value"], "unit": age["unit"]})
    if counts:
        for band in ("children", "infants"):
            if band in counts and sum(age_band(a) == band for a in result) > counts[band]:
                return None
    return result
