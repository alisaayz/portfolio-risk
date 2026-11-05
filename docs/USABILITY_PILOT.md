# Facilitated usability pilot

Prepared November 5, 2026. Participant sessions are pending. This pilot is designed to find confusing labels and controls before deciding whether to run a larger experiment.

## Session setup

Use five to eight consenting adults who are interested in managing a stock or ETF portfolio. Include people with different levels of investing experience if available. Reserve about 15 minutes per session. Use demonstration holdings throughout. Record anonymous session IDs, task outcomes, and usability observations locally. Ask participants to avoid sharing names, account details, or personal positions.

Start the opt-in comprehension pilot and open the study page on the facilitator's computer. The usual practice page is useful for facilitator rehearsal.

```bash
.venv/bin/python -m scripts.serve_portfolio_app --record-pilot --port 8766
```

Use [the local study](http://127.0.0.1:8766/study) before showing the main dashboard. Open a new independent browser session for each participant and allow one assignment per person. Read the consent text aloud if helpful. The application records the assigned format, answers, timing, and completion status after consent. [Comprehension pilot guide](COMPREHENSION_PILOT.md)

## Facilitation prompts

Say that the task is to evaluate the interface. Ask participants to think aloud. Give them a chance to act before offering assistance. Mark an outcome as independent, assisted, or unfinished. Note the first action, hesitation, and words they use to explain the result.

| Task | Prompt | Evidence of independent completion |
| --- | --- | --- |
| Interpret the report | “Which holding contributes most to volatility? How is that different from its portfolio weight?” | Identifies AAPL's risk share and explains that the two percentages describe different things. |
| Preview a constrained change | “Keep AAPL at its current weight and move at most 10% of the portfolio. Show how the scenario affects estimated volatility and drawdown.” | Sets the lock and budget, previews weights, and identifies the two before-and-after estimates. |
| Check a replacement | “Clear the lock. Set a 10% volatility reference and screen a swap of 10% of the portfolio out of AAPL. Open one qualifying comparison.” | Uses the matching candidate screen and explains the resulting estimate and target status. |

The formal comprehension questions come before these tasks, so the facilitator does not teach the answers. If a participant interprets the 10% volatility reference as a maximum possible loss, record the misunderstanding and correct it during the debrief. Ask which label or number they relied on.

## Readout

Use the descriptive SQL summary for the recorded comprehension sessions.

```bash
.venv/bin/python -m scripts.study_pilot
```

Summarize the observed problems by task, the number of participants who encountered each problem, and the effect on task completion. Prioritize misinterpretation of risk, blocked tasks, then hesitation. Separate observed behavior from hypotheses about its cause. Use the findings to revise labels or flow and decide whether recruitment for a powered experiment is feasible. The small pilot supports usability observations. A later confirmatory study requires its own cohort and registered design. [Report experiment](REPORT_EXPERIMENT.md)
