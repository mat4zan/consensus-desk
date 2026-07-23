# Consensus desk

Aggregates probability estimates for a tracked set of questions from prediction
markets, forecaster platforms, and bookmakers. Runs unattended on GitHub Actions,
keeps a full history, and scores each source on its own record.

The design rule throughout: **the pipeline is dumb, the config is expressive.**
Adding a source is a new file plus a config line. Changing how anything is
weighted, pooled, corrected, or alerted is a config edit, not a code edit.

---

## Setup

```bash
git clone <your-repo> && cd consensus-desk
pip install -r requirements.txt

python run.py collect --tier all
python run.py pool
python run.py digest
```

Open `dashboard/index.html` in a browser, or serve it:

```bash
cd dashboard && python3 -m http.server 8000
```

### Deploying

1. Push to a GitHub repo.
2. Settings → Pages → Source: **GitHub Actions**.
3. Settings → Secrets → Actions, add:
   - `ANTHROPIC_API_KEY` — optional, for the disagreement explanations
   - `ODDS_API_KEY` — optional, for bookmaker lines
   - `METACULUS_TOKEN` — optional, for the Metaculus forecaster source
     (the public API now returns 403 without one)
   - `KALSHI_ACCESS_KEY_ID` + `KALSHI_PRIVATE_KEY` — optional, for Kalshi
     prices. The public API strips quotes; live prices need an RSA-signed
     session. The collector is read-only (market data only, never trades).
   - `FRED_API_KEY` — optional, for FRED-backed resolution oracles (Layer 2).
     Free from fredaccount.stlouisfed.org; Yahoo-backed oracles need no key.
4. Settings → Actions → General → Workflow permissions: **Read and write**.

It runs itself from there. The SQLite file is committed back to the repo on
every collect, so you get version history of the data for free.

---

## Refresh cadence and what it costs

Polling everything at the same interval wastes your tightest budget on your
slowest data. Sources are tiered by how fast they actually move:

| Tier | Sources | Interval | Constraint |
|---|---|---|---|
| markets | Polymarket, Kalshi | 6h | none meaningful — public APIs, generous limits |
| forecasters | Metaculus, Good Judgment | 24h | none, but medians move on human timescales; hourly polling is wasted |
| bookmakers | Pinnacle, Betfair | 24h | **the binding constraint** — Odds API free tier is 500 calls/month |
| commentary | RSS, analyst feeds | weekly | LLM token cost |

At 20 topics this is roughly 2,400 market calls and 600 bookmaker calls a month.
Markets are free; bookmakers will exceed the free Odds API tier, so either
trim the bookmaker topic list or move to a paid tier.

GitHub Actions: ~30s per run, ~4 runs/day, so ~60 minutes/month against a
2,000-minute free allowance for private repos (unlimited for public).

**Compromises of polling more often than daily:** essentially none on cost.
The real cost is noise — 6h intervals will surface intraday wobble that isn't
signal. This is handled two ways: `min_delta_to_record` suppresses writing rows
when nothing moved, and alert thresholds are set on 24h/7d windows rather than
on the collection interval. Collect often, alert rarely.

**Compromises of polling less often than daily:** you lose the ability to
attribute a move to a news event, and `move_24h` alerts stop working. Daily
is the floor for the tool to be useful.

---

## Tuning

Everything lives in `config/settings.yml`.

### Pooling

```yaml
pooling:
  method: logodds     # logodds | linear | geometric
  extremize: 1.2
```

Averaging probabilities directly produces systematic underconfidence — individual
forecasters hedge toward the middle, and averaging preserves that hedge. Pooling
in log-odds space and then extremizing corrects for it. Set `method: linear` and
`extremize: 1.0` to see how much difference this makes on your own data; on the
worked example in `tests/`, it's about 4 percentage points.

`extremize` above 1.5 is manufacturing confidence you don't have. The
1.1–1.3 range is what the Good Judgment Project literature supports.

Extremization is skipped automatically when only one source is present — with
no averaging there's no hedge to correct.

### Weights

```yaml
weights:
  strategy: hybrid    # fixed | brier | hybrid
  min_resolved: 30
```

`fixed` uses the numbers you set. `brier` derives them entirely from each
source's historical accuracy. `hybrid` — the default — uses fixed weights until
you have `min_resolved` resolved questions, then blends toward Brier-derived.

The multiplier is capped at 0.3x–2.0x of base, so no single source can run away
with the pool on a lucky streak.

