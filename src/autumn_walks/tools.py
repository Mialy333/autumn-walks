"""Strands tools for planning autumn walks in Paris."""

import itertools
import json
import math
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from strands import tool

from autumn_walks.load_trees import DB_PATH

EARTH_RADIUS_M = 6_371_000
GENUS_PRIORITY = ["Ginkgo", "Liquidambar", "Parrotia", "Acer", "Quercus"]
N_RINGS = 3  # distance rings across the radius, so stops are spread out
MIN_STOPS = 3
MAX_STOPS = 5
MAX_CANDIDATES = 10
MAX_LOOP_M = 3000  # about 40 minutes of walking
AFTERNOON_HOURS = range(14, 19)  # 14:00 to 18:00 local time
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
    return {
        "id": r["id"],
        "common_name": r["common_name"],
        "genus": r["genus"],
        "species": r["species"],
        "address": r["address"],
        "lat": round(r["lat"], 6),
        "lon": round(r["lon"], 6),
        "arrondissement": r["arrondissement"],
        "remarkable": bool(r["remarkable"]),
    }


@tool
def find_autumn_trees(lat: float, lon: float, radius_m: int = 1500, limit: int = 10) -> list[dict]:
    """Find trees with strong autumn colour (ginkgo, sweetgum, Persian ironwood, maple, oak) around a point in Paris.

    Returns a varied selection spread across the whole radius: rarer genera first, one tree per street or park.

    Args:
        lat: Latitude of the starting point.
        lon: Longitude of the starting point.
        radius_m: Search radius in metres.
        limit: Maximum number of trees to return.
    """
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
    return [{**_tree_dict(r), "distance_m": round(dist)} for dist, r in picked]


@tool
def build_walk(start_lat: float, start_lon: float, tree_ids: list[int]) -> dict:
    """Turn candidate trees into a walking loop of about 40 minutes that starts and ends at the starting point.

    From the candidates, keeps the 3 to 5 stops with the most varied genera whose loop fits in 3 km,
    orders them, and computes every distance and the Google Maps link.
    Copy its numbers and link exactly; never compute distances yourself.

    Args:
        start_lat: Latitude of the starting point.
        start_lon: Longitude of the starting point.
        tree_ids: Ids of 3 to 10 candidate trees from find_autumn_trees.
    """
    ids = list(dict.fromkeys(int(i) for i in tree_ids))
    if not MIN_STOPS <= len(ids) <= MAX_CANDIDATES:
        return {"error": f"Pass between {MIN_STOPS} and {MAX_CANDIDATES} tree ids, got {len(ids)}."}
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    found = {
        r["id"]: r
        for r in con.execute(
            f"SELECT * FROM trees WHERE id IN ({','.join('?' * len(ids))})", ids
        )
    }
    con.close()
    missing = [i for i in ids if i not in found]
    if missing:
        return {"error": f"Unknown tree ids: {missing}. Use ids returned by find_autumn_trees."}

    start = (start_lat, start_lon)

    def loop_m(seq: tuple[sqlite3.Row, ...]) -> float:
        path = [start, *((r["lat"], r["lon"]) for r in seq), start]
        return sum(haversine_m(*a, *b) for a, b in zip(path, path[1:]))

    # Shortest ordering of every 3-5 stop subset; keep the best one that fits.
    best, best_key = None, None
    for k in range(MIN_STOPS, MAX_STOPS + 1):
        for subset in itertools.combinations((found[i] for i in ids), k):
            seq = min(itertools.permutations(subset), key=loop_m)
            length = loop_m(seq)
            if length > MAX_LOOP_M:
                continue
            key = (len({r["genus"] for r in seq}), k, -length)
            if best_key is None or key > best_key:
                best, best_key = seq, key
    if best is None:
        return {
            "error": f"No 3-stop loop from these trees fits in {MAX_LOOP_M} m. "
            "Pass more trees that are closer to the starting point."
        }

    stops, prev = [], start
    for n, r in enumerate(best, 1):
        here = (r["lat"], r["lon"])
        stops.append(
            {
                "stop": n,
                **_tree_dict(r),
                "distance_from_start_m": round(haversine_m(*start, *here)),
                "distance_from_previous_m": round(haversine_m(*prev, *here)),
            }
        )
        prev = here
    waypoints = "|".join(f"{s['lat']},{s['lon']}" for s in stops)
    origin = f"{start_lat},{start_lon}"
    return {
        "stops": stops,
        "return_to_start_m": round(haversine_m(*prev, *start)),
        "total_loop_m": round(loop_m(best)),
        "skipped_tree_ids": [i for i in ids if i not in {s["id"] for s in stops}],
        "google_maps_url": (
            "https://www.google.com/maps/dir/?api=1"
            f"&origin={origin}&destination={origin}&waypoints={waypoints}&travelmode=walking"
        ),
    }


@tool
def get_weather(lat: float, lon: float) -> dict:
    """Get this afternoon's weather (14:00-18:00, Paris time) at a location: temperature, rain probability and wind.

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
    return {
        "period": "14:00-18:00",
        "temperature_c_min": min(temps),
        "temperature_c_max": max(temps),
        "rain_probability_pct_max": max(rain),
        "wind_kmh_max": max(wind),
    }
