# Architecture — Ins and Outs

One weekly run of `GroundwaterChemistryDatabasePROD_updated.py` (triggered by FME
Flow — see [07-automation.md](07-automation.md)) touches every box below. Nothing
else writes to these destinations between runs.

```mermaid
flowchart TD
    SQL["SQL Server<br/>groundwater.ChemistryResults<br/>(all water sources, all client types,<br/>not pre-filtered)"]
    FME["FME Flow schedule<br/>'AHS_VDH_GroundWaterChemistryWeekly'<br/>Saturdays 21:26<br/>(embeds and runs the script)"]
    SCRIPT["GroundwaterChemistryDatabasePROD_updated.py"]

    RAW["GroundwaterChemistry_GWCDrawdata<br/>RAW_DATA_TABLE<br/>full, unfiltered, ungeocoded mirror"]
    GEOCODE["Clean / standardize / geocode<br/>(address match → else town centroid<br/>→ else tagged, not dropped)"]
    POINTS["GroundwaterChemistry_GWCDPoints<br/>POINTS_FEATURE_CLASS<br/>every record, exceedance calcs applied"]
    EXTERNAL["GroundwaterChemistry_GWCDPointTableExternal<br/>EXTERNAL_PUBLIC_TABLE<br/>filtered + deduplicated + small-sample suppressed"]

    AGS["ArcGIS Server REST service<br/>(reads EXTERNAL_PUBLIC_TABLE live, no caching)"]
    PUBLIC_APP["Public Experience Builder app<br/>'Drinking Water Quality'<br/>(Private Drinking Water Quality page only —<br/>its other 2 pages are an unrelated DEC/Power BI pipeline)"]
    INTERNAL_APP["Internal Experience Builder app<br/>'Drinking Water Quality - Internal'<br/>(staff-only group)"]

    PIVOT["AGOL CSV item<br/>PivotedGroundwaterData<br/>(long-to-wide, internal analysis only)"]
    EXCLUDED["AGOL CSV item<br/>GroundwaterChemistry_ExcludedRecords<br/>(geocode failures + town-centroid-only records)"]
    SHAREPOINT["SharePoint list<br/>'LatestDataUpdate' field"]
    EMAIL["Weekly exceedance alert email<br/>(separate hardcoded threshold set, 7-day window)"]

    SQL --> FME --> SCRIPT
    SCRIPT --> RAW
    RAW --> GEOCODE --> POINTS
    POINTS --> EXTERNAL
    POINTS --> PIVOT
    POINTS --> EXCLUDED
    EXTERNAL --> AGS --> PUBLIC_APP
    RAW --> INTERNAL_APP
    POINTS --> INTERNAL_APP
    EXTERNAL --> INTERNAL_APP
    SCRIPT --> SHAREPOINT
    SCRIPT --> EMAIL
```

## Reading this diagram

- **One source, one script, six destinations.** Everything downstream of
  `groundwater.ChemistryResults` is produced by a single weekly script run — there
  is no other process that writes to any of the GWCD tables/items/apps shown here
  (the only other FME workspace that touches `GroundwaterChemistry_GWCDPoints`,
  `EnvHealthGroundwaterChemistryDataPivotExport.fmw`, is a separate read-only
  export to an FME Server shared-resource CSV, not part of this pipeline, and is
  intentionally out of scope for this doc set).
- **`GroundwaterChemistry_GWCDPoints` is the hub.** It's the only table that feeds
  the public-facing path (via `EXTERNAL_PUBLIC_TABLE`), both internal-review CSVs,
  and the Internal app directly.
- **The public app and the Internal app read different tables**, not the same
  table with different filters applied client-side: the public app's ArcGIS
  Server service reads `EXTERNAL_PUBLIC_TABLE` live and dynamically (no caching —
  a data refresh is visible within one request), while the Internal app's three
  layers read `RAW_DATA_TABLE`, `POINTS_FEATURE_CLASS`, and
  `EXTERNAL_PUBLIC_TABLE` directly.
- **The two AGOL CSV exports and the weekly email are side channels** — none of
  them feed either Experience Builder app. They exist for internal
  analysis/review and staff notification only.
