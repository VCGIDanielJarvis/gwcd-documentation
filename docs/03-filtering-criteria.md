# Filtering Criteria

This is the scope filter applied before exceedance calculation and
aggregation (`calculationSelection` in the production script). Any dashboard
computing exceedance/detection rates from this data should apply the same
filter to stay aligned with the public map.

## Qualitative description

- **Valid result required**: excludes records where `Result` or
  `WHCombinedResult` indicate the sample wasn't validly tested (rejected,
  error, not tested, no data, etc.) — case-insensitive, NULL-safe (a NULL is
  allowed through here; it's excluded later if it has no usable numeric
  value).
- **Private water only**: excludes `WaterSource` values of public, surface,
  lake/pond, river, stream, or municipal. Keeps private wells, dug wells,
  springs, and unknown.
- **Non-institutional clients only**: excludes `ClientName` values indicating
  schools, daycares/childcare, academies, UVM/UVMMC, VT Agency of Agriculture,
  VDH internal lab/proficiency/quarterly testing, environmental health, etc.
- **Non-institutional sampling location**: same idea, applied to
  `SamplingLocationDescription` (school/daycare/VDH laboratory language).
- **Pre-treatment only**: excludes `PostTreatmentSample = 'Y'` (i.e., samples
  taken after a water treatment system — only raw/untreated water counts).

All of the above are NULL-safe: a NULL in any of these fields does **not**
exclude the record (only an explicit disqualifying value does).

## Pseudo-code

```
INCLUDE record IF:
    (Result IS NULL OR LOWER(Result) NOT IN [
        "rejected", "na", "n/a", "rejection", "no data", "nd",
        "not tested", "nda", "error", "see attached", ""
    ])
    AND (WHCombinedResult IS NULL OR LOWER(WHCombinedResult) NOT IN [same list as above])
    AND (WaterSource IS NULL OR LOWER(WaterSource) NOT IN [
        "public", "surface", "lake/pond", "river", "stream", "municipal"
    ])
    AND (ClientName IS NULL OR LOWER(ClientName) NOT IN [
        "learning", "school", "elem", "elementary", "daycare", "childcare",
        "district", "childhood", "uvmmc", "vt agriculture environmental lab",
        "early ed", "uvm-", "uvm", "city market", "vt agency of agriculture",
        "vdh quarterly", "vdh lab", "vdh laboratory", "vdh bottle", "uhs",
        "child care", "environmental health", "childrens", "academy"
    ])
    AND (SamplingLocationDescription IS NULL OR LOWER(SamplingLocationDescription) NOT IN [
        "learning", "school", "elem", "elementary", "daycare", "childcare",
        "district", "childhood", "uvmmc", "early ed", "uvm-", "vdh laboratory"
    ])
    AND (PostTreatmentSample IS NULL OR LOWER(PostTreatmentSample) = "n")
```

## Analyte name normalization

Applied before any grouping, so dashboard groupings match the public map's
analyte categories:

```
AnalyteAlias = LOOKUP(LOWER(TRIM(AnalyteName)), analyte_alias_dictionary)
    e.g. "arsenic total" -> "Arsenic"
         "nitrate as n"  -> "Nitrate"
         "radon-222"     -> "Radon"
         "uranium total" -> "Uranium"
         "e. coli"       -> "E.coli"
         "coliforms"     -> "Total Coliform"
IF no match: AnalyteAlias = NULL   # record excluded from analyte/town grouping
```

Full dictionary is in the sanitized script (`analyteDictionary`).

## Deduplication (applied after the above filter, before aggregation)

```
GROUP filtered records BY (ConcatAddress, AnalyteAlias, TOWNNAME)
KEEP the record with:
    the HIGHEST ResultCalc value
    (tie-break: most recent ReportedDateTime)
DISCARD all other records in the group
```

## Suppression (public output only)

```
FOR each (AnalyteAlias, TOWNNAME) group:
    SUPPRESS from public output IF sample count < 20
```

This suppression is only applied to `GroundwaterChemistry_GWCDPointTableExternal`
(the public map's source table) — `GroundwaterChemistry_GWCDPoints` retains the
unsuppressed counts, and is the better source for grant-reporting /
state-level aggregation.
