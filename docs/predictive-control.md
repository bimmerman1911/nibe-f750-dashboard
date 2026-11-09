# Predictive and adaptive control

> See [joint adaptive control in v0.21](joint-control.md) for the current live implementation. This page records the earlier forecast-planner design.

The v0.16 recommendation-only implementation is superseded by [active adaptive control in v0.17](adaptive-control.md). The planner now drives the existing heating-offset and DHW setters automatically while learning your home's response locally.

## Forecast sources

The backend prefers a single SMHI weather entity, otherwise a single weather entity. Integration Configure allows an explicit hourly weather entity. It calls HA's hourly `weather.get_forecasts`; no separate credentials are extracted.

Prices use the supplied Nord Pool sensor's timestamped `raw_today` / valid `raw_tomorrow`, or the official `nordpool.get_prices_for_date` action through a uniquely identifiable Nord Pool configuration entry. The defaults remain SE3 and SEK. Source prices are preserved: SEK/MWh is converted once, SEK/kWh is unchanged and öre/kWh is converted by 100. No extra VAT or supplier/network fees are added automatically. Negative prices are supported.

Timestamps require explicit offsets. Overlapping price rows are rejected. Weather is interpolated only across gaps of at most three hours; a current reading may bridge a first forecast point within 90 minutes. The timeline stops at the first missing price/weather interval, up to 24 hours. At least six continuous hours are required. Unknown tomorrow prices are not invented.

Sources refresh every 15 minutes and failed retrieval retries after two minutes. Model computation runs off HA's event loop. Forecast errors clear the active schedule and automatically fall back to temperature control. Fixed circuit relationships remain inside the controller and are not explained on the dashboard.

For model learning, active target mapping, diagnostics, configuration and limitations see the [adaptive control guide](adaptive-control.md).
