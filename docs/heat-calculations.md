# Heat flow Q and compressor power P

The diagram displays rates in **kW**, not accumulated energy in kWh. Values are calculated from the current Home Assistant states; there is no extra cloud polling. Required inputs are automatically discovered on the selected myUplink device when exposed and enabled.

## Compressor P: energy-derived average when current power is unavailable

F750 register definitions include both current compressor input power (43141) and cumulative compressor energy (43144). A register definition does **not** establish that myUplink exposes it on a particular installation. The owner reports that current compressor power is unavailable on their F750, so current power is now optional and the card also discovers cumulative compressor energy.

When a compressor-only counter with units **kWh or Wh** is available, Home Assistant recorder history provides:

`P_average [kW] = (E_end [kWh] − E_start [kWh]) / elapsed_hours`

The card queries roughly the last 10 minutes of history, at most once per minute while in use. It accepts a 5–15 minute sample span with the latest sample at most 3 minutes old. It supports Home Assistant's compressed WebSocket history states as well as full states. It rejects counter resets, unknown/unavailable values, invalid timestamps, operating hours and dimensionless values. A label such as “compressor time factor” is accepted only when the source actually declares electrical energy units. The counter's own accuracy and resolution limit the result; this is not an independent meter validation.

The diagram says **P avg** and the summary gives the averaging period. This includes compressor-off periods within that interval; it is not instantaneous running power. Missing/excluded recorder history, an unexposed or disabled counter, denied history access or insufficient recent samples leave P blank. The card never changes recorder configuration or enables disabled entities. A 0.01 kWh counter increment corresponds to about 0.06 kW over 10 minutes, so short intervals are deliberately avoided.

If a valid current power reading is available, it takes precedence. Parameter 43141 describes power delivered from the inverter to the compressor, excluding other unit consumption; it is not necessarily available through myUplink. W is converted to kW.

No default frequency-to-power curve is supplied: no verified F750 operating-point map or installation calibration was obtained. Electrical input cannot be recovered uniquely from compressor frequency and these temperatures alone. A calibrated model would require electrical reference measurements or a validated compressor performance map. Subtracting sensible-air evaporator heat from condenser heat would assign omitted latent heat to compressor power and is not used.

## Condenser Q: water-side estimate

`Q_cond [kW] = 997 [kg/m³] × 4.18 [kJ/(kg·K)] × volume_flow [m³/s] × (BT12 − BT3) [K]`

Inputs: BF1 EP14 flow (40072), BT12 condenser water outlet (40017), BT3 return (40012). Uses BT12 rather than heating supply BT2, which can include auxiliary heat. Assumes pure water with fixed density and heat capacity; glycol, incorrect flow calibration and sensor offsets change accuracy. A positive water-side heat rate can persist during residual heat transfer after compressor shutdown. It is not a certified heat meter.

## Evaporator Q: reference-airflow sensible estimate

The card automatically discovers `sensor.vp_reference_air_speed_sensor` (including equivalent prefixed/renamed entities on the selected myUplink device). The owner confirms that this entity has volume-flow units, M3/h. Discovery uses parameter 43124 or explicit reference-airflow name aliases; no fixed installation prefix is required.

When this reference airflow is available with supported volume/time units, it takes precedence for evaporator Q:

`Q_evap,sensible [kW] ≈ 1.2 [kg/m³] × 1.006 [kJ/(kg·K)] × reference_airflow [m³/s] × (BT20 − BT21) [K]`

Equivalently, for m³/h: `Q ≈ 0.000335333 × airflow × temperature_drop`.

It is labeled **reference airflow · sensible only**, with **Q sens** in the diagram. This uses a reference value rather than confirmed current flow. Frost buildup, dirty filters, ventilation changes and defrost can make actual flow differ. The sensible calculation excludes condensation/freezing heat and humidity effects; it is not total refrigerant evaporator capacity. It uses constant air density and heat capacity. It must not be used to infer compressor power by subtracting it from condenser Q.

The reference airflow value and its declared unit are also displayed with the readings so the source can be checked. M3/h, m3/h and m³/h are accepted. Percentages, m/s velocity and unitless values are not assumed to be volume flow.

### Other available inputs

If reference airflow cannot be used, the existing alternatives remain:

- Condenser Q and positive **current** compressor P, with Q_cond ≥ P: `Q_evap ≈ Q_cond − P_comp`. This approximate steady-state balance neglects motor/casing losses and changes in stored heat; the label is **estimated balance**. Energy-derived average power is excluded to avoid mixing historical electrical input with current water-side output.
- Otherwise, measured BS1 airflow (40050), BT20 and BT21 use the same sensible-air formula, labeled **sensible air only**. This also excludes latent heat.
- Missing valid inputs leave the result blank.

## Availability and units

- Temperatures: °C or °F, converted to °C for the calculation.
- Volume flow: l/min, l/m, l/s, m³/h, m3/h, m³/s or m3/s, converted to m³/s.
- Power: W or kW. Energy units such as kWh are rejected.
- Missing, unavailable, blank, non-numeric or unsupported-unit inputs leave the affected value blank. Negative flow or a reversed temperature difference is not converted to a positive heating rate. Unitless BS1 values are not assigned assumed physical units.
- Cloud states are sampled asynchronously; calculations do not interpolate or synchronize samples or detect defrost. These are display estimates, not inputs to automatic control. Validate readings against the actual installation before relying on them.

For optional advanced manual mapping, the keys are `compressor_power`, `water_flow`, `condenser_water_out`, `return`, `air_flow`, `exhaust_air` and `leaving_air`, plus optional `compressor_energy` and `reference_air_flow`. Normal automatic configuration still needs only `type: custom:nibe-f750-card`.

Source parameter descriptions: [F750 register list](https://github.com/yozik04/nibe/blob/master/nibe/data/f750.csv). Exposure and units in myUplink may vary by firmware and subscription. No assertion is made that every F750 will provide all the inputs.

History API source: [Home Assistant history WebSocket implementation](https://github.com/home-assistant/core/blob/dev/homeassistant/components/history/websocket_api.py).
