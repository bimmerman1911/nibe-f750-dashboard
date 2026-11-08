# Integrated Smart Control

The controller and both cards now install together as a **HACS Integration**. Follow [installation and migration](../README.md#install).

**Existing installation:** remove the old `nibe_f750_trial.yaml` package, change the HACS repository category from Dashboard to Integration, install, restart HA and add **NIBE F750 Smart Control** under Devices & services. No replacement YAML file is needed. Keep the three old thermostat/DHW automations disabled.

The new controller refuses to write while old YAML controller entities remain. Its switch starts enabled after first setup; a manual pause persists. Every integration start/reload waits 15 minutes before writing. Writes are serialized and durably reserved; failed writes consume the budget. Updates thereafter use HACS.

The same C1/C2 coupling, 2°C supply-shortfall margin, one-step offset changes and DHW price rules are implemented in Python. The actual room measurements are upstairs C1 and downstairs C2. BT61 is a shared distribution-supply proxy, not a measurement at every radiator. A low supply reading during DHW priority is not treated as a C2-induced heating shortfall.

Unknown, restored or over-30-minute-old room/offset readings block control. The native number bounds are enforced. A five-minute telemetry snapshot retains source timestamps, temperatures, targets, degree minutes, compressor frequency, DHW temperatures and inline-heater state/power/limit through HA Recorder. Recorder exclusions can prevent history retention.

The control switch exposes status, targets and last cycle/write-attempt timestamps. Pause leaves the last NIBE settings applied. Native heat-pump control continues to own compressor operation and inline-heat permission/limit. Predictive price/weather scheduling and a learned coupled thermal model remain future work; the migration does not activate the demonstration optimizer.

Storage-mode dashboard resources are configured automatically. YAML-mode dashboards get the module via the HA frontend API; remove older NIBE resource entries from dashboard YAML. Resource registration and platform startup rely on HA APIs; the code is tested with fixtures and hassfest, not against the owner's running installation.