Check progress with `python run.py score`.

### Correlation

```yaml
correlation:
  damping: 0.6
  clusters:
    real_money_markets: [polymarket, kalshi]
```

Polymarket and Kalshi on the same event are not two independent opinions — they
arbitrage against each other. Counting both at full weight double-counts one
view. Each cluster member's weight is scaled by `1 / n_present ** damping`.
Set `damping: 0` to disable.

### Bias correction

Real-money venues overprice low-probability outcomes — punters buy lottery
tickets and the price reflects that demand, not the true rate. Sub-threshold
probabilities from market sources are shrunk toward zero.

Bookmaker overround is stripped with Shin's method by default, which accounts
for insider money rather than assuming the margin is spread evenly across
outcomes. `method: proportional` for the naive version.

### Alerts

```yaml
alerts:
  move_24h_pp: 5.0
  source_spread_pp: 20.0
  cooldown_hours: 24
```

Four kinds, deliberately kept separate rather than collapsed into one severity
score, because they mean different things:

- **move_24h / move_7d** — something happened. The 7d alert is suppressed when
  24h already fired on the same topic, since the week's move is that day's move.
- **spread** — sources disagree. Usually a resolution-criteria mismatch, not a
  genuine difference of opinion. Check the criteria notes before reading it as signal.
- **volume_divergence** — volume spiked, price didn't. Someone is accumulating.

If you're getting too many alerts, raise the thresholds rather than turning
alerts off. A tool you ignore is worse than one that's quiet.

---

## Topics

`config/topics.yml`. The `resolution` field is canonical — it is *your*
definition of the event. Each source mapping asserts that source's criteria are
close enough.

Where they aren't, write a `criteria_note`:

```yaml
metaculus:
  id: 12345
  criteria_note: >
    MISMATCH: requires formal declaration, not observed interdiction.
    Expect this source to sit structurally lower during escalation.
```

The note surfaces in the disagreement panel, so you don't rediscover the same
mismatch every time the spread widens. This is the single highest-value field
in the config — question matching is the hardest unglamorous problem in the
whole system.

`review:` dates force periodic re-examination. Questions decay: criteria get
amended, markets go illiquid, the situation makes the question moot.

### Discovery

```bash
python run.py discover
```

Scans sources for untracked questions above the volume threshold and queues them.
Nothing is auto-promoted — the weekly digest lists candidates and you triage.
Suggested split: ~15 standing questions from your own analytical frame, ~5 slots
rotating from discovery.

---

## Adding a source

```python
from .base import Collector, Quote, register

@register
class MyCollector(Collector):
    name = "mysource"
    tier = "markets"

    def fetch(self, source_cfg: dict) -> Quote | None:
        r = requests.get(...)
        return Quote(probability=p, volume_usd=vol, raw={...})
```

Add a weight in `settings.yml`, reference it in a topic's `sources` block. Done.
Nothing in `core/` changes.

Return `None` when there's no usable data — an illiquid market, a closed
question, a missing ID. Returning `None` is not an error; raising is. A missing
source is recoverable; a wrong number silently entering the pool is not.

---

## The LLM's role

Extraction and explanation only. It never produces a probability that enters
the pool — this is enforced structurally in `core/explain.py`, which can only
return text, not by prompt discipline alone.

The model has no calibration and will anchor on whichever source is loudest.
It's given the numbers as fixed inputs and asked only to account for them.

Explanations only run when spread exceeds `explain_when_spread_above_pp`, which
keeps token cost near zero on quiet days.

---

## Commands

```
run.py collect --tier {all,markets,forecasters,bookmakers,commentary}
run.py pool                              # aggregate, alert, write snapshot
run.py digest                            # markdown summary
run.py discover                          # queue untracked candidates
run.py score                             # source calibration table
run.py resolve --topic ID --outcome 0|1  # record an outcome
```

Resolutions are what make calibration possible. Set a calendar reminder for
each `expiry` date, or you'll have a year of history and no way to score it.

---

## Known limits

- **Question matching is manual.** Two platforms with the same headline question
  usually have different resolution criteria. There's no automated fix; the
  `criteria_note` field is the mitigation.
- **Thin markets produce noise.** The liquidity filter helps but is crude.
- **30 resolved questions is a long wait.** Until then weights are your priors,
  not evidence. Consider seeding with short-horizon questions purely to
  accumulate resolutions faster.
- **Bookmakers are weak outside sports and elections.** They're on the board as
  confirmation, not as a leading source.
