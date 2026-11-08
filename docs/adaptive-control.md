# Adaptive Smart Control — v0.17

This version **changes heat-pump settings automatically using its forecast plan**. It starts operating from initial estimates and learns locally as the house runs. There is no recommendation-only stage, external AI service, training download, new enable switch or approval before each write.

Update the installed Integration through Marketplace, restart Home Assistant and refresh the browser. The existing enable/pause selection is preserved. No files or helpers need installing. Control evaluates immediately when readings are available; it has no fixed startup delay. The normal 15-minute setting cadence remains.

## What the controller does

Every minute it observes actual room/outdoor temperatures, compressor frequency, operating priority and inline-heater power. Every 15 minutes it refreshes hourly weather and upcoming Nord Pool prices and plans the next known 6–24 hours. Only published prices and a continuous forecast interval are used.

At each control cycle it selects the plan interval containing **the current time**, rather than repeatedly following the first interval. It translates that interval into a room-temperature target and Normal/Economy DHW demand:

- Heating periods raise the requested target toward the planned reserve, within the configured maximum.
- Coast periods lower it toward the configured minimum, using the house's stored warmth.
- A colder room approaching its minimum overrides a coast request and restores the normal target.
- DHW preparation, low measured reserve, or a low forecast reserve selects Normal. Economy means deliberate deferral, including a preset so low it produces essentially no DHW. A charge planned within the next 30 minutes enables Normal now; the reserve check explicitly projects zero charging over that interval instead of counting future reheating. Existing charging can continue until the model target is reached.
- The fixed relationship between circuits and the existing supply-temperature feedback remain internal constraints.

Defaults are 19°C minimum, 20°C normal and 20.5°C maximum preheat target. Native curve offsets move by at most one unit per cycle, with the existing 0.3°C room deadband and the entities' native ranges. An offset unit is not a guaranteed one-degree room-temperature change.

The actual cloud setters are the two heating offsets and `select.vp_comfort_mode`. The planner **does not directly command compressor Hz or disable the inline heater**. NIBE's degree-minute control, compressor/inverter limits, heater permission/maximum, defrost and hygiene remain native. The plan's heat-output schedule is translated into supervisory temperature and DHW requests; actual Hz/power may differ and those actual results are used for learning. This is active predictive supervision, not replacement firmware.

## Learning your house

The learner fits an equivalent-house response from the average of the two room readings. It uses actual observed heating inputs, including compressor frequency and inline power, rather than assuming the recommended schedule was followed. No suspect water-flow readings are used as heat-output ground truth.

A bank of five projected recursive least-squares models represents heat-response delays of 0, 0.5, 1, 2 and 4 hours. Each estimates loss response, heating response and an internal-gain term:

`ΔT = a × ∫(T_outdoor − T_room)dt + b × ∫heat_proxy dt + c × elapsed_time`

One-minute observations form measured 30-minute windows. The heat proxy uses nominal compressor output scaled by actual/reported-maximum frequency while Heating is active, plus measured inline power. A first-order delay filters the heat proxy for each candidate. These models are updated with bounded changes and forgetting; the candidate with reliably lower pre-update response error is selected. The planner uses its current effective heat-loss/storage/gain parameters and delayed heat state.

The learner runs even when control is paused, so manually controlled operation is still useful data. Unknown/restored/stale inputs, large room jumps, gaps over three minutes, implausible readings and explicit defrost states reset partial windows or skip fitting. Windows are not fitted across HA restarts. Coefficients, covariance, selected delay, error statistics and demand profiles persist in HA storage.

The dashboard's **Learning your home** / **Adapting to your home** describes accumulated observations, not whether writes are enabled. Both modes actively control the pump. A 30-minute response error is computed before updating the model, using actual observed inputs. It is not a 24-hour weather forecast accuracy or a savings figure. Low heating/weather variation limits identification; neither a small error nor many samples proves all physical parameters are uniquely known.

## Hot water and capacity

