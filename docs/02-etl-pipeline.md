# ETL Pipeline Walkthrough

Source: `GroundwaterChemistryDatabasePROD.py` (runs weekly). Line numbers below
refer to the sanitized copy in [scripts/](../scripts/GroundwaterChemistryDatabasePROD.sanitized.py).

## 1. Load raw data

Truncate and reload `GroundwaterChemistry_GWCDrawdata` from
`groundwater.ChemistryResults` (straight column copy, no filtering).

## 2. Weekly exceedance email alert

Filters the last 7 days of records against a fixed set of per-analyte
concentration thresholds (metals, VOCs, BNAs, PCBs, herbicides, PFOS/PFAS) and
emails a CSV + HTML summary to an internal distribution list. This is a
notification tool, separate from the public map/dashboard data below.

## 3. Data cleaning

- Zip code fixes (leading zeros, dash artifacts).
- `WaterSource` normalization (e.g. "dug well" → "Dug Well"; unrecognized
  values backfilled from `SamplingLocationDescription` where possible,
  otherwise set to "Unknown").
- Town name cleanup via the alias table (typos/out-of-state variants mapped to
  a canonical municipality where known).
- `AnalyteName` → `AnalyteAlias` standardization (e.g. "arsenic total" →
  "Arsenic").

## 4. Geocoding

- Addresses are concatenated (`Address1, City, VT, Zip`) and geocoded against
  the state's E911 composite locator.
- Records that fail to geocode an address are retried using **just the town
  name**, geocoded to a **town centroid**.
- Records that fail both are dropped from the geocoded/mapped product (they
  still exist in the raw table from step 1).
- All geocoded points (address-level + centroid fallback) are spatially joined
  to town boundaries to assign `TOWNNAME`.

See [05-geocoding.md](05-geocoding.md) for details and what this means for
state- vs. town-level analysis.

## 5. Scope filter

Before any exceedance math, records are restricted to the private drinking
water scope: valid/non-error results, private well/spring water sources only
(excludes public/municipal/surface water), non-institutional clients (schools,
daycares, VDH internal proficiency tests excluded), and non-post-treatment
samples. Full logic in [03-filtering-criteria.md](03-filtering-criteria.md).

## 6. Exceedance calculation

Per record, per applicable threshold type (MCL / SMCL / VHA / general
Threshold), flag whether the result is above or below. Non-detects are
represented as half the reporting limit. Full logic in
[04-exceedance-calculations.md](04-exceedance-calculations.md).

## 7. Deduplication

For a given (Address, Analyte, Town) combination, only one record is kept —
the highest result (ties broken by most recent report date). This prevents
repeat testing at one location from skewing town-level statistics.

## 8. Town/analyte aggregation

Grouped by (`AnalyteAlias`, `TOWNNAME`), compute: sample count, count/percent
above each threshold type, and mean/median/min/max/95th percentile/standard
deviation of the result value.

## 9. Write outputs

- Full set (deduplicated, with stats) → `GroundwaterChemistry_GWCDPoints`.
- Public set → `GroundwaterChemistry_GWCDPointTableExternal`: same data, with
  town/analyte groups under 20 samples suppressed, and extra
  human-readable popup fields generated (`MapMean`, `MapPopupHeading`, etc.)
  for 6 specific analytes (Arsenic, Fluoride, Gross Alpha, Nitrate, Radon,
  Uranium) — see [06-application.md](06-application.md).

## 10. Housekeeping

Rebuilds table indexes, updates a "last data refresh" timestamp in a
SharePoint list (via Microsoft Graph API), and publishes a pivoted
(long-to-wide) CSV export of all results to ArcGIS Online for internal use.
