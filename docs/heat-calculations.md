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

## Evaporator Q: estimated balance, or sensible air heat

When condenser Q and a positive **current** compressor P reading are available and Q_cond ≥ P:

`Q_evap ≈ Q_cond − P_comp`

This approximate steady-state energy balance neglects motor/casing losses and changes in stored heat. Electrical input is used as an approximation for energy entering the refrigerant cycle; this is not a direct refrigerant enthalpy measurement. During starts, stops, defrost and asynchronous cloud updates it may be inaccurate. The card labels it **estimated balance**. Energy-derived average power is deliberately excluded from this instantaneous balance; otherwise historical electrical input would be mixed with current water-side output.

Otherwise, if BS1 airflow (40050), extract temperature BT20 (40025) and discharge temperature BT21 (40026) are available:

`Q_evap,sensible [kW] ≈ 1.2 [kg/m³] × 1.006 [kJ/(kg·K)] × airflow [m³/s] × (BT20 − BT21) [K]`

This is **sensible air heat only**, not total evaporator capacity: it excludes condensation/freezing heat, humidity effects and defrost. It uses constant air density and heat capacity. It must not be treated as a complete COP measurement or used to infer compressor power by subtracting it from condenser Q.

## Availability and units

- Temperatures: °C or °F, converted to °C for the calculation.
- Volume flow: l/min, l/m, l/s, m³/h, m3/h, m³/s or m3/s, converted to m³/s.
- Power: W or kW. Energy units such as kWh are rejected.
- Missing, unavailable, blank, non-numeric or unsupported-unit inputs leave the affected value blank. Negative flow or a reversed temperature difference is not converted to a positive heating rate. Unitless BS1 values are not assigned assumed physical units.
- Cloud states are sampled asynchronously; calculations do not interpolate or synchronize samples or detect defrost. These are display estimates, not inputs to automatic control. Validate readings against the actual installation before relying on them.

For optional advanced manual mapping, the keys are `compressor_power`, `water_flow`, `condenser_water_out`, `return`, `air_flow`, `exhaust_air` and `leaving_air`, plus optional `compressor_energy`. Normal automatic configuration still needs only `type: custom:nibe-f750-card`.

Source parameter descriptions: [F750 register list](https://github.com/yozik04/nibe/blob/master/nibe/data/f750.csv). Exposure and units in myUplink may vary by firmware and subscription. No assertion is made that every F750 will provide all the inputs.

History API source: [Home Assistant history WebSocket implementation](https://github.com/home-assistant/core/blob/dev/homeassistant/components/history/websocket_api.py).
