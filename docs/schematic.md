# F750 schematic and sensor positions

Checked against NIBE's **Installatörshandbok, F750 Koppar, IHB SV 2218-2, 531385-2**, printed pages 11–12 (component/sensor definitions and locations) and 14 (system principle): [official NIBE PDF](https://assetstore.nibe.se/hcms/v2.4/entity/document/330612/storage/MzMwNjEyLzAvbWFzdGVy/download/Installat%C3%B6rshandbok_Fr%C3%A5nluftsv%C3%A4rmepumpar_F750_531385-2.pdf).

This is a functional dashboard schematic. The buffer is simplified; secondary circulation pumps, bypasses, isolation valves, safety devices and variant-specific connections are omitted. It is not a service piping drawing. The heating-water circuit is separate from potable tank water and from refrigerant. The two primary-water branches represent QN10's alternative destinations, not simultaneous measured circulation.

## Temperature markers

A small circle marks the measuring location. A leader connects it to the BT identifier and current value. Missing entities show — at the documented location, not an inferred temperature.

| Marker | Location |
| --- | --- |
| BT1 | Outdoor sensor, upper ambient area of diagram |
| BT50 | Room sensor, house symbol in upper ambient area |
| BT20 | Inlet/extract air duct before evaporator |
| BT21 | Outlet/discharge air duct after evaporator, outside refrigerant loop |
| BT16 | Evaporator |
| BT17 | Suction gas entering compressor |
| BT14 | Hot gas leaving compressor |
| BT15 | Liquid line after condenser, before expansion valve |
| BT12 | Heating water leaving condenser, before immersion heater |
| BT63 | Water after immersion heater, before heating/DHW changeover |
| BT61 | Heating flow after buffer vessel |
| BT62 | Heating return after buffer vessel |
| BT3 | Common water return into condenser |
| BT7 | Tank display sensor, upper tank position |
| BT6 | Tank control sensor, lower tank position |

BT30 is a backup-heating thermostat; it is not represented as an independent telemetry temperature. The integration's optional generic BT2/system-supply reading remains under Details rather than being relabeled as BT61 or BT63. BT6 and BT7 are separately discovered; missing BT7 no longer falls back to BT6 under the wrong marker.

The older register catalog supplies IDs for BT6, BT7, BT14, BT17, BT61 and BT62. No verified BT63 register ID was found in that catalog, so BT63 discovery uses the explicit BT63 name designation, scoped to the selected myUplink device. No numeric ID is guessed.

## Direction and animation

- Air: inlet duct → evaporator air side → outlet duct. BT21 and its value stay outside the refrigerant loop.
- Refrigerant: evaporator → compressor → condenser → expansion valve → evaporator.
- Common water supply: condenser → BT12 → immersion heater (EB1) → BT63 → QN10 → selected heating or tank-coil branch → common return → BT3 → condenser.
- The heating branch includes a simplified buffer before BT61. BT62 marks its return. BT6/BT7 measure stored tank water, not the primary-water coil.

Static chevrons show normal design direction. Animated dashes follow path direction. Refrigerant motion requires positive compressor frequency and no explicit stopped/off status; water motion illustrates operation when compressor or auxiliary heater is active. Heating/DHW branch motion uses the reported priority, and stops when the branch is unknown or unselected. Air motion uses a positive available airflow/reference reading. A reference value does not prove actual fan/air movement. No animation claims measured flow or an observed valve/pump state. Inlet air is red and outlet air is blue. Reduced-motion preference stops dashes while retaining direction chevrons.

The compressor-power and heat estimates are unchanged; see [heat calculations](heat-calculations.md).

Shower time at the DHW tank: [reported duration or approximate mixing estimate](shower-time.md).
