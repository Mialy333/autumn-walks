"""Turn the dataset's UPPERCASE addresses into short, readable place names.

"JARDINIERE DE LA RUE DES MARTYRS / ANGLE RUE ..." -> "rue des Martyrs"
"16 RUE DE HANOVRE"                                -> "16 rue de Hanovre"
"SQUARE D ANVERS JEAN CLAUDE CARRIERE / 3 PLACE"   -> "Square d'Anvers Jean Claude Carrière"
"""

import re

STREET_TYPES = (
    "RUE|AVENUE|BOULEVARD|PLACE|PASSAGE|IMPASSE|QUAI|VILLA|CITE|ALLEE|COURS|PORTE|ROND-POINT|CHAUSSEE"
)
SITES = "PARC|SQUARE|JARDIN|JARDINS|CIMETIERE|PROMENADE|ESPLANADE"
# Planters, verges and lawns: the useful part is the street named after them.
FILLERS = "JARDINIERES?|JARDINET|PELOUSE|TALUS|TERRE PLEIN"

LOWER = {
    "de", "du", "des", "la", "le", "les", "et", "au", "aux", "sur", "en", "bis", "ter",
    *(t.lower() for t in STREET_TYPES.split("|")),
}
ACCENTS = {
    "cimetiere": "cimetière", "cite": "cité", "allee": "allée", "chaussee": "chaussée",
    "general": "Général", "elysees": "Élysées", "carriere": "Carrière", "theatre": "théâtre",
    "marechal": "Maréchal", "republique": "République", "dominicaine": "Dominicaine",
    "etoile": "Étoile", "therese": "Thérèse", "leon": "Léon", "eglise": "église",
}
HOUSE_NUMBER = re.compile(r"^\d+\s*(?:bis|ter|[A-Z])?$", re.I)
TRAILING_CODE = re.compile(r"\s+(?:PR\s+)?[A-Z]\d+$|\s+N°.*$|\s+SUD$|\s+NORD$")


def _case(text: str) -> str:
    words = []
    for i, w in enumerate(text.split()):
        low = w.lower()
        if low in ("d", "l") and i + 1 < len(text.split()):
            words.append(low + "'")
            continue
        if low in LOWER:
            out = ACCENTS.get(low, low)
        else:
            out = "-".join(ACCENTS.get(p.lower(), p.capitalize()) for p in w.split("-"))
        words.append(out)
    return " ".join(words).replace("' ", "'")


def display_place(adresse: str, complement: str = "") -> str:
    segments = [s.strip() for s in adresse.split(" / ") if s.strip()]
    first = segments[0] if segments else ""
    street_in = re.compile(rf"\b(?:{STREET_TYPES})\b.*")

    if re.match(rf"^(?:{SITES})\b", first):
        name = TRAILING_CODE.sub("", first)
        return name[0].upper() + _case(name)[1:] if name else name
    if re.match(rf"^(?:{FILLERS})\b", first) and (m := street_in.search(first)):
        return _case(TRAILING_CODE.sub("", m.group(0)))
    if len(segments) > 1 and street_in.search(segments[1]):
        return _case(segments[1])
    name = _case(TRAILING_CODE.sub("", first))
    number = re.sub(r"^N°\s*", "", complement.strip(), flags=re.I)
    if HOUSE_NUMBER.match(number) and number != "0":
        name = f"{number} {name}"
    return name


def street_key(place: str) -> str:
    """Place name without its house number, used to keep one tree per street."""
    return re.sub(r"^\d+\s*(?:bis|ter|[A-Za-z])?\s+", "", place).lower()
