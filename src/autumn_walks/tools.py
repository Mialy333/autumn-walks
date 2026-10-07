"""Strands tools for planning autumn walks in Paris."""

import itertools
import json
import math
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from strands import tool

from autumn_walks.config import (
    DETOUR_FACTOR,
    MAX_LOOP_M,
    SEARCH_RADIUS_M,
    WALK_M_PER_MIN,
)
from autumn_walks.load_trees import DB_PATH

EARTH_RADIUS_M = 6_371_000
GENUS_PRIORITY = ["Ginkgo", "Liquidambar", "Parrotia", "Acer", "Quercus"]
N_RINGS = 3  # distance rings across the radius, so stops are spread out
MIN_STOPS = 3
MAX_STOPS = 5
MAX_CANDIDATES = 10
UMBRELLA_RAIN_PCT = 50
AFTERNOON_HOURS = range(14, 19)  # 14:00 to 18:00 local time

# Plain tree name and October look per genus. The model copies these, never invents them.
GENUS_INFO = {
    "fr": {
        "Ginkgo": ("Ginkgo", "jaune doré"),
        "Liquidambar": ("Liquidambar", "du rouge au pourpre"),
        "Parrotia": ("Parrotie de Perse", "du rouge à l'orange"),
        "Acer": ("Érable", "rouge ou orange"),
        "Quercus": ("Chêne", "brun cuivré"),
    },
    "en": {
        "Ginkgo": ("Ginkgo", "golden yellow"),
        "Liquidambar": ("Sweetgum", "red to purple"),
        "Parrotia": ("Persian ironwood", "red to orange"),
        "Acer": ("Maple", "red or orange"),
        "Quercus": ("Oak", "copper brown"),
    },
}


def walk_lang() -> str:
    """Language of the walk message, from WALK_LANG (fr or en, default fr)."""
    lang = os.environ.get("WALK_LANG", "fr").lower()
    return lang if lang in GENUS_INFO else "fr"


def _num(x: float, decimals: int = 1) -> str:
    """Number with a decimal comma in French, a decimal point in English."""
    text = f"{x:.{decimals}f}"
    return text.replace(".", ",") if walk_lang() == "fr" else text


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def _tree_dict(r: sqlite3.Row) -> dict:
    tree, colours = GENUS_INFO[walk_lang()][r["genus"]]
    return {
        "id": r["id"],
        "tree": tree,
        "genus": r["genus"],
        "october_colours": colours,
        "place": r["place"],
        "lat": round(r["lat"], 6),
        "lon": round(r["lon"], 6),
    }


