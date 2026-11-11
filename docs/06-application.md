# The Applications

Two Experience Builder apps consume this pipeline's output — a public one and
a staff-only internal one. Both were verified directly against their live
Experience Builder configuration (not just inferred from the ETL script), by
pulling each item's JSON config from the ArcGIS REST API.

## Public: Drinking Water Quality

**[Drinking Water Quality](https://experience.arcgis.com/experience/dbed7d7f37ff4927a8edda677696b7c4)**
— ArcGIS Experience Builder app, owned by `VDH_EnvHealth`, public (~18k views).

> **This app has three pages, and only one is fed by this pipeline:** "Private
> Drinking Water Quality" (the 6 analyte tabs described below). The other two
> — "System Level Public Drinking Water Quality" and "State Level Public
> Drinking Water Quality" — are embedded Power BI reports on an entirely
> separate VT DEC public-water-system data pipeline; this script has no effect
> on them whatsoever.

### Data source

The app's map/table/search widgets are built on:

```
GroundwaterChemistry_GWCDPointTableExternal  (joined to)  GroundwaterChemistry_TownBoundaries
```

This confirms `GWCDPointTableExternal` is in fact what's wired to the public
product — i.e., the suppressed/deduplicated table described in
[05-geocoding.md](05-geocoding.md), not the unsuppressed `GWCDPoints` table.

### Fields used in the app

Matches the ETL script's output fields exactly:

- `AnalyteAlias` (displayed as "Analyte")
- `TOWNNAME` / `TOWNNAMEMC` (displayed as "Town")
- `CityCount` (displayed as "Total Tests")
- `CityAboveMCL`, `CityAboveSMCL`, `CityAboveVHA`, `CityAboveThreshold`
- `PctAboveMCL`, `PctAboveSMCL`, `PctAboveVHA`, `PctAboveThreshold`
- `MapMean`, `MapMedian`, `MapMin`, `MapMax`, `MapPercentile95`, `MapStdDev`,
  `MapMDL`, `MapPopupHeading` (pre-formatted strings for map popups)

### Analytes currently surfaced

The app only has a dedicated map + summary table + search widget set for six
analytes — exactly the six the ETL script generates popup text for:

1. Arsenic
2. Fluoride
3. Gross Alpha
4. Nitrate
5. Radon
6. Uranium

All other analytes in `EXCEEDANCE_THRESHOLDS_BY_ANALYTE` (Lead, Manganese,
Copper, Iron, Sodium, Chloride, Radium, TDS, Turbidity, Odor, E.coli, Total
Coliform, pH, Hardness, Nitrite, Total Nitrate and Nitrite) **are calculated**
in the pipeline (exceedance flags, town-level stats all exist in
`GroundwaterChemistry_GWCDPoints`) but are **not currently displayed** in this
app. A grant-reporting dashboard could surface any of these directly from
`GWCDPoints` without needing new calculation logic.

### Layout

Each analyte has its own sidebar (full-screen) with: a text panel citing its
MCL/SMCL/VHA value, a map, a controller toggling between map and table view,
a summary table, and an address search widget.

## Internal: Drinking Water Quality - Internal

ArcGIS Experience Builder app, private (staff-only sharing group). Shows the
full, unfiltered internal picture that the public app deliberately doesn't:

| Layer | Source table |
|---|---|
| "Raw Data (GWCD) - Internal" | `GroundwaterChemistry_GWCDrawdata` (RAW_DATA_TABLE) |
| "Geocoded GWCD Points - Internal" | `GroundwaterChemistry_GWCDPoints` (POINTS_FEATURE_CLASS) — includes records that failed to geocode |
| "Analyte Data - External" | `GroundwaterChemistry_GWCDPointTableExternal` (EXTERNAL_PUBLIC_TABLE) — the same table the public app reads, included here for staff comparison/QA |

This app also carries a link to the `GroundwaterChemistry_ExcludedRecords` AGOL
CSV item (see [05-geocoding.md](05-geocoding.md)) for staff who want to review
geocoding precision without pulling the CSV from AGOL Content directly.
