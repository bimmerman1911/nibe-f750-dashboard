# Direct heating-offset planning

Version 0.19 replaces the heating/coasting target-temperature mapper with receding-horizon native offset planning. The usual room target is 20°C; configured minimum/maximum temperatures (initially 19–20.5°C) are comfort bounds, not two switching targets.

The existing thermal scheduler first reserves compressor time for DHW using prices, weather and predicted hot-water demand. A second beam search evaluates native heating-offset sequences over those intervals. Each candidate changes, holds or reduces the offset by one native step, within the entity's min/max limits. Minute simulation substeps predict supply temperature, accumulated degree minutes, native heat response, estimated electrical demand and delayed heat delivery to the house. Search penalises comfort violations, auxiliary use and unnecessary setting changes, as well as electricity cost and insufficient heat at the end of the horizon. It is a bounded approximate search, not a guarantee of globally optimal cost or a perfect native-firmware emulator.

The current interval's chosen offset is sent directly through myUplink's existing number entity. It no longer passes through an artificial 19/20°C thermostat target. Actual temperatures can override a cached offset decision to restore comfort. The fixed secondary-circuit rules remain internal. NIBE still owns compressor frequency, heater staging, defrost and all native protections; the integration never writes simulated degree minutes or predicted frequency to the pump.

## What adapts

The house model still learns heat loss, thermal capacity, internal gains, heat delivery lag and hot-water demand. A separate native-response learner now fits nominal heat output from previous output, supply-target error and degree-minute backlog over measured 15-minute windows. It also refines the supply-temperature shift per offset step and observed compressor/inline-heater start thresholds. The fit uses actual states, not its own predictions. Gaps, unavailable data and defrost prevent training across invalid intervals. The initial model is used immediately; learning is not an activation gate.

Learning persists in local HA storage and resets with Reset learning. Download integration diagnostics for the native-response coefficients, window count, prediction error and recent offset requests. Heat and electrical power remain estimates rather than dedicated meter readings.

The initial curve shift is 2.5°C per offset step, native start estimates are −60 and −700 degree minutes for compressor/auxiliary heat, and effective supply dynamics start from an estimated emitter conductance and 30-minute response. Start thresholds and curve shift improve when identifiable changes occur. Firmware-specific timing, supply response, DHW interruption and room differences are approximated; they are corrected from fresh observations each planning cycle. The outdoor heating-curve slope currently uses a fixed initial approximation. Sparse variation limits what the model can learn without deliberate intervention; it does not inject extra test writes.

## Runtime behaviour

The optimiser runs in Home Assistant's executor, using existing forecast refresh timing. Only changed native settings are written. Existing persisted gates remain: at most three setting attempts per rolling 15 minutes, normal batches at least 902 seconds apart, including failed calls. A candidate forecast does not bypass this gate. Actual native limits and the per-decision step limit are checked again when applying the plan.

Fresh degree minutes, supply/required temperature, outdoor temperature, compressor frequency/limit, inline power, room and tank readings are required. If these or forecasts are unavailable, the controller uses ordinary fixed-20°C temperature control and Normal DHW. There is no longer a price-triggered 19°C fallback. Pause and DHW reserve handling are unchanged.

The forecast's power lines now use the offset simulation's estimated demand. Historical predictions remain as issued. Existing cost history and the ordinary-thermostat comparison are retained.
