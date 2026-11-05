# Version 1 decision pilot

Protocol **UX-V1-01**, prepared November 5, 2026. This is a formative usability pilot for the first Version 2 checkpoint. It measures whether a person can use the Version 1 dashboard to make and explain a choice in a fictional portfolio case. The existing chart-comprehension study is a separate experiment. [Version 2 plan](V2_ACTION_PLAN.md) · [Version 1 release](https://github.com/alisaayz/portfolio-risk/tree/v1.0.0)

## Prepare the session

- Recruit five to eight consenting adults who manage, or expect to manage, a stock or ETF portfolio. Include different levels of investing experience if possible. Report the number and type of participants recruited. The project owner can rehearse the protocol. Record an owner rehearsal separately from the participant baseline.
- Reserve 20 to 25 minutes. Use the tagged Version 1 dashboard at `http://127.0.0.1:8765/`, the November 3, 2026 DS-002 snapshot, and demonstration holdings. The facilitator verifies the tag and loaded snapshot before the session. Use a fresh demo tab for each session. [Launch instructions](REPRODUCE.md)
- Share the [participant task cards](V1_PARTICIPANT_CASES.md). Keep the scoring key and numerical answers with the facilitator. Alternate case order A/B and B/A by session. Reset the demo and close the advanced controls between cases.
- Ask permission before taking anonymous notes. Explain the session purpose, voluntary participation, and what will be recorded. Use session IDs such as P01. Ask participants to avoid names, account information, and personal holdings. Keep individual notes locally in the ignored private folder. Publish aggregate observations only.
- Use the regular dashboard in practice mode. Record timings and observations in the template below. The standalone comprehension study uses a different task and cohort. [Moderated usability guidance](https://www.gov.uk/service-manual/user-research/using-moderated-usability-testing)

## Facilitate consistently

1. Before showing the dashboard, ask how the participant would compare a portfolio change today. Present the first case and ask for their initial decision and the evidence they would want. The case provides objectives and constraints. Keep the verified outputs hidden at this stage.
2. Open the Version 1 dashboard and let the participant work. Start the timer when the case prompt ends and the dashboard is ready. Stop it at the first usable comparison or supported keep-current decision. Keep a case limit of six minutes. Record the first action, mistakes, and exact point of hesitation.
3. Use neutral prompts such as “What are you looking for?” If needed, give one navigational cue after three minutes, record it, and mark the result assisted. A usable comparison respects the case's rules and uses the stated historical window. Mark a case unfinished if the participant cannot reach one within six minutes.
4. After each case, ask what they would choose and why, whether the tool changed their initial choice, and how confident they are. Ask what the volatility target tells them about a future loss. Record the answer before correcting a misconception. For case B, then ask for the 63-session check and record whether they interpret the difference appropriately.
5. Ask which existing tool or method they would use for this decision and where the dashboard added friction or evidence. Record the observed choice and their explanation separately from the facilitator's interpretation.

The before-and-after choice is a descriptive within-session observation. The participant sees more information after opening the dashboard. A change in choice can reflect that information, learning, or the interaction with the facilitator.

## Facilitator scoring key

Score completion and decision quality separately. Completion is **independent**, **assisted**, or **unfinished**. Score each case's final choice using the three criteria below. Each criterion earns one point when the participant gives the reason or supporting evidence. A defensible decision earns all three points. Use the shorter-window follow-up as a separate diagnostic.

| Criterion | Case A | Case B |
| --- | --- | --- |
| Respects the constraints | Keeps AAPL at 30%, uses only existing holdings, and moves at most 10%. | Requires an equity ETF, keeps the remaining allocations fixed, and uses the 10% swap. |
| Uses the relevant evidence | Finds or explains the feasible 252-session reweighting and its estimated risk relative to 10.60%. | Uses the 252-session results and recognizes that every qualifying candidate fails the exposure constraint. |
| Explains the decision and its limits | Compares the reweighted scenario or explains why they would keep the current allocation despite the feasible option. Explains that the figures describe past data. | Keeps the portfolio or defers the replacement under the stated rule. Explains why a bond ETF or single stock is an unsuitable choice for this case. |

Record a **critical misunderstanding** when someone treats the target as a guarantee or ceiling on future losses, or chooses an exposure-violating replacement while believing it satisfies the stated rule. Record both kinds separately. An independent completion can still contain a critical misunderstanding. Treat a 63-session pass as sensitivity evidence. The case's decision rule still uses 252 sessions.

### Verified Version 1 outputs for the facilitator

- **Case A.** The 252-session baseline is **11.29%** volatility and **−26.94%** historical drawdown. The AAPL lock and 10.60% target yield AAPL **30.00%**, SPY **41.55%**, and BND **28.45%**. The scenario moves **8.45%** of portfolio value and has **10.60%** volatility and **−24.34%** drawdown. The exact solver output meets the target before display rounding.
- **Case B.** Six candidates meet the 10% target at 252 sessions. Their labels describe two individual stocks and four bond ETFs. No equity ETF passes. XOM is the lowest estimated volatility at **8.95%**, and IEF shows **9.59%**. Neither fits this case's exposure rule. At 63 sessions all 13 pass, including QQQ at **8.14%**, versus **11.00%** at 252. The original portfolio is already at **8.33%** on the shorter window. The result depends on the window and does not change the primary case rule.

The outputs were checked through the local Version 1 API and rehearsed in the browser with demonstration inputs. They are the task answer key. Participant performance is recorded separately. [Candidate screen](PORTFOLIO_CANDIDATE_SCREEN.md)

## Anonymous session record

Copy this table into a local note per participant. Complete the record before discussing the answer key.

| Field | Record |
| --- | --- |
| Session ID, date, and case order | |
| Investing experience band and prior workflow | |
| Consent to anonymous notes | |
| Case A initial and final choice with reasons | |
| Case A time, assistance, completion, rubric score, and critical errors | |
| Case B initial and final choice with reasons | |
| Case B time, assistance, completion, rubric score, and critical errors | |
| Case B interpretation of the 63-session result | |
| First hesitation, recurring friction, and observed effect | |
| What the participant says the dashboard added | |

[Baseline readout](V1_PILOT_BASELINE.md)
