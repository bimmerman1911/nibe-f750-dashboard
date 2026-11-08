# NIBE F750 Smart Control

One **HACS Integration** installs the background controller and both dashboard cards. It uses Home Assistant's built-in **myUplink** connection. No YAML package, extra credentials, manual JavaScript copying or separate card download is required.

![Circuit diagram](docs/dashboard.png)

## Install

1. Set up Home Assistant's built-in **myUplink** integration for your F750.
2. Add `https://github.com/bimmerman1911/nibe-f750-dashboard` to HACS custom repositories with category **Integration**. Install **NIBE F750 Smart Control**.
3. Restart Home Assistant, then go to **Settings → Devices & services → Add integration → NIBE F750 Smart Control**.
4. Refresh the browser. The integration automatically registers both dashboard cards. Add either or both:

```yaml
type: custom:nibe-f750-card
```

```yaml
type: custom:nibe-f750-smart-card
```

Control is enabled by default after setup and checks readings immediately. There is **no fixed startup delay**; saved timestamps still enforce the normal write interval after a recent request. Pause/Resume is available in the Smart Control card and the integration's control switch. Paused state and write timestamps survive restarts. No dashboard needs to remain open.

The controller uses the owner's confirmed room entities: upstairs C1 `sensor.ovanvaning_temperature`, downstairs C2 `sensor.nedervaning_temperature`, existing `vp_*` myUplink controls, and `sensor.nordpool_kwh_se3_sek_3_10_025`. Other installations need equivalent entity names; configurable source selection is not included yet. Existing diagram sensor discovery remains automatic. Add SMHI through HA for hourly forecasts in the Smart Control card.

## Migrate from the earlier Dashboard/YAML installation

1. Disable the old **Smart thermostat**, **Set target temp**, **DHW Optimization** automations and pause the old NIBE controller.
2. Delete `/config/packages/nibe_f750_trial.yaml` if it exists. Remove any explicit include of that file from `configuration.yaml`; a general packages include can stay. Check configuration.
3. Remove the old HACS **Dashboard** installation and re-add this repository as an **Integration**, then install it.
4. Restart HA, add the integration under Devices & services and refresh the browser. Existing card YAML/types remain valid.

The new integration detects the old registered YAML script service and **does not write** while they remain loaded. Remove the package and restart, rather than merely pausing it. This avoids two competing controllers. Existing number/comfort settings remain on the pump throughout migration.

Standard storage-mode dashboard resources are registered automatically, including removal of this project's old `/local/` and `/hacsfiles/` card resources. For YAML-mode dashboards, the integration loads its module through HA's frontend API; remove any old NIBE resource URLs from your YAML so an outdated card is not loaded alongside it.

## Adaptive Smart Control (v0.17)

**The learned forecast plan now changes settings automatically.** Update through Marketplace, restart HA and refresh the browser. Existing integrations and card configurations keep working. No YAML, training file, extra model service or shadow-mode activation is needed.

- Learns cooling/heating response and heat delay from actual temperatures and heat-pump operation. Parameters persist across restarts.
- Learns an hourly hot-water demand profile and effective tank charging response.
- Plans heating and DHW using hourly weather and upcoming electricity prices, stored heat, available compressor capacity and estimated auxiliary need.
- Applies the current schedule through planned native heating offsets within room comfort bounds. For DHW, Normal enables charging and Economy deliberately defers it; a low Economy preset is supported. Data/forecast failure or Pause restores Normal at the next permitted update.
- Starts from estimates immediately and refines them while operating. It automatically falls back to fixed-20°C thermostat control when forecasts or a feasible plan are unavailable.
- Keeps the established write cadence: changed settings only, at most three setting attempts per rolling 15 minutes, with persisted timestamps. Native NIBE control owns actual compressor/heater operation, defrost and hygiene.

The card shows **Adaptive control** or **Temperature control** (fallback), the current targets, price/schedule outlook and learning progress. Circuit dependencies remain fixed internal constraints. Learning state is not an enable/disable gate.

[Model, configuration, diagnostics and limitations](docs/adaptive-control.md). This is an active first adaptive supervisor; it does not claim metered COP, perfect prediction or globally optimal cost. No GPU, AI subscription or direct HA access is needed for local learning.

## Direct offset planning (v0.19)

Adaptive control now searches native heating-offset sequences instead of converting heating/coasting periods into 19/20°C targets. The search predicts supply temperature, degree-minute backlog, compressor/auxiliary demand and delayed room response. Prices, weather and indoor comfort bounds determine which sequence is selected. Room temperature remains a comfort constraint; the normal target stays stable.

From v0.19.1, offset decisions can jump directly across the native range in one write; only the write timing is limited.

The native-response model learns from observed operating data and persists alongside the house model. The existing fixed circuit relationship, DHW reservation and cloud-write cadence remain in place. Missing required offset/degree-minute data uses ordinary 20°C temperature control with Normal DHW, without the old price-triggered 19°C rule. [Operation and modelling assumptions](docs/offset-control.md).

Update through Marketplace, restart HA and refresh the browser. No YAML, activation step or external model service.

## Scheduled DHW and morning reserve (v0.20)

Normal now follows the current DHW reservation, with low-reserve/necessary-charge exceptions and a daily 06:00 full-charge objective. A live failsafe enables Normal in time for a conservative charge estimate. Demand prediction uses the existing learned hourly usage profile; the power forecast now accounts for native charging thresholds and learned compressor fraction. [Operation and physical limits](docs/dhw-control.md).

## Recovery planning (v0.20.1)

If strict comfort/terminal constraints yield no schedule, the planner now searches an explicit recovery trajectory instead of immediately abandoning optimisation. Recovery prioritises reducing predicted comfort/reserve shortfalls and restoring the normal targets over price. It reports **Recovery plan**; it does not change configured temperature limits or unblock auxiliary heat. The secondary circuit can recover while upstairs is below target when measured supply is sufficient; real supply shortfalls and DHW priority still prevent an increase.

## Cards and calculations

The existing light, portrait-friendly combined refrigerant/hydraulic circuit card is unchanged. It shows positional temperatures, animated operation, Q/P and approximate shower minutes.

From v0.18, **Prices & schedule** shows the past 12 hours and next 12 hours, with 15-minute predicted and observed power lines. A separate weekly area compares recorded estimated electricity cost against a modelled ordinary 20°C thermostat with Normal DHW. Future days stay blank. Available Recorder history is imported automatically; missing data is not invented. [Calculations, history and comparison basis](docs/electricity-history.md).

- [Sensor discovery](docs/discovery.md) and [manual-based schematic](docs/schematic.md)
- [Heat calculations](docs/heat-calculations.md) and [shower estimates](docs/shower-time.md)
- [Planning model and limits](docs/smart-control.md)
- [Controller and migration](docs/live-control.md)

## Development

`npm run build` regenerates the standalone distributable and identical integration frontend. `npm run check` verifies both copies. Run `python -m http.server 8080` for `/demo/` and `/demo/smart.html`.

Run `python tests/adaptive_test.py` for learning and active control, `python tests/predictive_test.py` for price/weather/model/source checks, `python tests/integration_test.py` for policy/runtime tests and `python tests/accounting_test.py` for power, costs and history. The archived package regression checks need PyYAML/Jinja2 (`python tests/control_test.py`). Browser checks use Playwright and a running preview server (`npm test`). CI also runs HA's hassfest validation.

Validation uses deterministic HA-shaped fixtures and browsers; installation on the owner's HA instance has not been verified remotely. Independent community project; not affiliated with NIBE/myUplink. MIT licensed.
