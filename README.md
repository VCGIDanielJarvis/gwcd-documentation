# Groundwater Chemistry Database (GWCD) — Documentation

This repo documents the data source, ETL pipeline, and public-facing product for Vermont's
**private drinking water** groundwater chemistry data. It exists so that other teams
(e.g. grant-reporting / outreach dashboards) can build on the same data without
re-deriving filtering and exceedance logic from scratch.

**Live product:** [Drinking Water Quality](https://experience.arcgis.com/experience/dbed7d7f37ff4927a8edda677696b7c4) (ArcGIS Experience Builder app, public)

## Contents

| Doc | What's in it |
|---|---|
| [docs/01-data-source.md](docs/01-data-source.md) | Where the raw data comes from, the tables involved |
| [docs/02-etl-pipeline.md](docs/02-etl-pipeline.md) | Step-by-step walkthrough of the weekly ETL script |
| [docs/03-filtering-criteria.md](docs/03-filtering-criteria.md) | Record inclusion/exclusion rules, with pseudo-code |
| [docs/04-exceedance-calculations.md](docs/04-exceedance-calculations.md) | How exceedance rates are calculated, threshold table, with pseudo-code |
| [docs/05-geocoding.md](docs/05-geocoding.md) | How records get a town assignment; geocoded vs. non-geocodable data |
| [docs/06-application.md](docs/06-application.md) | What the public app actually displays, confirmed against its live config |
| [scripts/GroundwaterChemistryDatabasePROD.sanitized.py](scripts/GroundwaterChemistryDatabasePROD.sanitized.py) | Sanitized copy of the production ETL script (credentials/internal hostnames redacted) |

## TL;DR

- **Source**: `groundwater.ChemistryResults` (SQL Server), loaded weekly into
  `GroundwaterChemistry_GWCDrawdata` (full, unfiltered, ungeocoded).
- **Scope**: private drinking water wells/springs only (public/municipal water
  sources are excluded), Vermont addresses only.
- **Output tables**:
  - `GroundwaterChemistry_GWCDPoints` — all records that pass the quality/scope
    filters, geocoded (address or town-centroid fallback), with exceedance flags
    and per-town/analyte summary stats.
  - `GroundwaterChemistry_GWCDPointTableExternal` — the above, further deduplicated
    per location and with town/analyte combinations under 20 samples suppressed.
    This is what feeds the public app.
- **Public app** currently surfaces 6 analytes: Arsenic, Fluoride, Gross Alpha,
  Nitrate, Radon, Uranium.
- Script owner of record: originally Victoria Treto, rewritten 2025-03-24 by
  Daniel Jarvis. Runs weekly via `GroundwaterChemistryDatabasePROD.py`.

## Who to contact

AHS GIS & Data Viz team: ADS.VCGIAHSTechs@vermont.gov
