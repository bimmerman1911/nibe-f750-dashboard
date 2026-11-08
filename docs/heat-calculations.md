# Heat flow Q and estimated compressor power P

All diagram rates are in **kW**. The current calculation chain is:

1. Reference airflow and BT20/BT21 → sensible evaporator heat.
2. Actual compressor frequency and BT12 → estimated electrical compressor power.
3. Sensible evaporator heat + estimated compressor power → estimated condenser heat.

Required entities are automatically discovered through Home Assistant's built-in myUplink integration. No extra myUplink calls or history queries are needed.

## Compressor P: supplied frequency / BT12 formula

The owner supplied this empirical formula:

`P_est [kW] = f [Hz] × [0.0161 + 0.000208 × (BT12 [°C] − 45)]`

The implementation uses these coefficients exactly. Inputs are actual compressor frequency (43136 or its measurement-name alias) and condenser water outlet BT12 (40017 or its alias). BT12 is not the BT15 liquid-line temperature or BT2 heating supply temperature. °F inputs are converted to °C; frequency must be Hz.

This replaces the previous reported-power/history-based path. There is no fallback to a reported power sensor, assumed COP or averaged energy derivative. Missing inputs, negative frequency or a negative calculated coefficient leave P blank rather than manufacturing a plausible value. Zero frequency with valid BT12 produces zero power. The formula's accuracy and operating range have not been independently validated for this installation; it is labeled **P est**.

## Evaporator Q: reference-airflow sensible heat

The card automatically discovers `sensor.vp_reference_air_speed_sensor` and equivalent prefixed/renamed entities on the selected device. The owner confirmed M3/h units. Discovery uses parameter 43124 or explicit reference-airflow aliases.

`Q_evap,sensible [kW] ≈ 1.2 [kg/m³] × 1.006 [kJ/(kg·K)] × reference_airflow [m³/s] × (BT20 − BT21) [K]`

For m³/h, equivalently: `Q ≈ 0.000335333 × airflow × temperature_drop`.

Reference airflow takes precedence; measured BS1 airflow (40050) is used if reference airflow is unusable. No water-side calculation is used to infer evaporator Q, so the chain is not circular. Unsupported units, missing temperatures, negative airflow or a reversed temperature difference leave Q blank.

The diagram says **Q sens** and identifies whether reference or measured airflow is used. Reference flow can differ from actual flow as frost builds up, filters become dirty or ventilation settings change. Constant air density and heat capacity are approximations. The estimate excludes condensation/freezing heat and humidity effects; it is not total refrigerant evaporator capacity.

## Condenser Q: derived heat balance

`Q_cond,est [kW] ≈ Q_evap,sensible [kW] + P_est [kW]`

This follows the owner's requested heat balance. Corrupt liquid-flow/pump readings are excluded entirely. BF1 water flow and BT3 return are not read by this calculation. Auxiliary electrical heater power is separate and is not added to condenser Q. If either input is missing, condenser Q stays blank; there is no fallback to the water-side estimate.

This is a sensible-based condenser estimate, not measured total output. It inherits omitted latent heat, power-model error and reference-flow uncertainty. It neglects heat losses and thermal storage. Cloud readings are sampled asynchronously and may be particularly unrepresentative during starts, stops or defrost. No accuracy band is claimed, and no automatic control or COP calculation uses these estimates.

Example: 60 Hz, BT12 = 45°C → P_est = 0.966 kW. Reference airflow 180 m³/h and a 24°C air temperature drop → Q_evap,sensible ≈ 1.449 kW; derived Q_cond ≈ 2.415 kW.

## Units and setup

- Frequency: Hz.
- Temperature: °C or °F.
- Volume flow: l/min, l/m, l/s, m³/h, M3/h, m3/h, m³/s or m3/s.
- Unitless airflow, percentages and m/s air velocity are not assumed to be volume flow.
- Normal automatic configuration still needs only `type: custom:nibe-f750-card`.
- Advanced manual mapping keys: `compressor_frequency`, `condenser_water_out`, `reference_air_flow`, `air_flow`, `exhaust_air`, `leaving_air`. Old `compressor_power`, `compressor_energy` and `water_flow` mappings no longer drive calculations.

Parameter descriptions: [F750 register list](https://github.com/yozik04/nibe/blob/master/nibe/data/f750.csv). Exposure and units in myUplink vary by firmware and equipment.
