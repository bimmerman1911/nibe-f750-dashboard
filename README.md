# NIBE F750 Dashboard

A read-only Home Assistant circuit diagram for a NIBE F750 connected through **Home Assistant’s built-in myUplink integration**. No separate API client or credentials.

![Dashboard preview](docs/dashboard.png)

## First release

- Diagram-only light layout with bold `Q = … kW` / `P = … kW` values, BT sensor markers, red incoming air and blue outgoing air. No header panels or comfort controls. BT1/BT50 appear directly in the diagram.
- One combined refrigerant and hydraulic schematic with mapped temperatures and a shared condenser heat exchanger. Refrigerant and water paths stay separate. Static arrows show normal direction; animated air, refrigerant and water paths illustrate operation and reported heating/DHW priority. Motion is not a flow measurement. Compact BT sensor markers follow the [manual-based location guide](docs/schematic.md). On narrow cards and iPhone portrait screens, the schematic automatically becomes a vertical layout with heat recovery above heat distribution; no horizontal scrolling.
- Automatic discovery by myUplink parameter ID, with a device-scoped measurement-name fallback for API variations (including `sensor.vp_current_compressor_frequency`). Renamed entities still match stable IDs or original names. No manual sensor list required.
- Diagram annotations show compressor P estimated with the supplied frequency/BT12 formula, sensible evaporator Q from reference airflow, and condenser Q derived as their sum. Corrupt water-flow readings are excluded. See [heat calculations](docs/heat-calculations.md).
- Shower minutes beside the tank: reported duration if exposed, otherwise an approximate temperature-based estimate marked `≈`. Defaults: 180 L tank, 40°C shower, 10°C cold inlet and 10 L/min flow. See [shower estimates](docs/shower-time.md).
- Missing entities show unavailable values. No guessed sensor IDs or fabricated live COP.
- Interactive standalone demo with clearly labeled sample data.

## Connect to Home Assistant

1. Set up [the built-in myUplink integration](https://www.home-assistant.io/integrations/myuplink/) under **Settings → Devices & services**. Connect your F750 to your myUplink account first. Enter OAuth credentials in Home Assistant, never in this card or the repository.
2. Available data and writable controls depend on the equipment, firmware, API and subscription. Some entities may need enabling. myUplink normally updates every 60 seconds; this is a cloud dashboard, not real-time telemetry.
3. Copy `dist/nibe-f750-card.js` to `/config/www/nibe-f750-card.js`.
4. Under **Settings → Dashboards → Resources**, add `/local/nibe-f750-card.js?v=0.14.0` as a **JavaScript module**. Enable Advanced Mode in your profile if Resources is hidden.
5. Add a manual dashboard card with just:

```yaml
type: custom:nibe-f750-card
```

The card discovers the built-in myUplink device and readings automatically. If several devices are present, it prefers a uniquely identified F750; otherwise choose a device in the card. Use a full-width panel view or a wide section for the circuit layout. Reload the dashboard after enabling entities. Setup/retry controls appear only when a device must be selected or discovery fails. Registry access must be permitted for your Home Assistant account.

For HACS, add this repository as a custom **Dashboard** repository. `hacs.json` and the distributable file are included; this project is not listed in the default HACS catalog.

For an existing HACS installation, update/redownload the card and refresh your browser. Remove the old `entities:` and `controls:` configuration to enable automatic discovery. [Discovery details and source references](docs/discovery.md).

### Entity mapping

Manual mapping is an optional advanced override: providing `entities:` replaces automatic discovery. See [examples/dashboard.yaml](examples/dashboard.yaml). All `entities` keys are optional. `entities: {}` gives a read-only, unconfigured card. Units are taken from each entity's `unit_of_measurement` when present. Match the sensor's actual meaning; especially distinguish extract/discharge air, refrigerant temperatures and heating-water temperatures. The diagrams are explanatory, not an F750 service schematic and do not model valve positions or domestic-water plumbing in detail.

| Key | Meaning |
| --- | --- |
| `outdoor`, `room` | Outdoor and room temperature |
| `hot_water`, `hot_water_charge` | BT7 tank display and BT6 tank control temperatures, kept separate |
| `supply`, `return` | Heating-water flow and return temperatures |
| `exhaust_air`, `leaving_air` | Extract air before recovery and discharge air after recovery |
| `evaporator`, `condenser` | Evaporator and condenser refrigerant outlet (BT15 liquid line), if exposed |
| `compressor_frequency` | Compressor frequency in Hz (also drives diagram animation) |
| `heater_power` | Auxiliary electric heater power |
| `electrical_power`, `cop` | Optional measured input power and separately calculated/measured COP |
| `operation` | Reported operating mode |
| `condenser_water_out` | BT12 water outlet temperature, used with actual compressor frequency for estimated P |
| `hot_gas`, `suction` | BT14 compressor discharge and BT17 suction temperatures |
| `heating_supply`, `heating_return`, `heater_out` | BT61/BT62 after-buffer temperatures and BT63 after immersion heater |
| `air_flow` | BS1 airflow with volume/time units, for the sensible-only evaporator estimate |
| `reference_air_flow` | Automatically discovers `sensor.vp_reference_air_speed_sensor` and equivalents; takes precedence for a clearly labeled reference-airflow sensible evaporator Q estimate |

Old `controls:` configuration is ignored; this version never writes heat pump settings.

## Preview and development

No runtime dependencies. After editing card sources, run `npm run build` to regenerate the single HACS bundle:

```sh
python -m http.server 8080
# Open http://localhost:8080/demo/
node --check dist/nibe-f750-card.js
```

Browser checks: install Playwright (`npm install --no-save playwright` and `npx playwright install chromium`), then run `npm test` while the preview server is running. Checks cover portrait layout, sensor topology, heat calculations, off/zero compressor animation, air colors, shower estimates and device discovery. `PREVIEW_URL` can override the preview origin.

## Smart Control and live control

An optional [control backend](docs/live-control.md) now adjusts the two heating offsets and DHW mode, with persistent write limiting and automatic startup and Pause/Resume in the card. It uses the confirmed upstairs C1 and downstairs C2 room readings. The one-time Home Assistant package installation is required for live control.

A separate `custom:nibe-f750-smart-card` previews a two-zone, price/weather-aware heating and DHW plan using Home Assistant’s Nord Pool and SMHI integrations. The original diagram is unchanged. The planning demo remains separate from live control. The supplied C2 target dependency is displayed. Live two-zone schedules await a coupled hydraulic model; the fixed heat split is a demo assumption.

[Preview](docs/smart-desktop.png) · [Setup, model limits and design](docs/smart-control.md). Both cards are included in the existing HACS download. Update/redownload and refresh, then add `type: custom:nibe-f750-smart-card`; no additional JavaScript resource is needed.

Independent community project; not affiliated with NIBE or myUplink. MIT licensed.
