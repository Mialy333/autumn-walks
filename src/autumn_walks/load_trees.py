"""Build data/trees.sqlite from the Paris "les-arbres" CSV export.

Keeps only strong-autumn-colour genera in the 1st, 2nd, 8th, 9th and 17th arrondissements,
and only trees a walker can reach: streets, public gardens and cemeteries
(not school yards, nurseries, sports grounds or the ring road).
Usage: uv run python -m autumn_walks.load_trees
"""

import csv
import sqlite3
from pathlib import Path

from autumn_walks.places import display_place, street_key

ROOT = Path(__file__).resolve().parents[2]
RAW_CSV = ROOT / "data" / "raw" / "les-arbres.csv"
DB_PATH = ROOT / "data" / "trees.sqlite"

GENERA = {"Ginkgo", "Liquidambar", "Acer", "Parrotia", "Quercus"}
ARRONDISSEMENTS = {
    "PARIS 1ER ARRDT": 1,
    "PARIS 2E ARRDT": 2,
    "PARIS 8E ARRDT": 8,
    "PARIS 9E ARRDT": 9,
    "PARIS 17E ARRDT": 17,
}
PUBLIC_DOMAINS = {"Alignement", "Jardin", "CIMETIERE"}
REMARKABLE = {"OUI": 1, "NON": 0}


def rows():
    with RAW_CSV.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            arr = ARRONDISSEMENTS.get(r["arrondissement"])
            if (
                arr is None
                or r["genre"] not in GENERA
                or r["domanialite"] not in PUBLIC_DOMAINS
                or not r["geo_point_2d"]
            ):
                continue
            lat, lon = (float(x) for x in r["geo_point_2d"].split(","))
            place = display_place(r["adresse"], r["complementadresse"])
            extra = r["complementadresse"].strip().removeprefix("0").strip()
            if extra.isdigit():
                address = f"{extra} {r['adresse']}"
            elif extra:
                address = f"{r['adresse']} ({extra})"
            else:
                address = r["adresse"]
            yield (
                int(r["idbase"]),
                r["libellefrancais"] or None,
                r["genre"],
                r["espece"] or None,
                address or None,
                place or None,
                street_key(place) or None,
                lat,
                lon,
                arr,
                REMARKABLE.get(r["remarquable"]),
            )


def main() -> None:
    DB_PATH.unlink(missing_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """CREATE TABLE trees (
            id INTEGER PRIMARY KEY,
            common_name TEXT,
            genus TEXT NOT NULL,
            species TEXT,
            address TEXT,
            place TEXT,
            street TEXT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            arrondissement INTEGER NOT NULL,
            remarkable INTEGER
        )"""
    )
    con.executemany("INSERT INTO trees VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows())
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM trees").fetchone()[0]
    print(f"Kept {n} trees -> {DB_PATH.relative_to(ROOT)}")
    con.close()


if __name__ == "__main__":
    main()