DHW uses the mean of BT6/BT7 and an initial effective 180 L tank capacity. It learns a 24-hour demand profile from net tank cooling outside charging periods, after accounting for standing losses. Signed temperature changes are accumulated before deriving demand, so small oscillations are not all counted as draws. It also gradually updates effective charging capacity from observed charge periods and estimates the Normal-mode tank ceiling from completed charges.

The planner shares compressor capacity between space heating and DHW. It respects reported frequency limits, an approximate minimum-on/off/mode dwell, tank reserve and horizon-end reserves. It first searches for a compressor-only schedule, widens that search, then considers available auxiliary stages. The native configured electrical-addition limit and Blocked status constrain the model's auxiliary availability; the integration does not change those permissions. In auxiliary candidates it minimizes auxiliary energy before cost.

Compressor electrical input uses the owner's empirical frequency/BT12 formula. Current BT12 is used for the applicable operating mode where available; the other mode starts from an assumed outlet temperature. There is no dedicated meter: COP, heat output and cost remain model estimates. The effective learned parameters depend on the nominal heat-output basis and are not independent measurements of physical building loss, storage or COP.

## Comfort, fallback and cadence

Integration Configure exposes room bounds, model tank bounds and initial loss/storage/capacity estimates. Existing learning is retained when settings change. **Reset NIBE learning**, on the integration's device page, restarts from those estimates. Resetting learning does not reset the cloud-write timestamps or automatically unpause control.

Tank bounds describe the model; native Normal/Economy temperatures and hygiene settings remain NIBE settings. Economy can be set very low to defer production; Normal should be set to the desired charging level. Normal enables native charging subject to the pump’s start/stop thresholds; it is not an unconditional compressor-start command. The integration does not change these preset temperatures. Initial defaults are a 42°C mixed-tank reserve, 48°C model target and up to 52°C planned ceiling. The model does not resolve tank stratification or guarantee shower duration.

Forecast/source failure, stale plans, missing required readings or no feasible schedule automatically selects the existing temperature/DHW policy. Invalid room/offset readings still stop setting dispatch. The UI shows **Adaptive control** when the plan supplies targets and **Temperature control** when fallback supplies them. No operator confirmation is required to resume adaptive operation once data returns.

Forecast failure and invalid required readings restore Normal when the comfort selector is available. Pause also releases deliberate Economy deferral to Normal once, while leaving heating offsets in place. After this release, manual preset choices while paused are respected. This restoration waits for the next permitted setting update and preserves an explicit Lux selection on pause. Removing/unloading the integration stops its callbacks; pause and let Normal apply before uninstalling if DHW is deferred.

The same serialized write path handles every decision. It skips unchanged settings, persists timestamps before and after calls, and limits its setting attempts to the existing cadence (normally about 16 minutes between batches, at most three calls per rolling 15 minutes). A quick restart, Pause/Resume or model reset does not multiply requests. Source forecast/price reads and local learning/recording are not NIBE setting writes. Other controllers, NIBE app actions and client-internal HTTP retries remain outside this controller's budget.

## Diagnostics and performance

`sensor.nibe_adaptive_model` reports learning state and estimated response parameters. The integration device's control switch exposes the current applied strategy/target request and learning statistics. Entity IDs may receive suffixes if old registry entries reserve names; the card discovers its controller by integration metadata.

HA Recorder normally retains five-minute telemetry, the forecast sensor and model updates. Local storage keeps 192 forecast records and 512 decision records, including requested settings, service-call outcomes and observed room readings. Use the integration menu's **Download diagnostics** to share model state and recent decisions if tuning is needed. No HA credentials or routine manual history upload is required for learning.

Tests cover synthetic-house adaptation over two weeks, persistence, bad data, learned demand, real forecast-to-dispatch wiring, active target payloads, fallback, native write cadence and desktop/mobile UI. HA hassfest validates packaging. The release has not been tested remotely against the owner's physical installation.

This is the complete first adaptive supervisory version, not a claim of a globally optimal or perfectly calibrated heat-pump model. It does not yet learn an independent metered COP map, model solar/wind explicitly, predict every defrost or guarantee that native NIBE never starts inline heat unnecessarily. We can improve those behaviors from the recorded outcomes without another architecture change.
