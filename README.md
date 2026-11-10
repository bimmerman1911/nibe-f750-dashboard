# NIBE F750 Smart Control

One **Marketplace (HACS) integration** installs the adaptive controller and both dashboard cards. It uses Home Assistant's built-in **myUplink** connection. No separate Java service, YAML controller package, model server or manual JavaScript copying is required.

![Circuit diagram](docs/dashboard.png)

## Install or update

1. Set up Home Assistant's built-in **myUplink** integration for your F750.
2. Add `https://github.com/bimmerman1911/nibe-f750-dashboard` as a custom repository with category **Integration**, then install **NIBE F750 Smart Control**.
3. Restart Home Assistant. For a new installation, add **NIBE F750 Smart Control** under Settings → Devices & services.
4. Refresh the browser and add either or both cards:

```yaml
type: custom:nibe-f750-card
```

```yaml
type: custom:nibe-f750-smart-card
```

Existing installations only need the Marketplace update, HA restart and browser refresh. Options, learned state, history, pause state and cloud-write timestamps are retained. There is no trial activation or training-completion gate. New installations start enabled; an existing paused installation remains paused.

The integration registers its bundled cards automatically. For YAML-mode dashboards, remove old NIBE resource URLs to avoid loading an outdated duplicate.

## Interactive charts — v0.22.0

Prices & schedule and Outdoor forecast support zoom buttons, earlier/later navigation, horizontal drag and two-finger pinch. Tap or hover to inspect interval values; keyboard arrows inspect points and +/− zoom. Reset restores each chart's full default time window. Ctrl/Command + wheel zooms without intercepting normal scrolling.

Open **Data & labels** to choose visible series and point labels. Price, predicted/observed power, schedule colours and inline highlighting can be selected separately. Display preferences are saved in this browser; zoom/pan and inspection survive live HA updates. These controls only change the visualisation and do not change heat-pump settings. Zooming uses available data; it does not fetch additional history.

## Peak planning improvement — v0.21.1

The planner now compares complete price-aware coasting/recovery schedules with its beam search. This fixes a case where the search discarded a cheaper, comfortable way through the afternoon price peak before its delayed benefit became visible. Increasing calculation time alone did not recover it. All candidates use the same native-response model, comfort constraints, DHW protections and cloud-write gates. Diagnostics include the full forecast and candidate comparisons. No configuration reset or larger calculation budget is needed.

## Joint adaptive control — v0.21

The controller now plans **heating offsets and DHW settings together**, simulating the commands it can actually apply. This replaces the earlier ideal heat schedule followed by a separate offset translation.

- Optimises using published prices, hourly weather, stored warmth, observed heat response, degree minutes and compressor capacity. An 18°C minimum creates real flexibility; 20°C is a preference rather than a mandatory horizon-end target.
- Calibrates attainable supply from observed heating operation. An unreachable primary flow-temperature request is not assumed to create more heat at a saturated compressor.
- Plans Normal/Economy with native DHW thresholds and learned usage. It can make a limited reserve charge, pause while a later charge remains restartable, then finish for the daily 06:00 full-charge objective.
- Learns from measured heating/cooling and hot-water windows, with explicit coverage and uncertainty. Rejects discontinuities and prevents controller-induced stops from being learned as native full-tank stops.
- Models held settings until the next permitted cloud update. Unchanged settings do not consume a new write interval. Existing limits remain: at most three setting attempts per rolling 15 minutes, with normal batches at least 902 seconds apart and durable reservations before calls.
- Uses shorter available price/weather horizons when tomorrow is unpublished. On slower hardware, a reduced-search continuation completes the horizon instead of repeatedly abandoning a heavy search.

The Smart Control card shows the actual decision/fallback reason, comfort bounds and preferred temperature, actual → selected offset, next permitted update and DHW permission. An archived forecast is clearly marked inactive while the controller is paused or using temperature-control fallback.

The agreed room rule remains: **C1 supply shortfall can restrict C2 only when C2's room is warmer than C1**. The dependency is internal, not a separate dashboard topic. Native NIBE protections, actual compressor/inline-heater operation, defrost and hygiene remain pump-owned.

[Review findings, new model, validation and limitations](docs/joint-control.md)

## Data and configuration

The controller uses the owner's established room sources (`sensor.ovanvaning_temperature`, `sensor.nedervaning_temperature`), `vp_*` myUplink entities and `sensor.nordpool_kwh_se3_sek_3_10_025`. The circuit diagram's sensor discovery remains automatic. Other installations currently need equivalent backend source names; configurable source mapping is not included.

Use an hourly HA weather entity, preferably SMHI. Configure weather and indoor/DHW bounds through the integration's options. Saving reloads the integration automatically. A lower minimum permits coasting; fallback temperature control uses the configured preferred temperature and Normal DHW.

The 06:00 objective is a best-effort reserve policy in HA's local timezone. Normal permits charging but cannot force a native start above its threshold, create unavailable capacity or recover instantly after a large unexpected draw. A predicted shortfall is shown. After a measured morning completion, subsequent normal draw-off does not falsely restart a missed-morning recovery.

No dedicated F750 meter is assumed. Electrical power uses the owner's compressor frequency/BT12 formula plus reported inline power. Thermal output, COP, forecast cost and the ordinary-thermostat comparison are estimates; neither metered COP nor proven bill savings are claimed.

## Cards and history

The light, portrait-friendly combined circuit diagram includes positional temperatures, operation animations, Q/P, estimated COP and shower minutes.

Prices & schedule spans the past 12 hours and next 12 hours, with 15-minute power estimates and orange predicted inline-heater markers. The separate weekly area compares recorded estimated cost against a modelled ordinary 20°C thermostat with Normal DHW. Future days and unavailable history remain blank. Recorded predictions stay as issued.

- [Electricity history and comparison basis](docs/electricity-history.md)
- [Sensor discovery](docs/discovery.md) and [manual-based schematic](docs/schematic.md)
- [Heat calculations](docs/heat-calculations.md) and [shower estimates](docs/shower-time.md)
- [Controller and migration](docs/live-control.md)

## Older YAML/card installations

Disable the old Smart thermostat, Set target temp and DHW Optimization automations. Remove the old `nibe_f750_trial.yaml` package and any explicit include of that file. Replace the old Dashboard-category installation with this Integration-category repository, restart HA, add the integration and refresh the browser. The integration refuses competing writes while the old script-specific service remains loaded. Existing card types remain valid.

## Development

`npm run build` generates both identical bundled frontends. `npm run check` verifies them. Run `python -m http.server 8080` for `/demo/` and `/demo/smart.html`; browser checks use Playwright and `npm test`.

Python tests cover the native response, joint scenarios, learning quality, command timing, morning reserve/DST, recovery, accounting, source parsing and archived policy regressions. The archived package tests require Jinja2/PyYAML. CI runs these checks plus Home Assistant hassfest.

Validation uses deterministic HA-shaped fixtures and browsers; operation on the owner's HA instance has not been verified remotely. Independent community project; not affiliated with NIBE/myUplink. MIT licensed.
