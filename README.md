# autumn-walks

Plans a short autumn walk in Paris past trees with strong autumn colour (ginkgo, sweetgum, Persian ironwood, maple, oak), using a small local model.

A [Strands Agents](https://strandsagents.com) agent running **Gemma 4 E2B** on [Ollama](https://ollama.com) uses three tools:

- `get_weather`: this afternoon's temperature, rain probability and wind, from [Open-Meteo](https://open-meteo.com) (no API key needed)
- `find_autumn_trees`: a varied selection of trees around a point, rarer genera first, one per street
- `build_walk`: picks 3 to 5 of those trees for a loop under 3 km (about 40 minutes) and computes every distance and the Google Maps link in Python, so the model never has to calculate them

Terminal only for now.

## Run it

Needs [uv](https://docs.astral.sh/uv/) and [Ollama](https://ollama.com) running locally.

```bash
ollama pull gemma4:e2b
uv sync
uv run python try_walk.py
```

`try_walk.py` asks for a 40-minute walk from Opéra Garnier three times. It logs each tool call, the loop length and the latency, checks the answers, and saves them to `walks/test-run-N.md`.

## Data

The tree data comes from the Paris open data dataset ["Les arbres"](https://opendata.paris.fr/explore/dataset/les-arbres/) (Ville de Paris, [ODbL](https://opendatacommons.org/licenses/odbl/)). `data/trees.sqlite` holds 2,445 trees from 5 genera in the 1st, 2nd, 8th, 9th and 17th arrondissements, derived from it under the same licence.

To rebuild the database, download the CSV export to `data/raw/` and run the loader:

```bash
curl -o data/raw/les-arbres.csv "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/les-arbres/exports/csv"
uv run python -m autumn_walks.load_trees
```

Weather data by [Open-Meteo](https://open-meteo.com) (CC BY 4.0).

## License

Code: [MIT](LICENSE). Tree data: ODbL, see above.
