# Live trial control

Version 0.13 adds an opt-in controller that runs inside Home Assistant, independently of open dashboards. It uses Home Assistant's built-in myUplink entities and needs no extra credentials or JavaScript resource. The existing circuit diagram is unchanged.

This first live trial is a bounded thermostat and DHW controller. The price/weather planning demo is **not** driving the pump yet. In particular, the trial does not implement predictive compressor scheduling, calibrated hydraulic feedback, or a direct inline-heater inhibit.

## Install once

1. Update/redownload NIBE F750 Dashboard in HACS and refresh the browser.
2. Download [`nibe_f750_trial.yaml`](../packages/nibe_f750_trial.yaml) into `/config/packages/nibe_f750_trial.yaml`.
3. Enable packages in `configuration.yaml` if not already enabled:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

   Merge `packages:` into an existing `homeassistant:` section; do not create a duplicate section. If packages are configured differently already, use that existing arrangement.
4. Run Home Assistant's configuration check, then restart Home Assistant. The controller waits **15 minutes after startup** before it can write. This protects the rate limit even after an unexpected restart.
5. Disable the three old automations: **Smart thermostat**, **Set target temp**, and **DHW Optimization**. Leave sensor integrations running. The new controller does not read or require the stored `sensor.thermostat_comp_c1/c2` requests.
6. Add/open `type: custom:nibe-f750-smart-card` and press **Start trial**. Alternatively enable `input_boolean.nibe_smart_control_enabled` in Home Assistant. It is off on first installation; its selection restores across subsequent restarts.

The package is a one-time backend installation because a HACS Dashboard download cannot install server-side automations. The Start/Pause button appears when Home Assistant exposes the package's enable helper. No additional dashboard resource is required.

## What it controls

The owner confirmed these room measurements:

| Circuit | Room sensor | Role |
| --- | --- | --- |
| C1 | `sensor.ovanvaning_temperature` | Upstairs, radiators; leads demand |
| C2 | `sensor.nedervaning_temperature` | Downstairs, low-temperature circuit with its own shunt and pump |

- C1 target: the original 19/20°C price/temperature rules. Missing price, outdoor or extract readings select 20°C.
- C2 target: `min(ceil(C2 room temperature), C1 target)`. This uses the newly confirmed **downstairs C2** reading; the older supplied YAML used the upstairs entity in this expression.
- Each offset starts from its current NIBE value. If room temperature is more than 0.3°C below target, increase by one offset unit; if more than 0.3°C above, decrease by one. Otherwise hold. C2 increases are blocked while C1 is below its target by more than 0.3°C. C2 decreases are allowed. Requests outside the entity's native min/max are skipped.
- The one-unit step is a **heating-curve offset unit**, not a promised 1°C room-temperature change. This incremental thermostat is new trial logic; it does not reproduce an unknown algorithm behind the old stored requests. Review its response before leaving it unattended for long periods.
- DHW: preserve the original Normal/Economy time and price rules, including Normal overnight. The option must exist on `select.vp_comfort_mode`.
- Optional existing `input_number.set_temp_c1/c2` helpers are updated locally for visibility. These are not NIBE cloud writes.

Unknown/non-numeric or implausible room readings (outside 5–35°C), unavailable offsets, restored values, or room/offset states not reported for more than 30 minutes stop the cycle. The 5–35°C check rejects bad data; it is **not** a comfort band. Home Assistant's `last_reported` checks HA reports, not guaranteed physical sensor freshness. This trial does not yet compare C1's measured water supply against its required supply temperature; room-temperature priority and the linked target are its initial protection against C2 dominating. Both rooms need observation while tuning it.

The trial writes only the two heating offsets and DHW comfort mode. Native heat-pump control still determines compressor operation, degree minutes, inline heat, defrost and hygiene cycles. No claim is made that this first trial prevents every unnecessary inline-heater start.

## Cloud write budget

The old automations attempted two offset writes and one DHW write every 15 minutes: **at most 3 calls per cycle, 12 per hour**.

The trial:

- Runs one serialized backend script. Multiple cards, browser refreshes and manual script calls share its gates.
- Attempts each of those three settings at most once per batch, and skips unchanged settings.
- Waits at least **15 minutes after the final attempt/completion** before the next batch, with two extra seconds for timestamp rounding. The once-per-minute trigger normally makes this about 16 minutes. Writes within a batch may follow each other immediately, as the old offset writes did.
- Saves the cycle gate and reserves every attempt before dispatch; updates the write timestamp again after the service returns. Failures consume the interval and are not immediately retried.
- Restores timestamps and enforces the startup quiet period. Toggling Start/Pause does not reset the gates.

Thus this controller initiates no more than 3 NIBE-setting service calls in a rolling 15-minute window, including failed attempts. The budget applies to **this controller's Home Assistant service calls**; it cannot constrain myUplink's internal HTTP behavior, NIBE app usage, or other automations. Disable the old writers before starting the trial.

## Pause, inspect and revert

Press **Pause control**, or turn off `input_boolean.nibe_smart_control_enabled`. The backend checks this before each dispatch; an already dispatched request can finish. Pausing leaves the last applied offsets and DHW mode in place. It does not reset the heat pump or undo a manual change.

Inspect the **NIBE bounded trial cycle** script traces, current room temperatures, offsets, and the `input_datetime.nibe_smart_control_last_cycle` / `last_attempt` helpers. Missing data can stop a cycle while the enable switch remains on. To return to the old setup, pause this controller first, inspect the current settings, then re-enable the old automations.

Validation executes the package's actual Jinja templates and action tree with simulated HA states, failures and restored timestamps, plus browser checks of Start/Pause. It has not been installed or tested against the owner's Home Assistant instance. Run HA's own configuration check as part of installation.
