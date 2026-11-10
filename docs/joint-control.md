# Joint adaptive control — v0.21

## What the review changed

The earlier implementation chose an ideal heat/DHW schedule and then simulated offsets against it. Reserve overrides and native behaviour could change the meaning of that first schedule. Its loss-derived emitter model could also predict a 49°C supply from a machine observed near maximum frequency at about 35°C. Large preferred-temperature/terminal penalties could overpower high electricity prices even after the minimum was lowered to 18°C.

The live predictor now uses one joint command search (`joint.py`). The earlier pure schedulers remain for legacy regressions/demo compatibility; they do not select live commands. The circuit diagram is unchanged.

## Measured-response corrections — v0.23

The peak trace showed that the room-average prediction could be accurate while upstairs cooled faster than predicted. Valid 30-minute windows now learn the signed half-difference change per hour during space heating and coasting separately. Initial rates are zero. The measured rate is bounded to ±0.3°C/h; its forecast correction approaches twice that rate over a two-hour time constant rather than extrapolating indefinitely. The correction is added to one room and subtracted from the other, preserving the house average. This models observed divergence, not independent hydraulic energy allocation or a fully identified two-zone plant. Native circuit-priority rules are unchanged.

Each heat-lag bank persists its observation timestamp. On a short restart/gap, the remaining heat proxy decays assuming no unobserved input. No fitting window bridges the gap. After more than six hours, or without a trustworthy timestamp, initial heat uses the current measured input. Old stores use the last learning timestamp as an approximate migration anchor. This does not reconstruct unobserved heating.

Native start learning now requires a close negative degree-minute bracket across an off-to-space-heating transition, without an offset/supply-target jump. A median of up to nine brackets replaces the old EWMA. DHW transitions and jumps over 120 degree minutes are excluded. A fresh native compressor-start number takes precedence. Legacy averages with no validated brackets migrate to the initial −60 prior, not a claim that every F750 uses that setting. Fresh observed/native thresholds replace it.

A fresh previous command timeline is also re-simulated from the new initial state and competes under the same cost/comfort objective. Mandatory reserves can override it, and newly known prices, changed room response or better alternatives can replace it. Beyond its old horizon, its candidate continues with the dynamic policy. Strategic preferred temperature varies continuously with price position over the next eight known hours; there is no binary median switch between minimum and preferred temperature. Fixed coasting alternatives remain candidates, with live comfort/reserve protections. None of these changes guarantees a globally optimal schedule.

## Peak-search correction — v0.21.1

A live investigation exposed a cheaper feasible peak-avoidance schedule which the prefix-ranked beam discarded. More calculation time did not recover that trajectory: the search had already pruned it. The predictor now evaluates four complete price-aware rollouts before the beam search, and selects among all completed schedules using the same comfort-first objective. Strategies use known later prices and simulated warmth in transit, not fixed afternoon clock windows. They retain native timing, DHW reserve and 06:00 policy. A strategic rollout is a candidate, never an instruction to coast regardless of comfort.

Beam diversity also distinguishes compressor/charging/pending state and the current offset, and retains both degree-minute frontiers. The morning-deadline lookahead no longer shares a variable overwritten by simulation substeps. Budget accounting covers all candidate searches; at low remaining budget a complete candidate is retained. The existing 12-second soft budget and 30-second outer timeout are unchanged.

Diagnostics now include the full quarter-hour forecast, command timeline, candidate costs/objectives, selected strategy, total expansions and local search runtime. These support future replay without credentials. Snapshot tests are offline counterfactuals: REST snapshots can differ from the exact readings used when the original plan was generated. Model cost reductions are not measured household savings.

## Commands, dynamics and objective

The search jointly considers every supported primary offset and Normal/Economy choices. Actual current settings are held until the next permitted update. Future command blocks are at least 16 minutes apart, with the same durable live write gate rechecked at application. A C2-only update cannot consume the budget during an explicitly planned hold. Quarter-hour price/power output is duration-weighted across command boundaries; current requested settings come from the command timeline, not the averaged graph point.

The model simulates native supply error, degree-minute backlog, compressor start/stop state, the reported frequency bounds, auxiliary limits, delayed heat delivery and house response. The fitted 15-minute native-response map is interpolated consistently over shorter steps, rather than repeatedly applying a 15-minute map every five minutes and adding an extra actuator lag. A running compressor retains its minimum frequency until the simulated native stop condition; a zero requested heat proxy cannot magically stop it while backlog remains.

Near-capacity space-heating observations calibrate effective emitter conductance on the same estimated heat basis as the house learner. Calibration persists and is not counted repeatedly from the same cloud observation. Initial and observed calibrations are labelled. Excess supply requests beyond calibrated capacity incur a penalty; they cannot create heat beyond the compressor/auxiliary limits.

