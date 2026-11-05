# riskitnot Version 2 action plan

Planned November 5, 2026. Version 1 is preserved at `v1.0.0` on commit `d4eba345acf506ff3fb89c8583bc0bb1f5d9b02c`. The tag fixes the code, reports, and demo. The original captures, warehouse, and experiment artifacts remain local. The preserved DS-002 warehouse has SHA-256 `6dee162df4f560178d8a5ea55313898aba69e858857192c74425d804e498e404`. [Version 1](https://github.com/alisaayz/portfolio-risk/tree/v1.0.0) · [Reproduction guide](REPRODUCE.md)

## Product goal

Help a self-directed investor bring in a portfolio, identify a risk they care about, and make a defensible choice among keeping the portfolio, reweighting it, and reviewing a hypothetical replacement. A defensible choice respects the case's constraints and exposure goals, interprets historical evidence correctly, and identifies tradeoffs. Keeping the portfolio can be the correct answer.

Plan four two-week checkpoints for a local release. Participant access and data permissions can affect timing and scope. Broader screening, hosted deployment, and a claim of forecast superiority each have their own evidence requirements.

## 1. Establish the Version 1 baseline

The cases, rubric, and 30-path scripted baseline are complete. The scripted findings inform engineering priorities. Participant sessions and the observed user baseline are pending. [Scripted rehearsal](V1_SCRIPTED_REHEARSAL.md) [Facilitator protocol](V1_DECISION_PILOT.md) · [Participant cases](V1_PARTICIPANT_CASES.md) · [Baseline readout](V1_PILOT_BASELINE.md)

**Weeks 1–2.** Adapt the facilitator guide around a realistic decision. Ask participants to review a demo portfolio with a clear objective, explain volatility and loss in their own words, and choose whether to keep, reweight, or replace a holding. Include a case where a lower-volatility substitute violates the desired exposure and one where the evidence is inconclusive. Ask how participants handle this decision today and whether the tool changes it. [Version 1 facilitator guide](USABILITY_PILOT.md) · [Moderated usability testing](https://www.gov.uk/service-manual/user-research/using-moderated-usability-testing)

- Use five to eight consenting participants for the first round if available. Test Version 1 first and record anonymized observations.
- Define a rubric before sessions. Score independent completion and whether the participant makes a defensible choice for the stated constraints. Record time to first usable comparison, assistance, abandonment, and critical errors such as interpreting a historical target as a future loss limit.
- Compare with the participant's current workflow or a simple reference worksheet. Record which decisions the extra features change and whether the change improves the case outcome.
- Produce a baseline readout and prioritize recurring issues. Review Version 2 with a fresh group or use equivalent cases with counterbalanced order to limit learning effects. Report small-pilot counts and denominators as descriptive evidence. A causal improvement claim requires a separately powered study and frozen analysis plan. [Experiment design](https://www.microsoft.com/en-us/research/articles/patterns-of-trustworthy-experimentation-pre-experiment-stage/)

## 2. Make the first useful decision easier

**Technical checkpoint complete November 5, 2026.** The guided flow, two CSV formats, local draft, active settings, and standalone demo are implemented. All 30 archived decision paths match the Version 1 market-data results. The browser checks include keyboard interaction and a 390-pixel layout. Cross-window qualification and exposure filtering are part of checkpoint 3. [Guided workflow and verification](V2_GUIDED_WORKFLOW.md)

**Weeks 3–4.** Put portfolio entry, historical risk, and comparison in one guided flow. Keep one portfolio as the starting point and give “keep current” equal prominence in the decision summary.

- Add local CSV import for one documented format with ticker and weight, or ticker and market value. Preview the mapping, duplicate handling, totals, and unsupported holdings before applying it. Keep manual entry available. Test malformed files, partial imports, unknown symbols, totals, and cancellation.
- Add explicit local save, reopen, and delete for portfolio drafts. Show what is stored. Exclude account credentials and identifiers from the import. Direct brokerage integration remains a separate decision.
- Use a visible, documented default risk window. Show its date range, expose shorter-window sensitivity when it matters, and put manual numerical targets in advanced controls. Explain changes in percentages and percentage points. Keep the questionnaire separate from any numerical suitability score.
- Put the adjustment actions beside the risk result. Keep the target, exposure, move budget, and locks visible throughout. Check keyboard access, mobile layout, and common validation failures.
- Build a fresh-clone demo from clearly labeled synthetic fixtures or a redistributable dataset with documented rights. A reviewer should run one documented command and see the report and comparison without the author's captures or a provider account. Provide separate rebuild instructions for the actual research evidence.

## 3. Make the risk and replacement evidence harder to misuse

**Technical checkpoint complete November 5, 2026.** The dashboard shows historical downside, cost scenarios, bounded exposure evidence, and filtered window sensitivity. The 432-case development replay selected the simple shift as default. Complete underlying issuer overlap remains unknown. [Results and verification](V2_RISK_EVIDENCE.md)

**Weeks 5–6.** Expand the report and show where comparisons depend on assumptions.

| Critique | Version 2 work | Verification |
| --- | --- | --- |
| Volatility misses downside risk and overlapping exposures | Add historical downside deviation, a clearly dated loss scenario, and an exposure summary. Show fund look-through where dated source data are available. Label unknown overlap. | Reconcile metrics against hand calculations and an independent implementation. Check that users can distinguish historical downside measures from a forward probability of loss. |
| The replay assumes daily rebalancing without costs | Compare daily rebalancing with a specified less frequent schedule. Add turnover-based transaction costs and a wider-spread stress scenario. Report gross and net outcomes, trade counts, and tax assumptions separately. | Test the cash and holdings ledger. Check that zero costs reconcile with gross replay and that higher costs reduce net results on an identical trade path. Account-specific taxes need separate inputs and rules. |
| Qualification depends on the risk window | Compare 63-, 126-, and 252-session estimates. Test shrinkage covariance against sample covariance. Replace a single pass badge with stable, window-sensitive, above-target, and unavailable statuses. Show ranges and rank changes. Estimate paired uncertainty by resampling matched date blocks when coverage supports it. Display sample limitations separately from sensitivity across settings. | Freeze the status rule before testing. Reproduce the Version 1 demo's 13/9/6 qualification counts and verify that missing or conflicting evidence changes the label. [Covariance estimation reference](https://doi.org/10.1016/S0047-259X%2803%2900096-4) |
| A low-volatility substitute can change the purpose of the allocation | Ask which exposure the holding is meant to provide. Filter by allowed role, concentration, move budget, and available liquidity and fee evidence. Show reasons for exclusion and include keeping the original portfolio. | Test a case where a low-volatility candidate has the wrong role, plus locks, bounds, missing evidence, and no-match results. |
| The optimizer matched a simple move | Compare keep-current, the simple risk shift, and constrained optimization under matched constraints and costs across distinct portfolios and rolling dates. Report feasibility, realized downside, net outcomes, and turnover. | Predeclare when the optimizer adds enough benefit to display it. Use the simpler default if the more complex method fails that comparison. |

## 4. Strengthen provenance and publish the results

**Weeks 7–8.** Complete the comparison, audit the data contract, and publish a release readout.

- **Data integrity and freshness.** Distinguish searchable, price-available, structurally checked, spot-checked, and screen-eligible records. Replace the binary independent-check flag with counts, dates, source IDs, and gaps. Add a refresh dry run, snapshot age indicator, and provider-failure tests. Preserve quarantined observations. Require a second source with documented rights and independence where claims depend on it.
- **Candidate coverage and survivorship.** Show the screen's eligible count beside the discovery count. Expand only for candidates with verified identity, complete history, and dated exposure evidence. For historical strategy research, obtain point-in-time membership with delisted securities where feasible. Label any current-survivor analysis and limit conclusions to its sample.
- **Forecast evidence.** Preserve the frozen 2026 report as Version 1 evidence. Start a new prospective record with timestamped predictions before outcomes arrive. Predeclare simple trailing and exponentially weighted baselines, the minimum useful improvement, error and downside diagnostics, and the required number of new market dates under the chosen dependence assumptions. Compare on matched origins across distinct portfolios. Keep forecasts in research until that evidence threshold is met. Forward results can remain pending at the Version 2 dashboard release.
- **Public reproducibility and rights.** Have a reviewer run the demo from a fresh clone. Publish a manifest that separates software fixtures, demo inputs, and privately retained market evidence. Document software licensing and permitted provider uses, redistribution, and hosting. Keep the public demo on approved inputs. Public hosting of personal portfolios would need a separate review of authentication, storage, deletion, and operational support. [yfinance usage guidance](https://ranaroussi.github.io/yfinance/)
- **Product evidence and release.** Publish Version 1 versus Version 2 outcomes with counts and observed errors. Proposed formative targets are at least 80% independent completion of the scenario task, fewer assists, and zero observed cases of a participant interpreting a historical estimate as a guaranteed loss limit in the release round. Review every critical error before release. If participant access is delayed, label the result as a technical preview and leave user-benefit claims pending.

## Checkpoint deliverables

| Checkpoint | Deliverable |
| --- | --- |
| 1 | Version 1 decision-task baseline, rubric, and prioritized usability issues |
| 2 | CSV import, saved drafts, guided comparison, and a fresh-clone demo |
| 3 | Risk and cost replay, replacement filters, stability report, and simple-rule comparison |
| 4 | Version 2 decision readout, data-rights inventory, release checklist, and prospective forecast protocol |
