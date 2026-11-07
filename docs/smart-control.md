# Future smart control

The built-in myUplink integration remains the transport and entity backbone. A later Home Assistant automation/integration layer can consume the same entities; this card should display its decisions rather than run a scheduler in a browser tab.

1. **Inventory and observation:** record available settings, update intervals, compressor frequency, auxiliary heater power, temperatures and energy. Confirm permissions and supported control semantics on the actual F750. Never assume direct compressor or heater control is exposed.
2. **Inputs:** timestamped electricity import prices including tariff/taxes, weather forecast, indoor comfort bounds, hot-water needs and measured power/heat. Price integration and units must be explicit.
3. **Model:** learn building heat loss and thermal inertia. Derive COP only with adequate thermal/electrical measurements and aligned time windows; distinguish compressor COP from whole-system COP including resistance heat.
4. **Shadow mode:** propose a schedule, explain cost/comfort tradeoffs, compare predictions with actual consumption. No writes until the model is validated.
5. **Constrained operation:** use only supported myUplink settings with bounds, dwell times, anti-cycling constraints and rate limits. Keep manufacturer protections, frost prevention, ventilation, hot-water hygiene and manual overrides authoritative. Fall back to native control on stale prices, forecasts or telemetry.
6. **Evaluation:** track total cost, auxiliary heater energy, starts, comfort violations and forecast error against a native-control baseline. Cloud command latency must be part of the design.

No optimizer, estimated savings or live control capabilities are claimed by v0.1.
