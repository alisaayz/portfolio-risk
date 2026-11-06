# Version 2 decision pilot

Protocol **UX-V2-01**, prepared November 5, 2026. This formative pilot measures whether participants can make and explain a portfolio decision in the Version 2 preview. The two fictional tasks, six-minute case limit, and core rubric match Version 1. [Participant task cards](V1_PARTICIPANT_CASES.md) · [Version 1 facilitator guide](V1_DECISION_PILOT.md)

## Setup

| Item | Use |
| --- | --- |
| Dashboard | Version 2 technical preview, tag `v2.0.0-preview.1`, at [localhost:8767](http://127.0.0.1:8767/). |
| Comparison dashboard | Version 1, tag `v1.0.0`, at [localhost:8765](http://127.0.0.1:8765/). |
| Evidence | Saved DS-002 prices through November 3, 2026. Start each case with AAPL 30%, SPY 50%, and BND 20%. |
| Session | One participant at a time, 20 to 25 minutes, with a stopwatch and a local copy of the session record. |

For the planned comparison, run the Version 1 pilot first, then recruit a fresh group for Version 2. Aim for five to eight consenting adults per version and record investing experience using the same broad categories. Alternate the A/B and B/A case orders within each group. Keeping each participant on one version avoids repeating the same task after they learn the answer. If only Version 2 runs, report that cohort on its own.

Use a clean browser session. Reset the demonstration and close advanced controls between tasks. Verify the November 3 cutoff and starting weights before the participant starts. The cases require the saved market-data dashboard because Case B uses the replacement screen. [Launch instructions](REPRODUCE.md)

## Facilitator script

1. Say, “We’re testing the dashboard. You can stop at any point. We’ll use a fictional portfolio. May I take anonymous notes about what you try and where you get stuck?” Record consent before taking notes and ask participants to keep names, account details, and personal holdings out of the session.
2. Give the participant the task card and ask how they would approach the decision today. Start the timer when the task prompt ends and the dashboard is ready. Observe the first action, settings used, and any mistakes. Use neutral prompts such as “What are you looking for?”
3. Stop the timer at the first usable comparison or an evidence-based decision to keep the current portfolio. Allow one navigational cue after three minutes and mark any completion after that cue as assisted. Mark the task unfinished if the participant has not reached a usable decision after six minutes.
4. Ask, “What would you choose and why?” Then ask, “What does that volatility estimate tell you about a future loss?” Record their words before discussing the answer. In Case B, give the 63-session follow-up only after recording the primary decision and stopping the timer.
5. Ask what they would normally use for the decision and which part of the dashboard helped or slowed them down. End the session by explaining the expected evidence.

## Facilitator answer key

Use the Version 1 three-point rubric for each case. Award one point each for respecting the constraints, using the relevant historical evidence, and explaining the decision and its limits. A defensible decision earns all three points. A supported keep-current decision qualifies when the participant explains the evidence. [Full rubric](V1_DECISION_PILOT.md#facilitator-scoring-key)

- **Case A.** At 252 sessions, lock AAPL at 30%, set 10.60% as the volatility target, and cap the move at 10%. The default Simple shift and the Constrained optimizer both produce AAPL **30.00%**, SPY **41.55%**, and BND **28.45%**. The proposal moves **8.45%** of portfolio value. Estimated volatility falls from **11.29% to 10.60%** and historical drawdown changes from **−26.94% to −24.34%**. The target describes the estimate from the saved data.
- **Case B.** Set the replacement to 10% of the portfolio from AAPL and set intended exposure to **Equity ETF**. At 252 sessions, all four equity ETF candidates exceed the 10.00% target. Keep the portfolio or defer the change. IEF has **9.59%** estimated portfolio volatility but fails the exposure filter. At 63 sessions, all four equity ETF candidates pass the selected-window target. QQQ moves from **11.00% to 8.14%**. The four candidates still have a sensitive rating because Version 2 checks all six combinations of window and covariance estimator. Use the follow-up to check whether the participant distinguishes the selected-window estimate from the overall rating.

Record completion separately from decision quality. Flag a critical misunderstanding if a participant treats historical volatility as a ceiling on future losses or believes a replacement satisfies the case despite failing its equity exposure requirement. The numerical answer key was verified against the local API. A new browser rehearsal is pending.

## Anonymous session record

Copy the table into the ignored local `private/` folder for each consenting session. Use an ID such as P01. Complete the record before discussing the answer key.

| Field | Record |
| --- | --- |
| Session ID, date, version, and case order | |
| Consent to anonymous notes and broad experience band | |
| Case A choice before and after using the dashboard, with reasons | |
| Case A completion, seconds if completed, cue if given, score out of 3, and critical errors | |
| Case B choice before and after using the dashboard, with reasons | |
| Case B completion, seconds if completed, cue if given, score out of 3, and critical errors | |
| Case B explanation of the 63-session follow-up | |
| First hesitation, observed action, and facilitator interpretation | |
| What the participant normally uses and what helped or slowed them down | |

## Readout

Report independent, assisted, and unfinished attempts as counts over assigned attempts for each version and case. Report defensible decisions using the same denominator. Show the median time among completers with the number who completed and the number who did not. Count each kind of critical misunderstanding separately and keep the 63-session follow-up outside the primary score. Use aggregate results in any public readout.

Check whether at least **80%** complete each Version 2 case independently. Compare the share needing a cue when a Version 1 cohort is available. Review every critical error, with a target of zero observed future-loss-limit misunderstandings. Describe cohort differences and treat the comparison as formative evidence. Participant sessions and measures are pending. [Version 2 action plan](V2_ACTION_PLAN.md#4-strengthen-provenance-and-publish-the-results)
