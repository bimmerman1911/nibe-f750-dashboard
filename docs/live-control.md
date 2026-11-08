# Smart Control

Version 0.14 integrates the controller that runs inside Home Assistant, independently of open dashboards. It uses Home Assistant's built-in myUplink entities and needs no extra credentials or JavaScript resource. The existing circuit diagram is unchanged.

This first live control is a bounded thermostat and DHW controller. The price/weather planning demo is **not** driving the pump yet. In particular, the control does not implement predictive compressor scheduling, calibrated hydraulic feedback, or a direct inline-heater inhibit.

## Install once

1. Update/redownload NIBE F750 Dashboard in HACS and refresh the browser.
2. Download [`nibe_f750_trial.yaml`](../packages/nibe_f750_trial.yaml) into `/config/packages/nibe_f750_trial.yaml`.
3. Enable packages in `configuration.yaml` if not already enabled:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

   Merge `packages:` into an existing `homeassistant:` section; do not create a duplicate section. If packages are configured differently already, use that existing arrangement.
4. Disable the three old automations: **Smart thermostat**, **Set target temp**, and **DHW Optimization**. Run Home Assistant's configuration check, then restart Home Assistant. The controller waits **15 minutes after startup** before it can write. Leave sensor integrations running.
5. Open `type: custom:nibe-f750-smart-card`. Control enables automatically on first installation/update. The status changes from **Starting** to **Running** after the 15-minute startup delay and first control cycle. No Start button is required.

HACS installs the dashboard code. The one-time backend package installation/replacement above is still necessary; HACS Dashboard repositories cannot install HA server configuration. The legacy filename `nibe_f750_trial.yaml` is retained so replacing an existing package does not create duplicate controllers. No additional JavaScript resource is required.

The card reports **Not running** when the backend is missing, **Backend update required** for an older backend without status reporting, **Paused** after a manual pause, **Waiting for readings** for invalid/stale inputs, and **Controller not responding** if no cycle completes for more than 20 minutes. Running means recent backend cycles, not a guarantee that every cloud write succeeded; failed calls remain visible in script traces. Forecast loading errors do not hide the controller's independent status.

Pause/Resume remains available. Pausing is preserved across later restarts; the one-time initialization marker prevents re-enabling it on every boot. The same default-on migration happens once when updating the earlier opt-in backend.

## What it controls

The owner confirmed these room measurements:

| Circuit | Room sensor | Role |
| --- | --- | --- |
| C1 | `sensor.ovanvaning_temperature` | Upstairs, radiators; leads demand |
| C2 | `sensor.nedervaning_temperature` | Downstairs, low-temperature circuit with its own shunt and pump |

- C1 target: the original 19/20°C price/temperature rules. Missing price, outdoor or extract readings select 20°C.
- C2 target: `min(ceil(C2 room temperature), C1 target)`. This uses the newly confirmed **downstairs C2** reading; the older supplied YAML used the upstairs entity in this expression.
- Each offset starts from its current NIBE value. If room temperature is more than 0.3°C below target, increase by one offset unit; if more than 0.3°C above, decrease by one. Otherwise hold. C2 increases are blocked while C1 is below its target by more than 0.3°C. C2 decreases are allowed. Requests outside the entity's native min/max are skipped.
- The one-unit step is a **heating-curve offset unit**, not a promised 1°C room-temperature change. This incremental thermostat is new control logic; it does not reproduce an unknown algorithm behind the old stored requests. Review its response before leaving it unattended for long periods.
- DHW: preserve the original Normal/Economy time and price rules, including Normal overnight. The option must exist on `select.vp_comfort_mode`.
- Optional existing `input_number.set_temp_c1/c2` helpers are updated locally for visibility. These are not NIBE cloud writes.

Unknown/non-numeric or implausible room readings (outside 5–35°C), unavailable offsets, restored values, or room/offset states not reported for more than 30 minutes stop the cycle. The 5–35°C check rejects bad data; it is **not** a comfort band. Home Assistant's `last_reported` checks HA reports, not guaranteed physical sensor freshness. The C1 supply guard now compares BT61 with C1's calculated supply target, as described below. Both rooms need observation while tuning it.

The control writes only the two heating offsets and DHW comfort mode. Native heat-pump control still determines compressor operation, degree minutes, inline heat, defrost and hygiene cycles. No claim is made that this first control prevents every unnecessary inline-heater start.

## Cloud write budget

The old automations attempted two offset writes and one DHW write every 15 minutes: **at most 3 calls per cycle, 12 per hour**.

The control:

