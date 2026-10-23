# Data Source

## Origin

Raw lab test results are submitted by Vermont-certified labs and land in a SQL
Server table:

```
groundwater.ChemistryResults
```

(accessed via an internal ArcGIS SDE connection file)

This is the **system of record** for every analyte test submitted to the state,
across all water source types (private well, spring, public/municipal, surface
water, etc.) and all client types (homeowners, schools, daycares, VDH internal
lab proficiency tests, etc.) — i.e. it is not pre-filtered for the private
drinking water use case at all.

## Weekly load

Every week, `GroundwaterChemistryDatabasePROD.py`:

1. Truncates and reloads a GIS-side staging table,
   `GroundwaterChemistry_GWCDrawdata`, with a 1:1 column copy of
   `groundwater.ChemistryResults`. This table is the full, **unfiltered,
   ungeocoded** snapshot of all submitted results — useful as a state-level
   dataset since it needs no geometry.
2. Runs weekly exceedance alerting (see below), cleaning/standardization,
   geocoding, exceedance calculation, and aggregation (see
   [02-etl-pipeline.md](02-etl-pipeline.md)) against an in-memory copy of that
   table.
3. Writes two downstream products:
   - `GroundwaterChemistry_GWCDPoints` — filtered to the private drinking water
     scope, geocoded, with exceedance flags and per-town/analyte summary stats.
   - `GroundwaterChemistry_GWCDPointTableExternal` — the public-facing version
     of the above, deduplicated per location and suppressed for small sample
     sizes. This is what feeds the Experience Builder app.

## Alias/reference tables used during cleaning

- `GroundwaterChemistryAliasTable` — maps problematic/misspelled town names
  (typos, out-of-state towns, placeholder values) to a canonical Vermont
  municipality, where a mapping exists.
- `GroundwaterChemistry_TownBounds` — Vermont town boundary polygons, used to
  spatially join each geocoded point to a `TOWNNAME`.

## Weekly exceedance alert (separate from the public product)

Independent of the map/dashboard pipeline, the script also emails a rolling
7-day exceedance report (CSV + HTML table) to a fixed internal distribution
list, classifying records into Metals / VOCs / BNAs / PCBs / Herbicides /
PFOS-PFAS / Other. This uses its own, separate set of hardcoded concentration
thresholds (see the script) and is **not** the same threshold table used for
the public town-level exceedance rates — see
[04-exceedance-calculations.md](04-exceedance-calculations.md) for that.
