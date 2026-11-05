# Report comprehension pilot

Updated November 4, 2026.

UX-P01 asks whether a chart helps readers interpret a portfolio risk report. Both formats display the same historical facts, assumptions, and three questions. The visual format adds a bar chart that switches between capital weight and share of portfolio volatility. Readers can consult the report while answering. The tasks measure interpretation with the report available.

## Demonstration and scoring

The fixed demonstration uses accepted DS-002 data for a 30% AAPL, 20% BND, and 50% SPY portfolio. Annualized historical volatility is 11.29% over the 252 trading sessions ending November 3, 2026. The largest observed decline is 26.94% over the replay from January 2, 2020 through November 3, 2026. The 10% comparison reference is an example. The replay assumes daily rebalancing at fixed weights and excludes trading costs and taxes.

Three questions ask readers to identify the largest volatility contributor, compare the reported volatility with the example reference, and interpret annualized historical volatility. The [study definition](../config/comprehension_pilot.json) preserves the source report identifier, exact inputs, wording, and answer key. Feedback is available after submission.

## Practice and consented recording

From the project directory, start the application and open [the local study page](http://127.0.0.1:8765/study).

```bash
.venv/bin/python -m scripts.serve_portfolio_app
```

Practice allows a reader to choose either format. Answers are discarded after scoring. For a facilitated pilot, explicitly start a separate instance and open [the local recording page](http://127.0.0.1:8766/study).

```bash
.venv/bin/python -m scripts.serve_portfolio_app --record-pilot --port 8766
```

After consent, the server assigns a report format with equal probability and saves the assignment for that session. The participant can submit all three answers or end early. Closing the page leaves the session unfinished. The facilitator should allow one session per participant and reserve practice attempts for separate reviewers. Session identifiers are anonymous browser identifiers, so the facilitator must prevent repeat participation across devices or tabs.

Recording stores the study definition and hash, anonymous identifier, format, timestamps, completion status, and scored answers in `private/comprehension-pilot.sqlite3`. The database is local and ignored by Git. Names, contact details, and personal holdings are outside the study form. If the report, questions, or interaction change materially, create a new study version before collecting more responses.

## Descriptive summary

```bash
.venv/bin/python -m scripts.study_pilot
```

| Metric | Definition |
| --- | --- |
| Primary task success | Number answering all three correctly divided by all assigned sessions in that format |
| Completion | Counts of completed, explicitly ended, and unfinished sessions |
| Critical misunderstanding | Count of completers who interpret historical volatility as the maximum possible loss |
| Completion time | Median elapsed seconds from assignment to submission among completers, including pauses |

The summary reads SQLite without modifying it and reports each study version and format separately. Unit tests use temporary databases. Browser verification exercised both practice formats, scoring, the chart switch, and early exit. Participant evidence is pending. Use a facilitated pilot to evaluate wording and interaction. The [report experiment brief](REPORT_EXPERIMENT.md) explains how to freeze a separate cohort, estimate sample size, analyze it, and review the product decision.