Actual comfort/reserve excursions are ranked ahead of energy cost, including when prices are negative. Within the allowed range, the preferred room temperature has a modest soft cost. End-of-horizon warmth is valued as energy at a representative known tail price/COP estimate; there is no hard requirement to end at 20°C and no arbitrary large 20°C terminal penalty. Both measured rooms are checked, using a common house response plus a learned, bounded differential response during space heating and coasting. A bounded margin reflects empirical model error and data coverage. Recovery trajectories are disclosed rather than labelled fully comfortable.

This is a finite beam search, not a proof of global optimality. It preserves hot/cold storage and Normal/Economy alternatives so delayed effects are not discarded merely because current room temperature has not changed yet.

## DHW and 06:00

Normal enables native charging; Economy deliberately defers it. The model uses learned DHW demand by hour, native start/stop thresholds and observed compressor fraction. Native threshold observations exclude starts immediately after deliberate Economy deferral and stops caused by switching to Economy. These commands are not evidence of the pump's own hysteresis thresholds.

House and DHW share one compressor: modelled space input is zero while DHW uses it. A Normal reservation may have zero charging when the tank is above its start threshold. Outside planned reservations, reserve/necessary-completion/morning protections still apply.

To avoid charging too early and then being unable to top up at 06:00, the search checks whether a tank above its start threshold can cool enough to restart in time. An explicit economic pause is allowed only while reserve is healthy, the tank remains below the native restart threshold with a margin, and no low-reserve or morning protection is active. The same pause permission is checked again by the live supervisor. It is not a blanket permission to interrupt any charge.

The daily goal is the learned Normal full level with 0.5°C tolerance, in HA's timezone, including DST. A live recovery flag persists until full is observed. Measured completion is recorded per local date, so ordinary later draw-off does not retrigger a missed-morning goal. Ordinary low-reserve protection always remains. An unreachable configured/native tank target and predicted morning shortfall are reported rather than invalidating all space-heating planning.

Native thresholds and hardware can still make 06:00 full charge unattainable; the integration cannot force Lux, change Normal presets, bypass protections or create compressor capacity. DHW auxiliary prediction is uncertain unless observed; the dashboard says “No inline heat predicted” rather than claiming a guaranteed compressor-only outcome.

## Learning and confidence

The house learner retains recursive identification of heat loss, effective capacity, gains and lag hypotheses. New checks reject opposing room jumps that would cancel in the average, stale defrost states are distinguished from fresh defrost, and water windows cannot bridge charging, outages or large tank discontinuities. Heating and cooling coverage are separate: cooling-only data does not claim identified heating response. Domestic physical guardrails bound implausible parameter ratios, while old valid stores remain readable and retain their underlying coefficients. Projection and error allowance are exposed.

Hourly DHW confidence is based on observed time, not fragment count. Partial starts/stops cannot inflate coverage simply by creating many small windows. Model confidence is heuristic and the error allowance is empirical, not a statistical accuracy guarantee. Learning starts from prior estimates immediately and never gates activation.

## Availability, budget and diagnostics

Published prices and hourly weather define the available horizon, up to 24 hours. Shorter continuous horizons are usable; no tomorrow price is invented and no six-hour minimum forces unnecessary late-day fallback. Stale/invalid sources still clear the active plan and use the configured preferred-temperature thermostat with Normal DHW. Paused state remains respected.

Near the calculation budget, the search switches to a simple complete-horizon continuation. It reports reduced search in diagnostics instead of discarding all work or applying an unfinished prefix. Executor cancellation remains cooperative. Results remain model predictions; Raspberry Pi runtime and real control performance need validation on the installation.

Download integration diagnostics for model confidence/coverage, emitter calibration, the selected command preview, planning budget/horizon metadata, morning completion and recent actual setting attempts. The large live forecast attribute is excluded from duplicate Recorder storage; forecast power history persists in the local accounting store.

## Validation and limits

Regression scenarios include expensive-now/cheap-later operation with 18°C vs 19°C minima; shifted prices; negative-price comfort limits; the reported saturated supply state; shared compressor allocation; Normal permission without charging; a reserve charge/pause/late-full sequence across DST; native top-up infeasibility; paused/inactive chart states; initial write holds; no-op write-budget handling; lower native tank ceiling; and completion after a soft computation deadline.

These are deterministic model tests, not measured savings or a verified simulation of the owner's complete heating system. Effective heat is still frequency-based, the outdoor heating-curve slope starts from an approximation, emitter calibration can be biased during transients, and the two rooms are not separately identified thermal zones. Fan/pump power is not included. Changing occupancy, defrost, unobserved shower demand, cloud timing and sensor faults can all change outcomes. The next tuning step should use observed operation and forecast error; there is no claim that the first deployment is the final model.

## Update

Update through Marketplace, restart HA and refresh the dashboard. Existing options, learned state, costs/history, pause state and write reservations persist. No new YAML, service, GPU, external AI model or activation step is required.
