"""Step 2 test: plan an autumn walk from Opéra Garnier with real trees and weather (3 runs)."""

import re
import time
from pathlib import Path

from strands import Agent
from strands.models.ollama import OllamaModel

from autumn_walks.tools import build_walk, find_autumn_trees, get_weather, haversine_m

START = (48.8719, 2.3316)
PROMPT = (
    "Plan me a 40-minute autumn walk starting from Opéra Garnier (48.8719, 2.3316). "
    "3 to 5 stops, with a Google Maps link."
)
SYSTEM_PROMPT = """You plan short autumn walks in Paris.
1. Call get_weather for the starting point.
2. Call find_autumn_trees for the starting point.
3. Call build_walk once with the ids of all the trees find_autumn_trees returned.
   It picks the best 3 to 5 stops that fit in 40 minutes.
4. Answer with:
   - the afternoon weather: temperature, rain probability AND wind;
   - the stops in build_walk's order: common name, genus, address, distance_from_previous_m;
   - the return distance and total_loop_m;
   - build_walk's google_maps_url, copied exactly.
Copy every distance and the link exactly as the tools return them. Never compute or estimate a distance yourself.
Only use trees returned by find_autumn_trees."""
RUNS = 3
MAX_WALK_M = 3000
OUT_DIR = Path(__file__).parent / "walks"

COORD = re.compile(r"(4[89]\.\d{3,})\s*,\s*(2\.\d{3,})")
MAPS_URL = re.compile(r"https?://(?:www\.)?google\.[^\s)\]>\"']*maps[^\s)\]>\"']*")


def tool_uses(agent: Agent) -> list[dict]:
    return [b["toolUse"] for m in agent.messages for b in m["content"] if "toolUse" in b]


def presented_walk(agent: Agent, answer: str) -> dict | None:
    """The build_walk result whose Maps link the answer shows (the tool is deterministic, so recompute it)."""
    walks = [
        build_walk._tool_func(**u["input"]) for u in tool_uses(agent) if u["name"] == "build_walk"
    ]
    walks = [w for w in walks if "error" not in w]
    for w in walks:
        if w["google_maps_url"] in answer:
            return w
    return walks[-1] if walks else None


def loop_from_link(answer: str) -> float | None:
    """Independent check: straight-line loop through the coordinates in the answer's Maps link."""
    urls = MAPS_URL.findall(answer)
    if not urls:
        return None
    points = [(float(a), float(b)) for a, b in COORD.findall(urls[0].replace("%2C", ","))]
    stops = [p for p in points if haversine_m(*p, *START) >= 30]
    path = [START, *stops, START]
    return sum(haversine_m(*a, *b) for a, b in zip(path, path[1:])) if stops else None


def run_once(i: int) -> dict:
    model = OllamaModel(host="http://localhost:11434", model_id="gemma4:e2b")
    agent = Agent(
        model=model,
        tools=[find_autumn_trees, get_weather, build_walk],
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,
    )
    start = time.perf_counter()
    answer = str(agent(PROMPT)).strip()
    latency = time.perf_counter() - start

    calls = tool_uses(agent)
    walk = presented_walk(agent, answer)
    link_loop = loop_from_link(answer)
    checks = {
        "weather called": any(c["name"] == "get_weather" for c in calls),
        "trees called": any(c["name"] == "find_autumn_trees" for c in calls),
        "walk built": walk is not None,
        "3-5 stops": walk is not None and 3 <= len(walk["stops"]) <= 5,
        "loop ≤ 3 km": walk is not None and walk["total_loop_m"] <= MAX_WALK_M,
        "total copied": walk is not None and str(walk["total_loop_m"]) in re.sub(r"[,.\s\u202f]", "", answer),
        "link copied": walk is not None and walk["google_maps_url"] in answer,
        "wind mentioned": bool(re.search(r"\bwind", answer, re.I)),
    }

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"test-run-{i}.md").write_text(f"# Test run {i}\n\n> {PROMPT}\n\n{answer}\n", encoding="utf-8")

    print(f"\n[run {i}] latency={latency:.2f}s")
    for c in calls:
        print(f"  tool: {c['name']}({c['input']})")
    if walk:
        print(f"  build_walk: {len(walk['stops'])} stops, {[s['genus'] for s in walk['stops']]}, loop {walk['total_loop_m']} m")
    print(f"  loop recomputed from answer's link: {f'{link_loop:.0f} m' if link_loop else 'n/a'}")
    print(f"  failed checks: {[k for k, ok in checks.items() if not ok] or 'none'}")
    return {"run": i, "latency": latency, "calls": calls, "walk": walk, "checks": checks}


if __name__ == "__main__":
    rows = [run_once(i) for i in range(1, RUNS + 1)]

    print("\n| Run | Tool calls | Stops (genera) | Loop | Checks | Latency (s) |")
    print("|-----|------------|----------------|------|--------|-------------|")
    for r in rows:
        calls = ", ".join(c["name"] for c in r["calls"]) or "-"
        w = r["walk"]
        stops = f"{len(w['stops'])} ({', '.join(s['genus'] for s in w['stops'])})" if w else "-"
        loop = f"{w['total_loop_m']} m" if w else "n/a"
        passed = sum(r["checks"].values())
        print(f"| {r['run']} | {calls} | {stops} | {loop} | {passed}/{len(r['checks'])} | {r['latency']:.2f} |")

    ok = all(all(r["checks"].values()) for r in rows)
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'} - answers saved to walks/test-run-N.md")
    raise SystemExit(0 if ok else 1)
