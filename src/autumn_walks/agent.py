"""The walk-planning agent: Gemma 4 E2B on Ollama with the tree, walk and weather tools."""

import re
from dataclasses import dataclass, field

from strands import Agent
from strands.models.ollama import OllamaModel

from autumn_walks.config import DEFAULT_START, DEFAULT_START_NAME
from autumn_walks.tools import build_walk, find_autumn_trees, get_weather, haversine_m, walk_lang

OLLAMA_HOST = "http://localhost:11434"
MODEL_ID = "gemma4:e2b"
MAX_RETRIES = 2
MAX_WORDS = 150
WIND_WORD = {"fr": r"\bvent", "en": r"\bwind"}
COORDS = re.compile(r"(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)")

LANGUAGES = {"fr": "French", "en": "English"}
SYSTEM_PROMPT = """You write short invitations to go for an autumn walk in Paris, sent on Telegram, in {language}.
The walk starts from {start_name} ({lat}, {lon}).
1. Call get_weather with these coordinates.
2. Call find_autumn_trees with these coordinates.
3. Call build_walk once with these coordinates and the ids of all the trees find_autumn_trees returned.
   You cannot write the message without build_walk: only it gives the stops' trees, places, colours,
   total_distance, walking_time_min and google_maps_url.
Then reply with ONLY the message, in {language}, at most 120 words, warm and inviting:
- First line: one sentence of weather advice that ALWAYS gives the temperature, rain_probability
  AND wind, copied as written.
  If umbrella_advised is true, suggest taking an umbrella or going at driest_hour.
- Then one numbered line per stop, in build_walk's order: the tree, its place, and its october_colours.
- Then one line with total_distance and walking_time_min minutes on foot.
- Last line: google_maps_url, exactly as given.
Copy trees, places, colours, numbers and the link exactly from the tools.
Never invent a tree, a colour or a number, and never compute anything. No headings, no bold."""

RETRY_PROMPT = (
    "Your message was not sent: {problem} "
    "Call build_walk with the ids from find_autumn_trees, then rewrite the message using only "
    "its trees, places, colours, total_distance, walking_time_min and google_maps_url."
)


@dataclass
class WalkResult:
    message: str
    walk: dict | None
    start: tuple[float, float] = DEFAULT_START
    tool_calls: list[dict] = field(default_factory=list)
    retry_reasons: list[str] = field(default_factory=list)

    @property
    def retries(self) -> int:
        return len(self.retry_reasons)


def start_point(question: str) -> tuple[str, tuple[float, float]]:
    """Coordinates given in the question, or the default start point."""
    if m := COORDS.search(question):
        lat, lon = float(m.group(1)), float(m.group(2))
        return f"{lat}, {lon}", (lat, lon)
    return DEFAULT_START_NAME, DEFAULT_START


def make_agent(start_name: str = DEFAULT_START_NAME, start: tuple[float, float] = DEFAULT_START) -> Agent:
    return Agent(
        model=OllamaModel(host=OLLAMA_HOST, model_id=MODEL_ID),
        tools=[find_autumn_trees, get_weather, build_walk],
        system_prompt=SYSTEM_PROMPT.format(
            language=LANGUAGES[walk_lang()], start_name=start_name, lat=start[0], lon=start[1]
        ),
        callback_handler=None,
    )


def _tool_uses(agent: Agent) -> list[dict]:
    return [b["toolUse"] for m in agent.messages for b in m["content"] if "toolUse" in b]


def _walks(agent: Agent) -> list[dict]:
    """Results of the agent's valid build_walk calls (the tool is deterministic, so recompute them)."""
    walks = [build_walk._tool_func(**u["input"]) for u in _tool_uses(agent) if u["name"] == "build_walk"]
    return [w for w in walks if "error" not in w]


def _problem(message: str, walks: list[dict], start: tuple[float, float]) -> str | None:
    """Why the message can't be sent, or None if it is ready."""
    walks = [w for w in walks if haversine_m(*w["start"], *start) < 50]
    if not walks:
        return (
            f"you did not call build_walk with the starting point ({start[0]}, {start[1]}), "
            "so the stops and link are missing."
        )
    if not any(w["google_maps_url"] in message for w in walks):
        return "it does not contain build_walk's google_maps_url exactly."
    if not re.search(WIND_WORD[walk_lang()], message, re.I):
        return "the weather line does not give the wind."
    if len(message.split()) >= MAX_WORDS:
        return f"it is {len(message.split())} words long; keep it under 120 words."
    return None


def plan_walk(question: str) -> WalkResult:
    """Ask the agent for a walk; retry with the reason if the message is not ready to send."""
    start_name, start = start_point(question)
    agent = make_agent(start_name, start)
    message = str(agent(question)).strip()
    reasons: list[str] = []
    while (problem := _problem(message, _walks(agent), start)) and len(reasons) < MAX_RETRIES:
        reasons.append(problem)
        message = str(agent(RETRY_PROMPT.format(problem=problem))).strip()
    walks = _walks(agent)
    walk = next((w for w in walks if w["google_maps_url"] in message), walks[-1] if walks else None)
    return WalkResult(
        message=message, walk=walk, start=start, tool_calls=_tool_uses(agent), retry_reasons=reasons
    )
