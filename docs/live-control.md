# Integrated Smart Control

The controller and both cards now install together as a **HACS Integration**. Follow [installation and migration](../README.md#install).

**Existing installation:** remove the old `nibe_f750_trial.yaml` package, change the HACS repository category from Dashboard to Integration, install, restart HA and add **NIBE F750 Smart Control** under Devices & services. No replacement YAML file is needed. Keep the three old thermostat/DHW automations disabled.

The new controller refuses to write while the old YAML writer service remains loaded. Its switch starts enabled after first setup; a manual pause persists. Integration start/reload checks inputs immediately, without a fixed waiting period. Saved write timestamps still prevent a quick restart from bypassing the normal interval. Writes are serialized and durably reserved; failed writes consume the budget. Updates thereafter use HACS.

The [adaptive controller](adaptive-control.md) learns local thermal response and hot-water demand, plans from prices/weather, and applies heating targets/DHW settings automatically. The fixed distribution rules and native supply feedback are retained internally.

Unknown, restored or over-30-minute-old room/offset readings block control. The native number bounds are enforced. A five-minute telemetry snapshot retains source timestamps, temperatures, targets, degree minutes, compressor frequency, DHW temperatures and inline-heater state/power/limit through HA Recorder. Recorder exclusions can prevent history retention.

The control switch exposes status, targets, active strategy and learning statistics. Pause leaves the last NIBE settings applied and preserves learning. The integration also provides Reset NIBE learning and downloadable diagnostics. Native heat-pump control continues to own compressor operation and inline-heat permission/limit. The active planner runs from initial estimates immediately; no recommendation-only mode is required.

Storage-mode dashboard resources are configured automatically. YAML-mode dashboards get the module via the HA frontend API; remove older NIBE resource entries from dashboard YAML. Resource registration and platform startup rely on HA APIs; the code is tested with fixtures and hassfest, not against the owner's running installation.
