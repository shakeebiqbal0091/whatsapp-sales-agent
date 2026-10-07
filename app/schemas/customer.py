import re

_NON_DIGITS = re.compile(r"\D")


def normalize_phone(raw: str) -> str:
    """Canonical E.164-style form: '+<digits>'. WhatsApp sends digits only; /chat may send '+92 300-...'."""
    digits = _NON_DIGITS.sub("", raw)
    if not 8 <= len(digits) <= 15:
        raise ValueError("phone number must contain 8-15 digits")
    return f"+{digits}"
