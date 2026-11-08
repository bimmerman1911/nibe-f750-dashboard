# First predictive backend — v0.16

Update through Marketplace, restart HA and refresh the browser. No new integration, YAML package or JavaScript resource is needed.

The existing thermostat/DHW controller keeps operating. The new background planner produces and records **recommendations**; it does not dispatch additional NIBE writes or replace the running thermostat. The dashboard calls these recommendations and shows their temperature/reserve outlook. Circuit relationships remain fixed controller constraints rather than dashboard content.

## Inputs

The backend automatically prefers a single SMHI weather entity, otherwise a single weather entity, and calls HA's hourly `weather.get_forecasts`. It uses the supplied Nord Pool sensor's timestamped `raw_today`/`raw_tomorrow`; an explicitly false `tomorrow_valid` excludes tomorrow. Official Nord Pool's `get_prices_for_date` is the fallback, using the selected sensor's configuration entry, SE3 and SEK. Credentials stay inside the source integrations.

SEK/MWh is divided by 1000 once; SEK/kWh is preserved; öre/kWh is converted by 100. No VAT or supplier/network add-ons are added automatically. Negative prices are accepted. Ambiguous units, overlapping rows or timestamps without offsets are rejected. Missing tomorrow prices are not extrapolated. DST uses absolute timestamps and real interval durations.

Hourly weather is interpolated only across gaps of at most three hours. Current weather can bridge a first forecast point within 90 minutes. A continuous horizon of at least six hours is required; planning stops at the first missing price/weather interval, up to 24 hours. Missing or stale room/tank/frequency-limit readings clear the recommendation. Failures do not stop the existing controller. Acquisition refreshes every 15 minutes (source failures retry after two minutes), including with the dashboard closed; model computation runs off HA's event loop.

Integration **Configure** options allow selecting an hourly weather entity when automatic selection is ambiguous and changing four model parameters: building heat loss (kW/K), thermal storage (kWh/K), compressor space-heating output and DHW output (kW). Changing options reloads the integration without resetting its write timestamps.

## Initial model

A first-order equivalent-building model uses the average of the two confirmed room readings. It treats the existing distribution arrangement as fixed. Defaults: heat loss 0.10 kW/K, effective storage 9 kWh/K, compressor heat 4.2 kW, DHW heat 3.6 kW. These are **uncalibrated assumptions**, not inferred measurements. Heat output corresponds to the model's current reported maximum frequency; the model does not yet learn a frequency/temperature capacity map.

The hot-water model uses mean BT6/BT7, 0.209 kWh/K tank capacity (about 180 L), a small standing loss and a constant 0.15 kW draw allowance. That allowance is an assumption, not a learned shower timetable. Tank stratification and individual draws are not resolved.

Model bands are 19–20.5°C indoor average and 42–55°C mixed-tank temperature, with horizon-end targets of 20°C and 48°C. These are prediction assumptions, not newly imposed live comfort/hygiene settings. A starting temperature outside the band can recover without worsening its initial violation. Bands on an indoor average do not prove each room stays comfortable.

Compressor power uses the owner's frequency/BT12 formula. Assumed BT12 is 38°C for heating, 55°C for DHW. The minimum and maximum reported compressor frequencies constrain the low/high choices; heating output is apportioned by frequency within this simplified model. Weather changes building demand; it is not an outdoor-source COP multiplier for the F750. Suspect hydraulic flow readings are not used as heat-output ground truth.

A bounded beam search considers coast, low/high heating and DHW with shared compressor capacity. It first seeks a compressor-only schedule, then allows a 1 kW auxiliary candidate if none is found. Terminal temperature/tank reserves limit end-of-horizon depletion. The finite search is not proof of optimality or unavoidable inline heat. Minimum compressor dwell, native degree-minute response, defrost, actual shunt dynamics and learned DHW demand are not modeled yet. Its abstract frequency schedule is not sent to the pump.

## Logging and evaluation

`sensor.nibe_heating_forecast` exposes the latest plan, source, generation time, assumptions, model cost and predicted temperature trajectory. The sensor is discovered by its integration marker even if renamed. HA Recorder normally keeps its history. The dashboard shows a concise recommendation and price/action chart, with limitations under Prediction details.

The integration also retains the last 192 forecast records (approximately 48 hours at a 15-minute cadence) in HA storage `nibe_f750.predictions`: starting observations and predicted states/actions at each future interval. Five-minute telemetry continues recording actual operation through HA Recorder. Logging is local; source retrieval does not write to NIBE.

Predictions are **conditional on the recommended actions**. Because the current thermostat is still operating, a difference between the planned trajectory and actual temperature is not automatically a model error. There is no automatic calibration, MAE score or savings claim yet. Compare recorded actual compressor/mode/heater operation and temperature response before fitting the model and enabling predictive actuation.

The next stage is fitting/validating thermal response and adding native operating constraints, then allowing validated recommendations to influence the existing bounded targets. The cloud-write budget and normal live control remain intact throughout this version.