@tool
def find_autumn_trees(lat: float, lon: float) -> list[dict]:
    """Find trees with strong autumn colour (ginkgo, sweetgum, Persian ironwood, maple, oak) around a point in Paris.

    Returns candidate ids within 2 km, spread out: ginkgo and sweetgum first, one tree per street or park.
    Pass all the ids to build_walk, which returns the stops' names, places and colours.

    Args:
        lat: Latitude of the starting point.
        lon: Longitude of the starting point.
    """
    radius_m, limit = SEARCH_RADIUS_M, MAX_CANDIDATES
    # Bounding box prefilter, then exact haversine distance.
    dlat = math.degrees(radius_m / EARTH_RADIUS_M)
    dlon = dlat / math.cos(math.radians(lat))
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM trees WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
        (lat - dlat, lat + dlat, lon - dlon, lon + dlon),
    ).fetchall()
    con.close()

    # Bucket candidates by (genus, distance ring), nearest first within each bucket.
    ring_width = radius_m / N_RINGS
    pools: dict[tuple[str, int], list[tuple[float, sqlite3.Row]]] = {}
    for r in rows:
        dist = haversine_m(lat, lon, r["lat"], r["lon"])
        if dist <= radius_m:
            ring = min(int(dist // ring_width), N_RINGS - 1)
            pools.setdefault((r["genus"], ring), []).append((dist, r))
    for pool in pools.values():
        pool.sort(key=lambda x: x[0])

    # Round-robin over (genus, ring) in genus priority order, one tree per street.
    order = [(g, ring) for g in GENUS_PRIORITY for ring in range(N_RINGS)]
    used_streets: set[str] = set()
    picked: list[tuple[float, sqlite3.Row]] = []
    while len(picked) < limit and any(pools.get(k) for k in order):
        for key in order:
            pool = pools.get(key)
            while pool and pool[0][1]["street"] in used_streets:
                pool.pop(0)
            if not pool:
                continue
            dist, r = pool.pop(0)
            used_streets.add(r["street"])
            picked.append((dist, r))
            if len(picked) >= limit:
                break

    picked.sort(key=lambda x: x[0])
    return [{"id": r["id"], "genus": r["genus"], "distance_m": round(dist)} for dist, r in picked]


@tool
def build_walk(start_lat: float, start_lon: float, tree_ids: list[int]) -> dict:
    """Turn candidate trees into a walking loop of up to about 50 minutes that starts and ends at the starting point.

    From the candidates, keeps the 3 to 5 stops with the most varied genera whose loop fits in 4 km,
    orders them, and gives the total distance, walking time and Google Maps link.
    Copy its trees, places, colours, numbers and link exactly; never compute or invent anything.

    Args:
        start_lat: Latitude of the starting point.
        start_lon: Longitude of the starting point.
        tree_ids: Ids of up to 10 candidate trees from find_autumn_trees. If they cannot make a walk,
            the nearest trees are added automatically.
    """
    ids = list(dict.fromkeys(int(i) for i in tree_ids))[:MAX_CANDIDATES]
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    found = {
        r["id"]: r
        for r in con.execute(
            f"SELECT * FROM trees WHERE id IN ({','.join('?' * len(ids))})", ids
        )
    }
    missing = [i for i in ids if i not in found]
    if missing:
        con.close()
        return {"error": f"Unknown tree ids: {missing}. Use ids returned by find_autumn_trees."}

    start = (start_lat, start_lon)

    def loop_m(seq: tuple[sqlite3.Row, ...]) -> float:
        path = [start, *((r["lat"], r["lon"]) for r in seq), start]
        return sum(haversine_m(*a, *b) for a, b in zip(path, path[1:]))

    def best_loop(candidates: list[sqlite3.Row]) -> tuple[sqlite3.Row, ...] | None:
        """Shortest ordering of every 3-5 stop subset; the best one that fits."""
        best, best_key = None, None
        for k in range(MIN_STOPS, MAX_STOPS + 1):
            for subset in itertools.combinations(candidates, k):
                seq = min(itertools.permutations(subset), key=loop_m)
                length = loop_m(seq)
                if length > MAX_LOOP_M:
                    continue
                key = (len({r["genus"] for r in seq}), k, -length)
                if best_key is None or key > best_key:
                    best, best_key = seq, key
        return best

    chosen = [found[i] for i in ids]
    best = best_loop(chosen)
    if best is None:
        # The candidates are too few or too far apart: keep the 5 closest and add the nearest trees.
        chosen.sort(key=lambda r: haversine_m(*start, r["lat"], r["lon"]))
        chosen = chosen[:MAX_STOPS]
        streets = {r["street"] for r in chosen}
        dlat = math.degrees(MAX_LOOP_M / 4 / EARTH_RADIUS_M)
        dlon = dlat / math.cos(math.radians(start_lat))
        nearby = sorted(
            con.execute(
                "SELECT * FROM trees WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                (start_lat - dlat, start_lat + dlat, start_lon - dlon, start_lon + dlon),
            ),
            key=lambda r: haversine_m(*start, r["lat"], r["lon"]),
        )
        for r in nearby:
            if len(chosen) >= MAX_CANDIDATES:
                break
            if r["street"] not in streets:
                streets.add(r["street"])
                chosen.append(r)
        best = best_loop(chosen)
    con.close()
    if best is None:
        return {"error": f"No walk of 3 stops or more fits in {MAX_LOOP_M} m around this point."}

    stops = [{"stop": n, **_tree_dict(r)} for n, r in enumerate(best, 1)]
    total = round(loop_m(best))
    waypoints = "|".join(f"{s['lat']},{s['lon']}" for s in stops)
    origin = f"{start_lat},{start_lon}"
    return {
        "start": [start_lat, start_lon],
        "stops": stops,
        "total_loop_m": total,
        "total_distance": f"{_num(total / 1000)} km",
        "walking_time_min": round(total * DETOUR_FACTOR / WALK_M_PER_MIN / 5) * 5,
                "google_maps_url": (
            "https://www.google.com/maps/dir/?api=1"
            f"&origin={origin}&destination={origin}&waypoints={waypoints}&travelmode=walking"
        ),
    }


@tool
def get_weather(lat: float, lon: float) -> dict:
    """Get this afternoon's weather (14:00-18:00, Paris time) at a location: temperature, rain probability and wind.

    Also says whether an umbrella is advised and which hour is the driest.

    Args:
        lat: Latitude.
        lon: Longitude.
    """
    params = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,precipitation_probability,wind_speed_10m",
            "timezone": "Europe/Paris",
            "forecast_days": 1,
        }
    )
    data = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(f"{OPEN_METEO_URL}?{params}", timeout=10) as resp:
                data = json.load(resp)
            break
        except (urllib.error.URLError, TimeoutError) as e:
            error = str(e)
            time.sleep(1 + attempt)
    if data is None:
        return {"error": f"Weather unavailable (Open-Meteo: {error})"}

    hourly = data["hourly"]
    idx = [i for i, t in enumerate(hourly["time"]) if int(t[11:13]) in AFTERNOON_HOURS]
    temps = [hourly["temperature_2m"][i] for i in idx]
    rain = [hourly["precipitation_probability"][i] for i in idx]
    wind = [hourly["wind_speed_10m"][i] for i in idx]
    driest = min(range(len(idx)), key=lambda k: rain[k])  # earliest hour on ties
    hour = int(hourly["time"][idx[driest]][11:13])
    fr = walk_lang() == "fr"
    # Ready-to-copy text, formatted for the message language.
    return {
        "period": "14:00-18:00",
        "temperature": f"{_num(min(temps))} {'à' if fr else 'to'} {_num(max(temps))} °C",
        "rain_probability": f"{max(rain)} %" if fr else f"{max(rain)}%",
        "wind": f"{_num(max(wind))} km/h",
        "umbrella_advised": max(rain) > UMBRELLA_RAIN_PCT,
        "driest_hour": f"{hour} h" if fr else f"{hour - 12 if hour > 12 else hour} pm",
    }
