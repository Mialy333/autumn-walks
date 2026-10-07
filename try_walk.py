"""Walk test: ask for an autumn walk several times and check each message.

Usage: uv run python try_walk.py ["question"] [runs]
The message language follows WALK_LANG (fr or en, default fr).
Runs share a fresh, temporary walk history, so each walk avoids the trees of the previous ones.
"""

import os
import re
import sys
import tempfile
import time
from pathlib import Path

os.environ["WALK_HISTORY_DB"] = str(Path(tempfile.mkdtemp()) / "history.sqlite")

from autumn_walks.agent import MAX_WORDS, plan_walk
from autumn_walks.config import MAX_LOOP_M, RECENT_WALKS_EXCLUDED
from autumn_walks.history import record_walk
from autumn_walks.places import street_key
from autumn_walks.tools import haversine_m, walk_lang

LANG = walk_lang()
DEFAULT_PROMPT = {
    "fr": "Propose-moi une balade d'automne d'environ 45 minutes au départ de l'Opéra Garnier "
    "(48.8719, 2.3316), avec 3 à 5 arrêts et un lien Google Maps.",
    "en": "Plan me an autumn walk of about 45 minutes starting from Opéra Garnier (48.8719, 2.3316). "
    "3 to 5 stops, with a Google Maps link.",
}[LANG]
PROMPT = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROMPT
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
OUT_DIR = Path(__file__).parent / "walks"

COORD = re.compile(r"(4[89]\.\d{3,})\s*,\s*(2\.\d{3,})")
MAPS_URL = re.compile(r"https?://(?:www\.)?google\.[^\s)\]>\"']*maps[^\s)\]>\"']*")


def loop_from_link(answer: str, start: tuple[float, float]) -> float | None:
    """Independent check: straight-line loop through the coordinates in the answer's Maps link."""
    urls = MAPS_URL.findall(answer)
    if not urls:
        return None
    points = [(float(a), float(b)) for a, b in COORD.findall(urls[0].replace("%2C", ","))]
    stops = [p for p in points if haversine_m(*p, *start) >= 30]
    path = [start, *stops, start]
    return sum(haversine_m(*a, *b) for a, b in zip(path, path[1:])) if stops else None


def run_once(i: int, previous: list[dict]) -> dict:
    start = time.perf_counter()
    result = plan_walk(PROMPT)
    latency = time.perf_counter() - start

    answer, walk, calls = result.message, result.walk, result.tool_calls
    link_loop = loop_from_link(answer, result.start)
    checks = {
        "weather called": any(c["name"] == "get_weather" for c in calls),
        "trees called": any(c["name"] == "find_autumn_trees" for c in calls),
        "walk built": walk is not None,
        "right start": walk is not None and haversine_m(*walk["start"], *result.start) < 50,
        "3-5 stops": walk is not None and 3 <= len(walk["stops"]) <= 5,
        "loop ≤ 4 km": walk is not None and walk["total_loop_m"] <= MAX_LOOP_M,
        "total copied": walk is not None and walk["total_distance"] in answer,
        "link copied": walk is not None and walk["google_maps_url"] in answer,
        "wind mentioned": bool(re.search(r"\b(wind|vent)", answer, re.I)),
        f"< {MAX_WORDS} words": len(answer.split()) < MAX_WORDS,
        "new places": walk is not None
        and not {street_key(s["place"]) for s in walk["stops"]}
        & {street_key(s["place"]) for w in previous[-RECENT_WALKS_EXCLUDED:] for s in w["stops"]},
    }
    if walk:
        record_walk(walk)

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"test-run-{i}-{LANG}.md").write_text(
        f"# Test run {i} ({LANG})\n\n> {PROMPT}\n\n{answer}\n", encoding="utf-8"
    )

    print(f"\n[run {i}] latency={latency:.2f}s retries={result.retries}")
    for n, reason in enumerate(result.retry_reasons, 1):
        print(f"  retry {n}: {reason}")
    for c in calls:
        print(f"  tool: {c['name']}({c['input']})")
    if walk:
        print(f"  build_walk: {len(walk['stops'])} stops, loop {walk['total_loop_m']} m")
        for s in walk["stops"]:
            print(f"    {s['id']:>8} {s['genus']:<12} {s['place']}")
    print(f"  loop recomputed from answer's link: {f'{link_loop:.0f} m' if link_loop else 'n/a'}")
    print(f"  words: {len(answer.split())}")
    print(f"  failed checks: {[k for k, ok in checks.items() if not ok] or 'none'}")
    return {
        "run": i,
        "latency": latency,
        "calls": calls,
        "walk": walk,
        "checks": checks,
        "retries": result.retries,
        "retry_reasons": result.retry_reasons,
        "answer": answer,
    }


if __name__ == "__main__":
    rows = []
    for i in range(1, RUNS + 1):
        rows.append(run_once(i, [r["walk"] for r in rows if r["walk"]]))

    print("\n| Run | Tool calls | Retries | Stops (genera) | Loop | Words | Checks | Latency (s) |")
    print("|-----|------------|---------|----------------|------|-------|--------|-------------|")
    for r in rows:
        calls = ", ".join(c["name"] for c in r["calls"]) or "-"
        w = r["walk"]
        stops = f"{len(w['stops'])} ({', '.join(s['genus'] for s in w['stops'])})" if w else "-"
        loop = f"{w['total_loop_m']} m" if w else "n/a"
        passed = sum(r["checks"].values())
        words = len(r["answer"].split())
        print(
            f"| {r['run']} | {calls} | {r['retries']} | {stops} | {loop} | {words} | "
            f"{passed}/{len(r['checks'])} | {r['latency']:.2f} |"
        )

    print(f"\nQuestion: {PROMPT}")
    for r in rows:
        for n, reason in enumerate(r["retry_reasons"], 1):
            print(f"Run {r['run']} retry {n}: {reason}")
    print(f"\n--- Message, run 1 ({LANG}) ---\n\n{rows[0]['answer']}")
    ok = all(all(r["checks"].values()) for r in rows)
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'} - messages saved to walks/test-run-N-{LANG}.md")
    raise SystemExit(0 if ok else 1)
