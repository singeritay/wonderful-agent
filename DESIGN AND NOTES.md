## Airport Investment Intelligence Agent
A chat agent that helps analysts spot US airports worth investing in. You ask things like
"Compare LAX and Santa Ana congestion" or "What share of Anchorage's flights are long-haul?",
and it answers with real flight data and explains how it got there.
## The project is made of several parts:
### API - the Data Access level
We're using 2 APIs for the scope of the project.
The first one is for flights data. It returns us all the relevant data about flights, per airport.<br/>
We're using it for caclulating congestion and long haul flights counting.<br/>
We cache the results per airport per day to reduce API calls and make the query run faster.
<br/>
The second one is for airports data. This is not an official API (I could'nt find a good and available API that has all the data). This part queries a CSV file (which is updated) and treats it like it was an API, while caching the CSV per day in a `data/` folder.
<br/>

### Settings
Keeps a fairly small amount of settings, regarding both "business"/"product" decision, and some running configurations. (for simplicity the API URLs are stored in the API's files)
<br/>

### Analytics
This is the core of the project's data part. This part is responsible for querying and calculating the data relevant for answering the agent's questions.
Made of three parts:
- `reports.py` describes the output formats of the queries.
- `metrics.py` is responsible for the actual calculations.
- `airport_analyzer.py` is responsible for managing the questions and answers for a specific airport. Uses `metrics` for calculatios and `reports` for the output format.

### Agent
Fairly small module with a basic `agent.py` mechanism that uses Gemini LLM model, while using tools exposed by `mcp_server.py`. <br/>
The agent is accessible through a minimalist streamlit website (`ui.py`).

## Calculations & Ranking
I've decided to calculate the score and the basic metrics deterministically. <br/>
This allows the agent to decide by itself what metrics it should gather, and the base its ranking on any metric, rather than pre-chosen metrics. <br/>
In an earlier stage I did expose a ranking tool, but I wanted to allow as flexible as possible. I think both approaches are possible and good. I chose to simplify things while allowing more versatility.

## Where AI is used, and where it isn't

- **Deterministic (Python):** fetching data, counting flights, capacity, utilization, congestion
  level, long-haul counts. Same data in, same numbers out, covered by unit tests.
- **AI:** understanding the question, resolving names ("Santa Ana" to KSNA), choosing
  tools, comparing and ranking airports from the reports, working out percentages, and
  explaining the answer with its assumptions.


## Assumptions and tradeoffs
1. Passengers: We're assuming all flights are full - no way to figure out passengers occupation. The analysis is flight-based (movements), not passenger-based.
2. Scope: US large and medium airports from OurAirports. Small airports, heliports and
   seaplane bases are excluded.
3. Capacity: Airport capacity is calculated as open runways x 20 flights per runway per hour. Closed runways and helipads are excluded. This ignores runway configuration (parallel vs. crossing), weather, ATC procedures, gates and terminal size.
4. Airports are open 24/7. this is relevant for calculating the average congestion per hour.
5. Long-haul = a flight longer than 5 hours, measured from OpenSky's firstSeen/lastSeen
    timestamps
6. Unmet demand can't be observed directly - flights that didn't happen aren't in any data. The proxy is observed peak traffic compared with practical and theoretical capacity.
7. Limit of 10 airports per request of the agent. This limit prevents too many calls to the flights API (which is limited). There are a couple of solutions for it:
- A: Move to a deterministic caclulation that reduces the amount of calls to the API (my favorite, existed in earlier version) <br/>
- B: Pre-filter candidates cheaply by runway count before fetching any flights. <br/>
- C: Accept slower answers and rate-limit risk
8. A fresh MCP connection per chat turn in the Streamlit UI, with Gemini's chat history
   carried between turns in st.session_state. On one hand it's simple and robust with Streamlit's rerun-the-whole-script model. The minus is a small overhead each turn (subprocess start and tool listing).


## Running it

```
uv sync
uv run airports-agent                        # chat UI in the browser
uv run python -m airports_agent.agent.agent  # chat in the terminal
uv run pytest                                # tests
```

Needs `GEMINI_API_KEY` in `.env`. OpenSky credentials (`OPEN_SKY_CLIENT_ID`,
`OPEN_SKY_CLIENT_SECRET`) are optional but give a higher rate limit.
