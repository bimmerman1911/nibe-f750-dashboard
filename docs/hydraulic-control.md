# Primary production and the secondary mixing circuit

For this F750 installation, C1 is the primary radiator circuit and C2 is the lower-temperature circuit with its own mixing valve and circulation pump. The integration distinguishes the two actuator roles:

| Role | Entity / calculation |
| --- | --- |
| Primary production offset | `number.vp_heating_offset_climate_system_1` |
| Primary calculated target | `sensor.vp_calculated_supply_climate_system_1` |
| Actual primary supply used by the model | `sensor.vp_supply_line_bt61` |
| Primary degree-minute increment | `(actual primary supply − C1 calculated target) × elapsed minutes` |
| Secondary mixing target offset | `number.vp_heating_offset_climate_system_2` |
| Secondary calculated target | `sensor.vp_calculated_supply_climate_system_2` |

The C2 target is not averaged with C1, selected as a maximum, or used as a second compressor demand in the model. Secondary heat extraction can still lower the actual primary supply and thereby influence degree minutes indirectly. Both room temperatures remain relevant to comfort constraints; C2's existing room feedback and warm-secondary-only load limiting are preserved.

The joint planner already used C1's calculated target before v0.27.1. This version consolidates the existing degree-minute equation in a named primary-circuit transition shared by the joint and legacy offset models, records actuator roles in diagnostics, and adds regression tests. It does not introduce a new hydraulic model or alter the degree-minute equation, its existing bounds, or its existing hold during DHW charging. The learned differential room response remains an approximation rather than an identified shunt/flow model.

## Evidence and scope

NIBE's [ECS 40/ECS 41 installer manual](https://professional.nibe.eu/document/Installat%C3%B6rshandbok/631178-3.pdf), F-series section, printed pages 22, 28 and 33, identifies the lower-temperature secondary circuit, its own flow/return sensors, mixing valve and circulation pump, and the secondary shunt settings. The [F750 installer manual](https://assetstore.nibe.se/hcms/v2.4/entity/document/330612/storage/MzMwNjEyLzAvbWFzdGVy/download/Installat%C3%B6rshandbok_Fr%C3%A5nluftsv%C3%A4rmepumpar_F750_531385-2.pdf), printed page 16, describes ECS mixing down the supply to an additional climate system.

Those passages establish the hydraulic roles, not a complete firmware specification of degree-minute calculation. Read-only operating-history checks on this installation additionally showed degree minutes recovering while primary supply was above C1's target but well below C2's target. This supports the C1-only degree-minute basis already used by the integration. Cloud sampling is too coarse to identify the exact internal integration timing or all firmware overrides.

Regression tests hold primary conditions fixed while changing C2's offset/target, and verify unchanged predicted degree minutes and compressor behavior. Separate tests confirm that changes to C1's target or actual primary supply do change degree minutes.
