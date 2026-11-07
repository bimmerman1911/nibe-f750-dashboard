# Heat flow Q and compressor power P

The diagram displays rates in **kW**, not accumulated energy in kWh. Values are calculated from the current Home Assistant states; there is no extra cloud polling. Required inputs are automatically discovered on the selected myUplink device when exposed and enabled.

## Compressor P: reported input

F750 parameter **43141**, “compr. in power”, reports power delivered by the inverter to the compressor. The card converts W to kW. It does not estimate power from frequency, assume a fixed COP, or subtract auxiliary heat from whole-unit consumption. This is electrical compressor input, not refrigerant shaft work or total heat-pump mains consumption. Inverter losses, fans and pumps are outside this reported value.

## Condenser Q: water-side estimate

`Q_cond [kW] = 997 [kg/m³] × 4.18 [kJ/(kg·K)] × volume_flow [m³/s] × (BT12 − BT3) [K]`

Inputs: BF1 EP14 flow (40072), BT12 condenser water outlet (40017), BT3 return (40012). Uses BT12 rather than heating supply BT2, which can include auxiliary heat. Assumes pure water with fixed density and heat capacity; glycol, incorrect flow calibration and sensor offsets change accuracy. A positive water-side heat rate can persist during residual heat transfer after compressor shutdown. It is not a certified heat meter.

## Evaporator Q: estimated balance, or sensible air heat

When condenser Q and positive compressor P are available and Q_cond ≥ P:

`Q_evap ≈ Q_cond − P_comp`

This approximate steady-state energy balance neglects motor/casing losses and changes in stored heat. Electrical input is used as an approximation for energy entering the refrigerant cycle; this is not a direct refrigerant enthalpy measurement. During starts, stops, defrost and asynchronous cloud updates it may be inaccurate. The card labels it **estimated balance**.

Otherwise, if BS1 airflow (40050), extract temperature BT20 (40025) and discharge temperature BT21 (40026) are available:

`Q_evap,sensible [kW] ≈ 1.2 [kg/m³] × 1.006 [kJ/(kg·K)] × airflow [m³/s] × (BT20 − BT21) [K]`

This is **sensible air heat only**, not total evaporator capacity: it excludes condensation/freezing heat, humidity effects and defrost. It uses constant air density and heat capacity. It must not be treated as a complete COP measurement or used to infer compressor power by subtracting it from condenser Q.

## Availability and units

- Temperatures: °C or °F, converted to °C for the calculation.
- Volume flow: l/min, l/m, l/s, m³/h, m3/h, m³/s or m3/s, converted to m³/s.
- Power: W or kW. Energy units such as kWh are rejected.
- Missing, unavailable, blank, non-numeric or unsupported-unit inputs leave the affected value blank. Negative flow or a reversed temperature difference is not converted to a positive heating rate. Unitless BS1 values are not assigned assumed physical units.
- Cloud states are sampled asynchronously; calculations do not interpolate or synchronize samples or detect defrost. These are display estimates, not inputs to automatic control. Validate readings against the actual installation before relying on them.

For optional advanced manual mapping, the keys are `compressor_power`, `water_flow`, `condenser_water_out`, `return`, `air_flow`, `exhaust_air` and `leaving_air`. Normal automatic configuration still needs only `type: custom:nibe-f750-card`.

Source parameter descriptions: [F750 register list](https://github.com/yozik04/nibe/blob/master/nibe/data/f750.csv). Exposure and units in myUplink may vary by firmware and subscription. No assertion is made that every F750 will provide all the inputs.
