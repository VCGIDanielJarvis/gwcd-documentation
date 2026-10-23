# Exceedance Calculations

## Threshold types

Each analyte is checked against up to four benchmark types:

| Type | Meaning |
|---|---|
| **MCL** | Maximum Contaminant Level (legally enforceable, federal/state drinking water standard) |
| **SMCL** | Secondary MCL (aesthetic — taste, odor, staining — not a health standard) |
| **VHA** | Vermont Health Advisory |
| **Threshold** | A general health-based advisory/action level, used where no MCL/SMCL/VHA applies |

A `None`/blank value for a given type means that benchmark doesn't apply to
that analyte.

## Threshold table (as hardcoded in the script)

| Analyte | MCL | SMCL | VHA | Threshold |
|---|---|---|---|---|
| Arsenic | 0.010 mg/L | — | — | 0.001 mg/L |
| Fluoride | 4.000 mg/L | 2.000 mg/L | — | 0.700 mg/L |
| Gross Alpha | 15 pCi/L | — | — | 5 |
| Nitrate | 10 mg/L | — | 5 | 0 |
| Nitrite | 1 mg/L | — | — | 0 |
| Total Nitrate and Nitrite | 10 mg/L | — | — | 5 |
| Sodium | — | 250 mg/L | — | 15 |
| Chloride | — | 250 mg/L | — | 50 |
| Manganese | — | 0.05 mg/L | 0.3 mg/L | 0.08 mg/L |
| Lead | 0.015 mg/L | — | 0.001 mg/L | — |
| Iron | — | 0.3 mg/L | — | — |
| Copper | 1.3 mg/L | 1 mg/L | 1.3 mg/L | — |
| Radon | — | — | 4,000 pCi/L | — |
| Uranium | 0.03 mg/L | — | 0.02 mg/L | — |
| Radium | 5 | — | — | — |
| TDS | — | 500 mg/L | — | — |
| Turbidity | — | — | — | 1 |
| Odor | — | 3 | — | — |
| E.coli | 0 (presence) | — | — | 0 (presence) |
| Total Coliform | — | — | — | 0 (presence) |
| pH | — | 6.5–8.5 (range) | — | — |
| Hardness | — | — | — | 75–151 (range) |

> Note: pH's SMCL and Hardness's Threshold are **ranges** — a result outside
> the range is "above" (flagged), not just a result over a single number.

## Result value used for exceedance math (`ResultCalc`)

Unit conversions are applied first:

```
IF AnalyteAlias == "Uranium" AND unit == "ug/L":  numeric_result *= 0.001;   unit = "mg/L"
IF AnalyteAlias == "Uranium" AND unit == "pCi/L": numeric_result *= 0.00149; unit = "mg/L"
IF AnalyteAlias == "Chloride" AND unit == "ug/L": numeric_result *= 0.001;   unit = "mg/L"
```

Then, non-detects are handled by using half the reporting limit (a standard
convention), except for a few analytes with special presence/absence logic:

```
IF ResultType == "<" (non-detect) AND AnalyteAlias NOT IN ["Total Coliform", "E.coli", "Hardness"]:
    ResultCalc = ReportingLimit / 2   IF ReportingLimit IS NOT NULL ELSE NULL (excluded from exceedance calc)
ELSE:
    ResultCalc = numeric_result
```

## Exceedance flag logic (per record, per threshold type)

```
thresholds = LOOKUP(AnalyteAlias, threshold_table)   # (MCL, SMCL, VHA, Threshold)

FOR each threshold_type IN [MCL, SMCL, VHA, Threshold]:
    limit = thresholds[threshold_type]
    IF limit IS NULL:        flag = NULL   # not applicable to this analyte
    ELIF ResultCalc IS NULL: flag = NULL   # can't determine (e.g. non-detect, no reporting limit)
    ELIF ResultCalc > limit: flag = 1      # Above
    ELSE:                    flag = 0      # At/Below
```

Special cases layered on top of the general logic above:

```
# pH (SMCL is a range):
flag = 1 IF ResultCalc < 6.5 OR ResultCalc > 8.5 ELSE 0

# Hardness (Threshold is a range):
flag = 1 IF ResultCalc < 75 OR ResultCalc > 151 ELSE 0

# E.coli / Total Coliform: if no numeric result, fall back to qualitative result
IF ResultCalc IS NULL:
    flag = 1 IF WHResultValueAlpha IN ["Present", "Detected"]
    flag = 0 IF WHResultValueAlpha IN ["Absent", "Not detected"]
    flag = NULL otherwise
```

## Town/analyte aggregation (public map + summary tables)

```
GROUP deduplicated records BY (AnalyteAlias, TOWNNAME)

FOR each group:
    CityCount = COUNT(records with a non-null Result)
    FOR each threshold_type:
        CityAbove[type] = SUM(flag == 1)
        PctAbove[type]  = CityAbove[type] / CityCount * 100
    Mean, Median, Min, Max, 95th Percentile, StdDev = stats(ResultCalc) for the group
    # rounding precision varies by analyte (e.g. Arsenic/Nitrate to 4 decimals,
    # Fluoride to 3, Gross Alpha/Radon to 1, Uranium to 6)

SUPPRESS group from public output IF CityCount < 20
```