- Runs one serialized backend script. Multiple cards, browser refreshes and manual script calls share its gates.
- Attempts each of those three settings at most once per batch, and skips unchanged settings.
- Waits at least **15 minutes after the final attempt/completion** before the next batch, with two extra seconds for timestamp rounding. The once-per-minute trigger normally makes this about 16 minutes. Writes within a batch may follow each other immediately, as the old offset writes did.
- Saves the cycle gate and reserves every attempt before dispatch; updates the write timestamp again after the service returns. Failures consume the interval and are not immediately retried.
- Restores timestamps and enforces the startup quiet period. Toggling Start/Pause does not reset the gates.

Thus this controller initiates no more than 3 NIBE-setting service calls in a rolling 15-minute window, including failed attempts. The budget applies to **this controller's Home Assistant service calls**; it cannot constrain myUplink's internal HTTP behavior, NIBE app usage, or other automations. Disable the old writers before starting the control.

## Pause, inspect and revert

Press **Pause control**, or turn off `input_boolean.nibe_smart_control_enabled`. The backend checks this before each dispatch; an already dispatched request can finish. Pausing leaves the last applied offsets and DHW mode in place. It does not reset the heat pump or undo a manual change.

Inspect the **NIBE control cycle** script traces, current room temperatures, offsets, and the `input_datetime.nibe_smart_control_last_cycle` / `last_attempt` helpers. Missing data can stop a cycle while the enable switch remains on. To return to the old setup, pause this controller first, inspect the current settings, then re-enable the old automations.

Validation executes the package's actual Jinja templates and action tree with simulated HA states, failures and restored timestamps, plus browser checks of Start/Pause. It has not been installed or tested against the owner's Home Assistant instance. Run HA's own configuration check as part of installation.


## Supply guard and telemetry update

Replace the installed package with the current [`nibe_f750_trial.yaml`](../packages/nibe_f750_trial.yaml), check configuration and restart HA to add these entities. A HACS dashboard update does not update an already copied backend package. The normal startup quiet period still applies.

The owner's entity export established these mappings:

| Signal | Entity |
| --- | --- |
| Distribution supply proxy, BT61 | `sensor.vp_supply_line_bt61` |
| Distribution return, BT62 | `sensor.vp_return_line_bt62` |
| Required C1 supply | `sensor.vp_calculated_supply_climate_system_1` |
| C2 supply / return | `sensor.vp_supply_line_ep21_bt2` / `sensor.vp_return_line_ep21_bt3` |
| Required C2 supply | `sensor.vp_calculated_supply_climate_system_2` |
| Degree minutes | `sensor.vp_degree_minutes_2` |
| Inline power / status | `sensor.vp_power_internal_add_heat` / `sensor.vp_int_elec_add_heat` |

BT61 is a shared distribution-supply proxy, not a direct measurement at each radiator. The entity named `sensor.vp_supply_line_bt2` has a friendly name identifying BT63 in the export; it is logged separately and is not silently treated as a confirmed C1-only measurement.

A **2°C shortfall margin** is the initial control setting, not a calibrated hydraulic model. C2 increases require fresh supply/target/priority readings, native Heating priority, and BT61 at least C1's required temperature minus that margin, as well as the existing C1 room-temperature condition. During DHW priority, C2 increases wait.

`binary_sensor.nibe_c1_supply_shortfall` turns on after a shortfall persists for 15 minutes during Heating. While the shortfall still exists, the controller may reduce C2 by one offset step per permitted cycle, but only if C2 is within 0.3°C of its linked target or warmer. If C2 is already colder, it holds rather than lowering its request further. The diagnostic resets through DHW/other priority transitions; its delay restarts after HA restart. Review this margin and the response using history. No additional cloud settings are written and the existing write gate applies to all offset changes.

`sensor.nibe_control_telemetry` captures a local snapshot every five minutes, whether control control is enabled or paused. Its `readings` attribute includes room/outdoor/water temperatures, calculated targets, degree minutes, compressor frequency and reported limits, BT12, DHW temperatures, heater power/status/limit, offsets and current price. Unknown readings remain explicitly unknown. Snapshots contain HA report timestamps to distinguish old values. These are reads of existing HA state and do not cause NIBE cloud writes.

Home Assistant's Recorder normally saves the telemetry sensor. If your Recorder uses an include/exclude list, ensure this sensor is recorded. Keep several days of history to tune the coupled model; the snapshot does not itself learn a model or produce measured COP/savings. No source meters based on the suspect hydraulic flow values are used as calibrated heat-output ground truth.

The owner subsequently enabled inline heat on the pump. The earlier export's Blocked status and 0 kW configured limit are historical observations, not fixed controller assumptions. The control reads/logs the current settings and leaves heater permission, maximum electrical addition and operating mode under native/manual control.
