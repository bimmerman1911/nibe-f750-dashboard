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

## What runs now

- Bounded thermostat control: the original 19/20°C price rules; at most one offset step per cycle, with a 0.3°C deadband.
- C2 follows `min(ceil(C2 room temperature), C1 target)`. C2 increases require satisfied C1 room demand and adequate BT61 supply relative to C1's calculated target.
- A sustained 15-minute supply shortfall can reduce C2 one step when C2 is near its target; unknown/stale data and DHW priority prevent C2 increases.
- Original Normal/Economy DHW rules, including Normal overnight.
- **At most three setting attempts in a rolling 15-minute window**, unchanged values skipped. Durable reservation before dispatch, timestamps after completion, no immediate retry after failure. Other automations/NIBE app actions and myUplink internal HTTP retries are outside this controller's budget.
- Local telemetry every five minutes in `sensor.nibe_control_telemetry`, normally retained by HA Recorder. Source report timestamps are included.

The controller writes only the two heating offsets and DHW comfort mode. Native NIBE control owns compressor, inline-heater permission/limit, defrost and hygiene. **Forecast-based scheduling remains a planning model, not the live controller.** No calibrated COP, globally optimal cost or guaranteed inline-heater avoidance is claimed.

Status is reported by the backend: Starting, Running, Paused, Waiting for readings, Legacy backend detected, Write failed or Controller error. Running means the control loop is active; check HA logs and actual settings to investigate rejected cloud requests.

## Cards and calculations

The existing light, portrait-friendly combined refrigerant/hydraulic circuit card is unchanged. It shows positional temperatures, animated operation, Q/P and approximate shower minutes.

- [Sensor discovery](docs/discovery.md) and [manual-based schematic](docs/schematic.md)
- [Heat calculations](docs/heat-calculations.md) and [shower estimates](docs/shower-time.md)
- [Planning model and limits](docs/smart-control.md)
- [Controller and migration](docs/live-control.md)

## Development

`npm run build` regenerates the standalone distributable and identical integration frontend. `npm run check` verifies both copies. Run `python -m http.server 8080` for `/demo/` and `/demo/smart.html`.

Run `python tests/integration_test.py` for policy/runtime tests. The archived package regression checks need PyYAML/Jinja2 (`python tests/control_test.py`). Browser checks use Playwright and a running preview server (`npm test`). CI also runs HA's hassfest validation.

Validation uses deterministic HA-shaped fixtures and browsers; installation on the owner's HA instance has not been verified remotely. Independent community project; not affiliated with NIBE/myUplink. MIT licensed.
