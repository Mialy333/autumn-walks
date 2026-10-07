"""Spike: does Gemma 4 E2B (Ollama) call a tool correctly through Strands Agents?"""

import time

from strands import Agent, tool
from strands.models.ollama import OllamaModel

PROMPT = "Should I go for a walk in Paris this afternoon?"
RUNS = 3

calls: list[str] = []


@tool
def get_weather(city: str) -> str:
    """Get the current weather forecast for a city.

    Args:
        city: Name of the city.
    """
    calls.append(city)
    return f"{city}: 17°C, partly cloudy, light breeze, 10% chance of rain this afternoon."


def run_once(i: int) -> dict:
    calls.clear()
    model = OllamaModel(host="http://localhost:11434", model_id="gemma4:e2b")
    agent = Agent(model=model, tools=[get_weather], callback_handler=None)
    start = time.perf_counter()
    result = agent(PROMPT)
    latency = time.perf_counter() - start
    row = {"run": i, "tool_called": bool(calls), "args": list(calls), "latency_s": round(latency, 2)}
    print(f"[run {i}] tool_called={row['tool_called']} args={row['args']} latency={row['latency_s']}s")
    print(f"         answer: {str(result).strip()[:200]!r}")
    return row


if __name__ == "__main__":
    rows = [run_once(i) for i in range(1, RUNS + 1)]
    print("\n| Run | Tool called | Argument(s) | Latency (s) |")
    print("|-----|-------------|-------------|-------------|")
    for r in rows:
        print(f"| {r['run']} | {r['tool_called']} | {', '.join(r['args']) or '-'} | {r['latency_s']} |")
