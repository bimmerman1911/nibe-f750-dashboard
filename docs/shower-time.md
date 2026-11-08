# Shower minutes at the DHW tank

A small shower symbol and duration appear beside the tank. This represents available shower time, not an elapsed shower timer.

If an enabled myUplink sensor on the selected device explicitly reports shower time/minutes/duration in minutes, seconds or hours, the card converts it to minutes and uses it directly. No unverified numeric parameter ID is assigned. The optional manual mapping key is `shower_minutes`.

Otherwise, the card displays a **rough ideal-mixing estimate**, marked `≈`, requiring both BT7 (tank display/top) and BT6 (tank control/lower) temperatures:

```text
T_bulk ≈ (BT7 + BT6) / 2
mixed_litres ≈ tank_litres × (T_bulk − cold_inlet) / (shower_temperature − cold_inlet)
minutes ≈ mixed_litres / shower_flow_litres_per_minute
```

BT7 below the requested shower temperature gives zero minutes. Missing temperature inputs or invalid settings give “— min”. Values are rounded down to whole minutes.

Defaults are 180 L nominal tank volume, 10°C cold inlet, 40°C mixed shower temperature and 10 L/min shower flow. The [F750 installation manual](https://assetstore.nibe.se/hcms/v2.4/entity/document/330612/storage/MzMwNjEyLzAvbWFzdGVy/download/Installat%C3%B6rshandbok_Fr%C3%A5nluftsv%C3%A4rmepumpar_F750_531385-2.pdf) documents nominal tank volume; cold-inlet temperature, shower temperature and shower flow are explicit assumptions, not device measurements. The tooltip lists the active assumptions.

This model uses only two temperature points. It does not resolve tank stratification, draw-off cooling, mixing-valve behavior, effective usable volume, concurrent taps or reheating. It can overestimate available duration and is not a guarantee that the shower will remain at the target temperature.

Optional adjustments, without manual sensor IDs:

```yaml
type: custom:nibe-f750-card
shower:
  tank_volume_l: 180
  cold_water_c: 10
  shower_temperature_c: 40
  flow_l_min: 10
```

These options affect only the shower-duration estimate, not heat-pump settings or the Q/P formulas. The diagram is read-only.
