# Automatic F750 discovery

Home Assistant's built-in myUplink integration derives display names from API parameter names, prefixes entity names with device names, and permits user renames. Hardcoded `sensor.nibe_f750_*` names therefore cannot reliably work across installations.

Instead the card reads the Home Assistant entity and device registries over the authenticated Home Assistant WebSocket connection. It filters for `platform: myuplink`, selects one device and matches parameter IDs against the integration's unique ID format: `<myUplink device ID>-<parameter ID>`. Renaming an entity does not change this identity. No myUplink API requests or credentials are added.

The card excludes disabled entities and other integrations, scopes every match to one device, and leaves ambiguous matches unmapped. With multiple devices, it selects a unique F750 model if possible, otherwise asks the user to choose. A device selection stays for that card instance; optional `device_id:` in YAML pins a Home Assistant device registry ID across reloads. Multiple cards can target different devices. Use **Refresh discovery** after enabling missing entities.

| Card reading / control | F750 parameter | Meaning |
| --- | --- | --- |
| Outdoor | 40004 | BT1 outdoor temperature |
| Indoor | 40033 | BT50 room temperature, system 1 |
| Hot water | 40013, fallback 40014 | BT7 tank top, fallback BT6 charging |
| Supply | 40008 | BT2 heating supply, system 1 |
| Return | 40012 | BT3 return |
| Extract air | 40025 | BT20 exhaust/extract air before recovery |
| Discharge air | 40026 | BT21 vented air after recovery |
| Evaporator | 40020 | BT16 evaporator |
| Condenser outlet | 40019 | BT15 refrigerant liquid line; not BT12 heating-water outlet |
| Compressor | 43136 | Actual frequency; not requested/target/min/max frequency |
| Auxiliary heater | 43084 | Internal electrical addition power |
| Operation | 49994 | Current priority |
| Heating adjustment | 47011 | Heating curve offset, system 1; writable `number` only |
| Hot water mode | 47041 | Comfort mode; writable `select` or `number` only |

The register list documents the F750 parameter semantics; it does not guarantee every parameter is exposed by every myUplink firmware/API version. Unrecognized IDs are left blank, with no broad name guesses. Missing sensors may be disabled, unavailable from the cloud, or absent in the installation. The card does not enable entities itself. Indoor temperature requires a room sensor. COP and electrical input are not automatically inferred: neither follows from frequency or heater power. They remain optional manual mappings of separately measured/calculated entities.

## Sources inspected

- [Home Assistant myUplink entity base](https://github.com/home-assistant/core/blob/dev/homeassistant/components/myuplink/entity.py): device identity and unique ID construction.
- [Home Assistant myUplink sensor implementation](https://github.com/home-assistant/core/blob/dev/homeassistant/components/myuplink/sensor.py): API parameter naming, parameter IDs and priority enum.
- [F750 register data, python-nibe](https://github.com/yozik04/nibe/blob/master/nibe/data/f750.csv): F750 database 8310, parameter IDs and descriptions (2020-06-24).

Browser tests use registry fixtures representing that source format, including renamed entities, disabled entities, another integration and multiple devices. Actual discovery on the owner's F750 has not yet been verified.
