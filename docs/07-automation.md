# Automation: How This Actually Runs

This pipeline is **not** triggered by a Windows Task Scheduler job calling
`python.exe` directly. It runs via **FME Flow** (the rebranded FME Server), and
the mechanism is unusual enough to be worth documenting explicitly, because it
is not obvious from reading the `.py` file alone.

## The FME workspace is a wrapper, not a transformer pipeline

`EnvHealthGroundwaterChemistryData.fmw` (repository `AHS_VDH_GroundwaterChemistry`
on the FME Flow server) has essentially no transformer graph. Its entire job is
a **workspace-level Startup Python Script** (the `BEGIN_PYTHON`/`END_PYTHON`
workspace property, set via FME Workbench's Workspace Properties → Scripting
tab) that contains a **complete, embedded copy of the whole
`GroundwaterChemistryDatabasePROD_updated.py` file**, ending in the same
`if __name__ == "__main__": main()` guard. FME executes a workspace's startup
script as `__main__`, so that guard fires normally and `main()` runs for real.

**Practical implication**: editing the `.py` file on disk, by itself, does
**not** change what the weekly job runs. The embedded copy inside the `.fmw`
file has to be re-synced (re-pasted into the workspace's Startup Python Script
and re-published to FME Flow) before a change takes effect in production. As
of this writing the embedded copy has been diff-checked against the on-disk
`GroundwaterChemistryDatabasePROD_updated.py` and found to be byte-for-byte in
sync — but this is a point-in-time fact, not a guarantee, and there is no
automated sync between the two. **Always verify the embedded copy is current
before relying on an on-disk edit having taken effect.**

## Schedule configuration (as of this writing)

| Setting | Value |
|---|---|
| Schedule name | `AHS_VDH_GroundWaterChemistryWeekly` |
| Enabled | Yes |
| Recurrence | Weekly, Saturdays at 21:26, no end date |
| Repository / Workspace | `AHS_VDH_GroundwaterChemistry` / `EnvHealthGroundwaterChemistryData.fmw` |
| Skip if Job In Progress | **No** (unchecked) — if a run ever overruns past the next Saturday, FME would allow a second run to start concurrently. Relevant given this script writes to SDE tables with real lock-contention risk under concurrent access. |
| Success/failure notification topics | None configured — FME Flow itself will not alert anyone if the job fails. The only failure signal is the weekly exceedance alert email, plus the script's own internal try/except-and-warn handling around the SharePoint and AGOL publish steps at the very end. |

## A separate, unrelated FME workspace exists in the same folder

`EnvHealthGroundwaterChemistryDataPivotExport.fmw` (repository `Automation`) is
a **genuinely different** FME workspace with a real transformer graph: it reads
directly from `GDB_ENVHEALTH_ADMIN.GroundwaterChemistry_GWCDPoints` via its own
SDE reader and writes a CSV to FME Server's shared-resource folder
(`$(FME_SHAREDRESOURCE_DATA)`), not to ArcGIS Online. It appears to be a
parallel/independent pivot export, distinct from this script's own
`publish_pivoted_csv_to_agol()` step. It has not been investigated in depth
(no confirmed trigger/schedule found for it yet) and is intentionally out of
scope for the rest of this doc set — see [00-architecture.md](00-architecture.md)
for why it's excluded from the architecture diagram.
