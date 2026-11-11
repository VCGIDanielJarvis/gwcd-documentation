# ============================================================================
# SANITIZED COPY - for documentation purposes only.
# Internal server/SDE connection paths, credential file paths, and staff email
# addresses have been redacted/replaced with placeholders below. This is not a
# runnable copy of the production script. See ../docs/ for a guided walkthrough
# of this logic.
# ============================================================================

"""
Title:
Groundwater Chemistry Database Private Drinking Water Application Script

File Name:
GroundwaterChemistryDatabasePROD_updated.py

Description:
This script runs on a weekly basis to maintain and update the public-facing web
application that displays private drinking water exceedances by town and analyte.
Along the way it also:
  - mirrors raw lab results from SQL Server into an internal SDE table,
  - emails a weekly "did anything exceed a safety threshold in the last 7 days" report,
  - geocodes and cleans up sample locations, standardizes analyte/town/water-source names,
  - computes per-record and per-town/analyte exceedance statistics,
  - publishes the internal (full) and external (public, suppressed) results to SDE,
  - updates a "data last refreshed" date on a SharePoint list, and
  - republishes a long-to-wide pivoted CSV export to ArcGIS Online.

Changelog:
01/23/23  - Created - Victoria Treto
11/01/23  - Finalized - Victoria Treto
3/24/2025 - Rewritten - Daniel Jarvis
11/09/2026 - Rewritten for readability and maintainability, at Daniel Jarvis's request:
    - Reorganized the whole script into small, documented functions instead of one long
      linear script.
    - Consolidated the two copies of the "exclude school/daycare/public-water-system/
      rejected-result" filter into one shared function. The two copies had quietly drifted
      apart (one excluded WHCombinedResult = 'error in result', the other didn't), so a
      record in that state could skip the exceedance calculation step but still end up
      published. Both places now call build_published_record_filter_clause().
    - Added basic error handling around the SharePoint and ArcGIS Online publish steps at
      the very end of the script. Those are not critical to the main data pipeline, so a
      transient network hiccup there now prints a warning and moves on instead of crashing
      the whole job and hiding the fact that everything before it already succeeded.
    - Moved the Azure AD app credentials out of the script and into a creds file
      (azureCredsFile below), matching the existing pattern used for the AGO credentials.
      NOTE: this is a stopgap - the plan is to move all creds files into KeePass later.
    - Accepted a brief "table is empty" window during the nightly refresh (delete-then-
      append) as a known, acceptable tradeoff since this job only runs overnight.

-------------------------------------------------------------------------------------
OPEN ITEMS (carried over from the previous version of this script - still not resolved):

- For recorduid = 507051, in the final points dataset, SamplePhysicalAddressCity is set to
  "Athens", but the joined TOWNNAME / TOWNNAMEMC comes back as "Townshend". This needs to
  be investigated - there are other examples like this.

- To Do / Get Kristine:
    - a list of all analytes and the labs they come from
    - a list of records with other problems, like addresses
    - more

- "ADDED MUNICIPAL TO THE WATER SOURCE FILTER" - is this ok to remove?
-------------------------------------------------------------------------------------

WHAT THIS SCRIPT PRODUCES / UPDATES (final destinations - see also the per-step comments
inside main() below for which step updates which of these):

- SDE table GDB_ENVHEALTH_ADMIN.GroundwaterChemistry_GWCDrawdata (RAW_DATA_TABLE)
    Full, unfiltered mirror of the SQL Server source - every raw lab record, nothing
    filtered or geocoded yet. Feeds the "Raw Data (GWCD) - Internal" layer in the
    Internal experience below.

- SDE feature class GDB_ENVHEALTH_ADMIN.GroundwaterChemistry_GWCDPoints (POINTS_FEATURE_CLASS)
    Every record, geocoded where possible (tagged instead of dropped where it isn't),
    with exceedance calculations applied. Feeds the "Geocoded GWCD Points - Internal"
    layer in the Internal experience below, and is the source table for both the
    pivoted CSV export and the excluded-records report.

- SDE table GDB_ENVHEALTH_ADMIN.GroundwaterChemistry_GWCDPointTableExternal (EXTERNAL_PUBLIC_TABLE)
    Filtered, small-sample-suppressed, town/analyte summary table. Feeds BOTH the
    "Analyte Data - External" layer in the Internal experience AND the live public
    ArcGIS Server service backing the Public experience below. This table is read live
    and dynamically with no caching - changes here are visible to the public within
    one request, no lag.

- ArcGIS Online item "PivotedGroundwaterData" (CSV, "AHS_VDH_EnvHealth_GroundwaterInternal"
  folder)
    Long-to-wide pivoted export of POINTS_FEATURE_CLASS, for internal analysis only -
    not used by either experience below.

- ArcGIS Online item "GroundwaterChemistry_ExcludedRecords" (CSV,
  "AHS_VDH_EnvHealth_GroundwaterInternal" folder)
    Every record whose address did not geocode to a real street-level match: records
    that failed to geocode entirely, and records that only reached their town's centroid
    (lower spatial precision; these still count toward the public map's statistics). For
    privileged internal review of geocoding precision only - not used by either
    experience below.

- SharePoint list item, "LatestDataUpdate" field, Groundwater Chemistry application
  domain (AHS.GISAdministrationGroup site, list id in SHAREPOINT_LIST_ID)
    Lets staff see at a glance when this data was last refreshed.

- Internal Experience Builder app, "Drinking Water Quality - Internal" (private,
  staff-only group):
    https://experience.arcgis.com/experience/860a6e275d9c4f72aa2acc138e0a0880
  Shows the full, unfiltered internal picture: raw data, full geocoded points
  (including records that failed to geocode), and the external/analyte summary layer.

- Public Experience Builder app, "Drinking Water Quality" (public, ~18k views):
    https://experience.arcgis.com/experience/dbed7d7f37ff4927a8edda677696b7c4
  IMPORTANT: this app has three pages, and only ONE of them is fed by this script -
  "Private Drinking Water Quality" (the 6 analyte tabs: Arsenic, Fluoride, Gross Alpha,
  Nitrate, Radon, Uranium). The other two pages, "System Level Public Drinking Water
  Quality" and "State Level Public Drinking Water Quality", are embedded Power BI
  reports on an entirely separate VT DEC public-water-system data pipeline - this
  script has no effect on them whatsoever.
-------------------------------------------------------------------------------------
"""

# ----------------------------------- Module Imports ----------------------------
import arcpy
from collections import defaultdict
import numpy as np
from datetime import datetime, timedelta
import os
import requests
import pandas as pd
import tempfile
import zipfile
from arcgis.gis import GIS, ItemProperties, ItemTypeEnum
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import io
import csv
import html


# =====================================================================================
# CONFIGURATION - data sources, destinations, and other settings.
# These external paths/names/schemas must stay exactly as-is: other applications
# (ArcGIS Server map services, two public ArcGIS Experience Builder apps, and a
# SharePoint list) read directly from these tables and fields.
# =====================================================================================

GIS_EDITOR_CONNECTION = "<SDE_CONNECTION_PATH>/EnvHealth_PROD_Editor.sde"

RAW_DATA_TABLE = f"{GIS_EDITOR_CONNECTION}/GDB_ENVHEALTH_ADMIN.GroundwaterChemistry_GWCDrawdata"
TOWN_ALIAS_TABLE = f"{GIS_EDITOR_CONNECTION}/GDB_ENVHEALTH_ADMIN.GroundwaterChemistryAliasTable"
POINTS_FEATURE_CLASS = f"{GIS_EDITOR_CONNECTION}/GDB_ENVHEALTH_ADMIN.GroundwaterChemistry_GWCDPoints"
EXTERNAL_PUBLIC_TABLE = f"{GIS_EDITOR_CONNECTION}/GDB_ENVHEALTH_ADMIN.GroundwaterChemistry_GWCDPointTableExternal"
TOWN_BOUNDARIES = f"{GIS_EDITOR_CONNECTION}/GDB_ENVHEALTH_ADMIN.GroundwaterChemistry_TownBounds"

SQL_SOURCE_DATABASE = "<SDE_CONNECTION_PATH>/<SQL_CONNECTION_FILE>.sde"
SQL_SOURCE_TABLE = f"{SQL_SOURCE_DATABASE}/groundwater.ChemistryResults"

E911_GEOCODER_URL = "https://maps.vcgi.vermont.gov/arcgis/rest/services/EGC_services/GCS_E911_COMPOSITE_SP_v2/GeocodeServer/GCS_E911_COMPOSITE_SP_v2"

AGO_CREDS_FILE = "<REDACTED_CREDENTIALS_FILE_PATH>"

# format is: client_id,client_secret,tenant_id
AZURE_CREDS_FILE = "<REDACTED_CREDENTIALS_FILE_PATH>"

EMAIL_SENDER = "<REDACTED_SENDER_ADDRESS>"
EMAIL_RECIPIENTS = [
    "<REDACTED_RECIPIENT_1>",
    "<REDACTED_RECIPIENT_2>",
    "<REDACTED_RECIPIENT_3>",
    "<REDACTED_RECIPIENT_4>",
]

SHAREPOINT_SITE_URL = "vermontgov.sharepoint.com:/teams/AHS.GISAdministrationGroup"
SHAREPOINT_LIST_ID = "<REDACTED_LIST_ID>"
SHAREPOINT_APPLICATION_DOMAIN = "Groundwater Chemistry"

AGOL_PORTAL_URL = "https://ahs-vt.maps.arcgis.com/"
PIVOTED_CSV_ITEM_TITLE = "PivotedGroundwaterData"
# The AGOL folder that both CSV items (PivotedGroundwaterData and
# GroundwaterChemistry_ExcludedRecords) live in.
PIVOTED_CSV_FOLDER_NAME = "AHS_VDH_EnvHealth_GroundwaterInternal"


# -------------------------------------------------------------------------------------
# Thresholds used for the WEEKLY EXCEEDANCE ALERT EMAIL (a separate, independent system
# from the public-map exceedance thresholds further down - they cover different analytes
# and serve a different purpose: a fast "something looks bad, go look at it" email).
# -------------------------------------------------------------------------------------

WEEKLY_ALERT_METALS_THRESHOLDS_MG_L = {
    "Barium": 5,
    "Cadmium": 0.005,
    "Chromium": 0.1,
    "Mercury": 0.002,
    "Selenium": 0.05,
    "Silver": 0.1,
    "Antimony": 0.006,
    "Beryllium": 0.004,
    "Nickel": 0.021,
    "Thallium": 0.002,
    "Zinc": 5,
}

# -------------------------------------------------------------------------------------
# Thresholds used for the PUBLIC MAP exceedance calculations (per analyte):
#   mcl       = Maximum Contaminant Level (federal/state enforceable limit)
#   smcl      = Secondary MCL (aesthetic/nuisance limit, not health based)
#   vha       = Vermont Health Advisory level
#   threshold = Vermont's own "pay attention" level, usually lower than the MCL
# A value of None means that limit doesn't apply to that analyte.
# pH's "smcl" and Hardness's "threshold" are a (low, high) acceptable range instead of a
# single cutoff - those two are handled as a special case in calculate_result_and_exceedances().
# -------------------------------------------------------------------------------------

EXCEEDANCE_THRESHOLDS_BY_ANALYTE = {
    "Arsenic":                  {"mcl": 0.010, "smcl": None,       "vha": None,  "threshold": 0.001},
    "Fluoride":                 {"mcl": 4.000, "smcl": 2.000,      "vha": None,  "threshold": 0.700},
    "Gross Alpha":              {"mcl": 15,    "smcl": None,       "vha": None,  "threshold": 5},
    "Nitrate":                  {"mcl": 10,    "smcl": None,       "vha": 5,     "threshold": 0},
    "Nitrite":                  {"mcl": 1,     "smcl": None,       "vha": None,  "threshold": 0},
    "Total Nitrate and Nitrite": {"mcl": 10,   "smcl": None,       "vha": None,  "threshold": 5},
    "Sodium":                   {"mcl": None,  "smcl": 250,        "vha": None,  "threshold": 15},
    "Chloride":                 {"mcl": None,  "smcl": 250,        "vha": None,  "threshold": 50},
    "Manganese":                {"mcl": None,  "smcl": 0.05,       "vha": 0.3,   "threshold": 0.08},
    "Lead":                     {"mcl": 0.015, "smcl": None,       "vha": 0.001, "threshold": None},
    "Iron":                     {"mcl": None,  "smcl": 0.3,        "vha": None,  "threshold": None},
    "Copper":                   {"mcl": 1.3,   "smcl": 1,          "vha": 1.3,   "threshold": None},
    "Radon":                    {"mcl": None,  "smcl": None,       "vha": 4000,  "threshold": None},
    "Uranium":                  {"mcl": 0.03,  "smcl": None,       "vha": 0.02,  "threshold": None},
    "Radium":                   {"mcl": 5,     "smcl": None,       "vha": None,  "threshold": None},
    "TDS":                      {"mcl": None,  "smcl": 500,        "vha": None,  "threshold": None},
    "Turbidity":                {"mcl": None,  "smcl": None,       "vha": None,  "threshold": 1},
    "Odor":                     {"mcl": None,  "smcl": 3,          "vha": None,  "threshold": None},
    "E.coli":                   {"mcl": 0,     "smcl": None,       "vha": None,  "threshold": 0},
    "Total Coliform":           {"mcl": None,  "smcl": None,       "vha": None,  "threshold": 0},
    "pH":                       {"mcl": None,  "smcl": (6.5, 8.5), "vha": None,  "threshold": None},
    "Hardness":                 {"mcl": None,  "smcl": None,       "vha": None,  "threshold": (75, 151)},
}

# Analytes that get their own tab/map on the public "Private Drinking Water Quality" app,
# plus the plain-language threshold label and non-detect display settings for each one's
# map popup. "exceedance_type" says which of the CityAbove.../PctAbove... fields on the
# published table actually represents "above the limit" for that analyte.
PUBLIC_MAP_ANALYTE_SETTINGS = {
    "Arsenic":     {"exceedance_type": "MCL",       "threshold_label": "MCL (0.010 mg/L)",   "non_detect_display_threshold": 0.001, "units": "mg/L"},
    "Fluoride":    {"exceedance_type": "Threshold",  "threshold_label": "PHS (0.7 mg/L)",     "non_detect_display_threshold": 0.3,   "units": "mg/L"},
    "Gross Alpha": {"exceedance_type": "MCL",       "threshold_label": "MCL (15 pCi/L)",     "non_detect_display_threshold": 1.50,  "units": "pCi/L"},
    "Nitrate":     {"exceedance_type": "MCL",       "threshold_label": "MRL (10 mg/L)",      "non_detect_display_threshold": 0.5,   "units": "mg/L"},
    "Radon":       {"exceedance_type": "VHA",       "threshold_label": "VHA (4,000 pCi/L)",  "non_detect_display_threshold": 100,   "units": "pCi/L"},
    "Uranium":     {"exceedance_type": "VHA",       "threshold_label": "VMCL (0.020 mg/L)",  "non_detect_display_threshold": 0.001, "units": "mg/L"},
}

# Standardizes messy free-text "water source" values down to a short, consistent set.
WATER_SOURCE_STANDARDIZATION = {
    "drilled well": "Drilled Well",
    "dug well": "Dug Well",
    "other": "Unknown",
    "not reported by client": "Unknown",
    "well": "Well",
    "spring": "Spring",
    "unknown": "Unknown",
}

# Standardizes messy free-text "analyte name" values down to a short, consistent set used
# everywhere downstream (public map tabs, exceedance thresholds, popups, etc). Anything not
# in this dictionary is left with AnalyteAlias blank and gets filtered out before publish.
ANALYTE_NAME_STANDARDIZATION = {
    "arsenic": "Arsenic", "arsenic total": "Arsenic",
    "sulfate": "Sulfate",
    "fluoride": "Fluoride",
    "total dissolved": "TDS", "tds": "TDS",
    "gross alpha": "Gross Alpha",
    "total nitrate/nitrite": "Total Nitrate and Nitrite",
    "nitrate & nitrite": "Total Nitrate and Nitrite",
    "nitrate and nitrite as no3": "Total Nitrate and Nitrite",
    "total nitrate and nitrite as n": "Total Nitrate and Nitrite",
    "nitrate": "Nitrate", "nitrate as n": "Nitrate",
    "nitrite": "Nitrite", "nitrite as n": "Nitrite",
    "sodium": "Sodium",
    "chloride": "Chloride",
    "manganese": "Manganese",
    "lead": "Lead",
    "iron": "Iron",
    "copper": "Copper",
    "radon": "Radon", "radon-222": "Radon", "radon in water": "Radon",
    "uranium": "Uranium", "uranium total": "Uranium",
    "radium": "Radium", "radium-226": "Radium", "radium-228": "Radium", "radium-226/228": "Radium",
    "e. coli": "E.coli", "e.coli": "E.coli", "escherichia": "E.coli",
    "coliform": "Total Coliform", "coliforms": "Total Coliform",
    "turbidity": "Turbidity",
    "hardness": "Hardness",
    "odor": "Odor",
    "ph": "pH",
}

# Maps each SQL Server source column name to its (sometimes truncated) destination field
# name in the SDE raw-data table. Most names match exactly; a handful of the
# "SampleLocationPhysicalAddress..." fields are truncated to fit a 32-character field-name
# limit on the destination side.
SQL_TO_SDE_FIELD_MAP = {
    'AdditionalEmail': 'AdditionalEmail', 'AnalysisType': 'AnalysisType',
    'AnalyteName': 'AnalyteName', 'AnalyzedAmount': 'AnalyzedAmount',
    'AnalyzedAmountUnit': 'AnalyzedAmountUnit', 'AnalyzedDateTime': 'AnalyzedDateTime',
    'CAS_RegistryNumber': 'CAS_RegistryNumber', 'Chlorinated': 'Chlorinated',
    'ClientEmail': 'ClientEmail', 'ClientMailingAddressCity': 'ClientMailingAddressCity',
    'ClientMailingAddressLine1': 'ClientMailingAddressLine1', 'ClientMailingAddressLine2': 'ClientMailingAddressLine2',
    'ClientMailingAddressState': 'ClientMailingAddressState', 'ClientMailingAddressZip': 'ClientMailingAddressZip',
    'ClientName': 'ClientName', 'ClientNotes': 'ClientNotes',
    'ClientPhoneNumber': 'ClientPhoneNumber', 'Composite': 'Composite',
    'DilutionFactor': 'DilutionFactor', 'FileName': 'FileName',
    'FilePosition': 'FilePosition', 'InsertDate': 'InsertDate',
    'InsertUser': 'InsertUser', 'LabCertificationExpirationDate': 'LabCertificationExpirationDate',
    'LabContact': 'LabContact', 'LabContactEmail': 'LabContactEmail',
    'LabMailingAddressCity': 'LabMailingAddressCity', 'LabMailingAddressLine1': 'LabMailingAddressLine1',
    'LabMailingAddressLine2': 'LabMailingAddressLine2', 'LabMailingAddressState': 'LabMailingAddressState',
    'LabMailingAddressZip': 'LabMailingAddressZip', 'LabName': 'LabName',
    'LabQualifiersDefinition': 'LabQualifiersDefinition', 'LastUpdateDate': 'LastUpdateDate',
    'LastUpdateUser': 'LastUpdateUser', 'PostTreatmentSample': 'PostTreatmentSample',
    'Preservative': 'Preservative', 'QualifiersAndNotes': 'QualifiersAndNotes',
    'ReceivedDateTime': 'ReceivedDateTime', 'Record_uid': 'Record_uid',
    'RejectionReason': 'RejectionReason', 'ReportType': 'ReportType',
    'ReportedDateTime': 'ReportedDateTime', 'ReportingLimit': 'ReportingLimit',
    'ReportingLimitType': 'ReportingLimitType', 'ReportingLimitUnit': 'ReportingLimitUnit',
    'Result': 'Result', 'ResultType': 'ResultType', 'ResultUncertainty': 'ResultUncertainty',
    'ResultUnit': 'ResultUnit', 'SPAN': 'SPAN', 'SampleAmount': 'SampleAmount',
    'SampleAmountUnit': 'SampleAmountUnit', 'SampleCollectionDateTime': 'SampleCollectionDateTime',
    'SampleCollector': 'SampleCollector', 'SampleFinishTime': 'SampleFinishTime',
    'SampleFinishVolume': 'SampleFinishVolume', 'SampleFinishVolumeUnit': 'SampleFinishVolumeUnit',
    'SampleLatitude': 'SampleLatitude', 'SampleLatitudeLongitudeFormat': 'SampleLatitudeLongitudeFormat',
    'SampleLocationPhysicalAddressCity': 'SampleLocationPhysicalAddressCi',
    'SampleLocationPhysicalAddressLine1': 'SampleLocationPhysicalAddress1',
    'SampleLocationPhysicalAddressLine2': 'SampleLocationPhysicalAddress2',
    'SampleLocationPhysicalAddressState': 'SampleLocationPhysicalAddressSt',
    'SampleLocationPhysicalAddressZip': 'SampleLocationPhysicalAddressZi',
    'SampleLongitude': 'SampleLongitude', 'SampleStartTime': 'SampleStartTime',
    'SampleStartVolume': 'SampleStartVolume', 'SampleStartVolumeUnit': 'SampleStartVolumeUnit',
    'SampleTemperature': 'SampleTemperature', 'SampleTemperatureUnit': 'SampleTemperatureUnit',
    'SampleVolume': 'SampleVolume', 'SampleVolumeUnit': 'SampleVolumeUnit',
    'SampleWeight': 'SampleWeight', 'SampleWeightUnit': 'SampleWeightUnit',
    'SamplingLocationDescription': 'SamplingLocationDescription',
    'SubcontractedResults': 'SubcontractedResults', 'TestMethodCode': 'TestMethodCode',
    'TestMethodName': 'TestMethodName', 'Test_id': 'Test_id',
    'VT_StateLab_id': 'VT_StateLab_id', 'VT_WellTag_id': 'VT_WellTag_id',
    'WHCombinedResult': 'WHCombinedResult', 'WHResultType': 'WHResultType',
    'WHResultUncertainty': 'WHResultUncertainty', 'WHResultValueAlpha': 'WHResultValueAlpha',
    'WHResultValueNumeric': 'WHResultValueNumeric', 'WaterSource': 'WaterSource', 'pH': 'pH',
}

# Fields kept on the final, flattened external/public summary table (everything else is
# dropped before publish).
EXTERNAL_PUBLIC_TABLE_FIELDS = (
    "AnalyteAlias;TOWNNAME;TOWNNAMEMC;CityCount;CityAboveMCL;CityAboveSMCL;CityAboveVHA;"
    "CityAboveThreshold;PctAboveMCL;PctAboveSMCL;PctAboveVHA;PctAboveThreshold;Mean;Median;"
    "Min_;Max_;Percentile95;StdDev"
)

# -------------------------------------------------------------------------------------
# These four lists are the actual "what gets excluded from publish" business rules,
# shared by build_published_record_filter_clause() below (which turns them into a SQL
# where-clause). Keeping them as one shared set of Python values, instead of writing the
# rule twice (once in SQL, once elsewhere), means the two can never drift apart.
# -------------------------------------------------------------------------------------
REJECTED_RESULT_TEXT_VALUES = (
    "rejected", "na", "n/a", "rejection", "no data", "nd", "not tested",
    "nda", "error", "error in result", "see attached", "",
)
EXCLUDED_WATER_SOURCE_VALUES = ("public", "surface", "lake/pond", "river", "stream", "municipal")
EXCLUDED_CLIENT_NAME_VALUES = (
    "learning", "school", "elem", "elementary", "daycare", "childcare",
    "district", "childhood", "uvmmc", "vt agriculture environmental lab",
    "early ed", "uvm-", "uvm", "city market", "vt agency of agriculture",
    "vdh quarterly", "vdh lab", "vdh laboratory", "vdh bottle", "uhs",
    "child care", "environmental health", "childrens", "academy",
)
EXCLUDED_SAMPLING_LOCATION_DESCRIPTION_VALUES = (
    "learning", "school", "elem", "elementary", "daycare", "childcare",
    "district", "childhood", "uvmmc", "early ed", "uvm-", "vdh laboratory",
)

# Marker prefix written into the (reused, not-a-real-schema-change) ConcatAddress field
# for records that could not be geocoded at all, so they stay visible in the internal
# points table instead of being silently dropped. Matches the existing convention of
# using ConcatAddress to carry "<town> Centroid" and "DELETE" markers.
GEOCODE_EXCLUSION_MARKER_PREFIX = "EXCLUDED - "
GEOCODE_EXCLUSION_OUT_OF_STATE_MARKER = f"{GEOCODE_EXCLUSION_MARKER_PREFIX}Out of State Address, Not Geocoded"
GEOCODE_EXCLUSION_NOT_GEOCODED_MARKER = f"{GEOCODE_EXCLUSION_MARKER_PREFIX}Address Could Not Be Geocoded"

EXCLUDED_RECORDS_REPORT_ITEM_TITLE = "GroundwaterChemistry_ExcludedRecords"


# =====================================================================================
# CREDENTIALS
# =====================================================================================

def read_comma_separated_credentials_file(file_path):
    """
    Reads a small text file containing comma-separated credential values (for example
    "username,password" or "client_id,client_secret,tenant_id") and returns them as a
    list of strings. This is the same simple format already used for the AGO credentials
    file, and is now also used for the Azure AD credentials file below. It is a stopgap -
    the plan is to move these into KeePass later instead of a plain text file.
    """
    with open(file_path, "r") as creds_file:
        return creds_file.read().strip().split(",")


# =====================================================================================
# STEP 1 - Mirror raw lab results from SQL Server into the SDE raw-data table.
# =====================================================================================

def refresh_raw_data_table(sql_source_table, raw_data_table, field_map):
    """
    Copies every row from the SQL Server chemistry results table into the SDE raw-data
    table, mapping each source column to its (sometimes truncated) destination field name.
    The destination table is fully cleared first and then reloaded from scratch, so this
    is a complete refresh rather than an incremental update. There is a brief window where
    the raw-data table is empty while this runs; that's an accepted tradeoff since the job
    only runs overnight.

    This deliberately uses a plain row-by-row cursor loop rather than a bulk Append/
    FieldMappings copy, even though that's slower at this table's size (roughly three
    quarters of a million rows). Record_uid - the field this table is keyed on - has no
    registered primary key on the SQL Server side, so arcpy auto-promotes it to serve as
    that view's surrogate Object ID. Any tool that assigns/recognizes an OID (TableToTable,
    Append with a field mapping) consumes Record_uid for that role instead of copying it as
    an ordinary attribute, silently producing blank or collapsed values. A plain SearchCursor/
    InsertCursor asks for it by name with no OID reinterpretation, which is the only
    approach confirmed to copy it correctly - this was found and verified the hard way
    while testing a bulk-Append version of this function.
    """
    arcpy.management.DeleteRows(raw_data_table)

    source_field_names = list(field_map.keys())
    destination_field_names = list(field_map.values())

    with arcpy.da.InsertCursor(raw_data_table, destination_field_names) as insert_cursor:
        with arcpy.da.SearchCursor(sql_source_table, source_field_names) as search_cursor:
            for row in search_cursor:
                insert_cursor.insertRow(row)


# =====================================================================================
# STEP 2 - Weekly exceedance alert email.
# This looks back 7 days for lab results that cross a safety threshold and emails a
# summary report. It is a separate, independent check from the public-map exceedance
# calculations further down - it runs against the raw data, before any geocoding, town
# matching, or name standardization happens.
# =====================================================================================

def build_metals_exceedance_filter(metals_thresholds_mg_l):
    """
    Builds the SQL fragment that matches any metals result at or above its safety
    threshold, given a dictionary of {analyte name: threshold in mg/L}. Every metal uses
    the same comparison shape (unit must be mg/L, result type must be an exact "=", and
    the result must be at or above the threshold), so this builds all of them from one
    small loop instead of repeating the same fragment by hand for each metal.
    """
    metal_filter_fragments = []
    for analyte_name, threshold_mg_l in metals_thresholds_mg_l.items():
        fragment = (
            f"(AnalyteName LIKE '%{analyte_name}%' AND ResultUnit = 'mg/L' "
            f"AND CAST(Result AS FLOAT) >= {threshold_mg_l} AND ResultType = '=')"
        )
        metal_filter_fragments.append(fragment)
    return metal_filter_fragments


def build_weekly_alert_where_clause():
    """
    Builds the full SQL where-clause used by the weekly exceedance alert email. It combines
    a handful of general data-quality filters (Vermont address only, no "rejected"/"error"
    results, excludes VDH lab proficiency test records, last 7 days only) with a set of
    contaminant-specific filters covering metals, VOCs, BNAs, PCBs, herbicides, and
    PFOS/PFAS, each matched by test method code or name.
    """
    seven_days_ago = datetime.now() - timedelta(days=7)
    seven_days_ago_sql = seven_days_ago.strftime("%Y-%m-%d %H:%M:%S")

    general_filters = [
        "(UPPER(SampleLocationPhysicalAddressSt) IN ('VT','VERMONT','VTG','VT 0','VR','VRT',"
        "'WATERV','0','q','EEEEEEEEEEEEE','VTP','VTT','VST','V','VTD','```','VGT','VERM',"
        "'AAAAAAAAAAAAA') OR SampleLocationPhysicalAddressSt = '' OR SampleLocationPhysicalAddressSt IS NULL)",

        "(Result IS NULL OR (LOWER(Result) NOT LIKE '%not tested%' "
        "AND LOWER(Result) NOT LIKE '%error in result%' AND LOWER(Result) NOT LIKE '%rejected%' "
        "AND LOWER(Result) NOT LIKE '%rejection%' AND LOWER(Result) NOT LIKE '%error%' "
        "AND LOWER(Result) NOT LIKE '%fail%' AND LOWER(Result) NOT LIKE '%complete%'))",

        "(ClientName IS NULL OR LOWER(ClientName) NOT LIKE '%vdh lab proficiency%')",

        f"SampleCollectionDateTime >= timestamp '{seven_days_ago_sql}'",
    ]

    metals_filters = build_metals_exceedance_filter(WEEKLY_ALERT_METALS_THRESHOLDS_MG_L)

    # VOCs, BNAs, PCBs, herbicides, and PFOS/PFAS are all identified the same way: by test
    # method code or name containing a known method number, with a numeric (non-percent)
    # result unit and an exact ("=") result type. PFOS/PFAS additionally excludes blanks.
    vocs_filter = (
        "((TestMethodCode LIKE '%524%' OR TestMethodName LIKE '%524%' "
        "OR TestMethodCode LIKE '%551%' OR TestMethodName LIKE '%551%') "
        "AND (ResultUnit IS NULL OR ResultUnit NOT LIKE '%!%%' ESCAPE '!') AND ResultType = '=')"
    )
    bnas_filter = (
        "((TestMethodCode LIKE '%525%' OR TestMethodName LIKE '%525%') "
        "AND (ResultUnit IS NULL OR ResultUnit NOT LIKE '%!%%' ESCAPE '!') AND ResultType = '=')"
    )
    pcbs_filter = (
        "((TestMethodCode LIKE '%505%' OR TestMethodCode LIKE '%508%' "
        "OR TestMethodName LIKE '%505%' OR TestMethodName LIKE '%508%') "
        "AND (ResultUnit IS NULL OR ResultUnit NOT LIKE '%!%%' ESCAPE '!') AND ResultType = '=')"
    )
    herbicides_filter = (
        "((TestMethodCode LIKE '%515%' OR TestMethodCode LIKE '%552%' "
        "OR TestMethodName LIKE '%515%' OR TestMethodName LIKE '%552%') "
        "AND (ResultUnit IS NULL OR ResultUnit NOT LIKE '%!%%' ESCAPE '!') AND ResultType = '=')"
    )
    pfas_filter = (
        "((TestMethodCode LIKE '%533%' OR TestMethodCode LIKE '%537%' "
        "OR TestMethodName LIKE '%533%' OR TestMethodName LIKE '%537%') "
        "AND (ResultUnit IS NULL OR ResultUnit NOT LIKE '%!%%' ESCAPE '!') AND ResultType = '=' "
        "AND (SamplingLocationDescription IS NULL OR UPPER(SamplingLocationDescription) NOT LIKE '%BLANK%'))"
    )

    contaminant_filters = (
        f"({' OR '.join(metals_filters)} OR {vocs_filter} OR {bnas_filter} "
        f"OR {pcbs_filter} OR {herbicides_filter} OR {pfas_filter})"
    )

    return f"({' AND '.join(general_filters)}) AND ({contaminant_filters})"


def classify_contaminant_group(analyte_name, test_method_code, test_method_name):
    """
    Figures out which broad contaminant group a lab result belongs to (Metals, PFOS/PFAS,
    VOCs, BNAs, PCBs, Herbicides, or Other), based on the analyte name or the test method
    code/name. Used to label rows in the weekly exceedance alert email.
    """
    test_method_code = test_method_code or ""
    test_method_name = test_method_name or ""

    metal_analyte_names = list(WEEKLY_ALERT_METALS_THRESHOLDS_MG_L.keys())
    if any(metal_name in analyte_name for metal_name in metal_analyte_names):
        return "Metals"

    if "533" in test_method_code or "537" in test_method_code or "533" in test_method_name or "537" in test_method_name:
        return "PFOS/PFAS"
    if "524" in test_method_code or "524" in test_method_name or "551" in test_method_code or "551" in test_method_name:
        return "VOCs"
    if "525" in test_method_code or "525" in test_method_name:
        return "BNAs"
    if "505" in test_method_code or "508" in test_method_code or "505" in test_method_name or "508" in test_method_name:
        return "PCBs"
    if "515" in test_method_code or "552" in test_method_code or "515" in test_method_name or "552" in test_method_name:
        return "Herbicides"
    return "Other"


def send_email_notification(html_body, email_sender, email_recipients, csv_text=None, csv_attachment_filename=None):
    """
    Sends an HTML email, with an optional CSV file attached, through the department's SMTP
    relay. Used for both the weekly exceedance alert ("here are N records that need a
    look") and the "no exceedances this week" all-clear message.
    """
    try:
        message = MIMEMultipart()
        message["Subject"] = "|| Automated Alert || - Weekly Groundwater Chemistry Analyte Exceedance Report"
        message["From"] = email_sender
        message["To"] = ", ".join(email_recipients)
        message.attach(MIMEText(html_body, "html"))

        if csv_text and csv_attachment_filename:
            csv_attachment = MIMEApplication(csv_text.encode("utf-8"), Name=csv_attachment_filename)
            csv_attachment["Content-Disposition"] = f'attachment; filename="{csv_attachment_filename}"'
            message.attach(csv_attachment)

        smtp_server = smtplib.SMTP("relay.state.vt.us")
        smtp_server.sendmail(email_sender, email_recipients, message.as_string())

        if csv_attachment_filename:
            print(f"Summary email with CSV attachment '{csv_attachment_filename}' sent successfully.")
        else:
            print("Email sent successfully.")
    except Exception as error:
        print(f"Failed to send email: {error}")


def run_weekly_exceedance_alert(raw_data_memory_table, email_sender, email_recipients):
    """
    Looks back 7 days for lab results that cross a safety threshold (metals, VOCs, BNAs,
    PCBs, herbicides, or PFOS/PFAS) and emails a summary. If nothing was found, sends a
    short "all clear" email instead. This runs against the raw, not-yet-geocoded data, so
    the only fields available are whatever came straight from the lab.
    """
    where_clause = build_weekly_alert_where_clause()

    fields = [
        "AnalyteName", "Result", "ResultUnit", "SampleLocationPhysicalAddress1",
        "SampleLocationPhysicalAddressCi", "SampleCollectionDateTime", "ClientName",
        "TestMethodCode", "TestMethodName", "ResultType", "Record_uid",
    ]

    alert_records = []
    with arcpy.da.SearchCursor(raw_data_memory_table, fields, where_clause) as cursor:
        for row in cursor:
            analyte_name, result, result_unit, address, city, sample_date, client_name, \
                test_method_code, test_method_name, result_type, record_uid = row
            contaminant_group = classify_contaminant_group(analyte_name, test_method_code, test_method_name)
            alert_records.append(list(row) + [contaminant_group])

    if not alert_records:
        print("No records found matching the alert criteria in the last 7 days.")
        body = f"""
        <html><body>
        <p>- Weekly Groundwater Chemistry Analyte Exceedance Report -</p>
        <p>Hello,</p>
        <p>No analyte exceedances were found for the 7 day period ending on {datetime.now().strftime('%Y-%m-%d')}.</p>
        <p>Contact the AHS GIS & Data Viz team for questions: ADS.VCGIAHSTechs@vermont.gov.</p>
        <p>Thank you.</p>
        </body></html>
        """
        send_email_notification(body, email_sender, email_recipients)
        return

    # Sort newest sample first. SampleCollectionDateTime is index 5; contaminant group was
    # appended as the last column.
    alert_records.sort(key=lambda record: record[5] if record[5] else datetime.min, reverse=True)

    csv_output = io.StringIO()
    csv_writer = csv.writer(csv_output)
    csv_writer.writerow([
        "Classification", "Analyte", "ResultType", "Result", "Unit", "Client", "Sample_Date",
        "Location", "City", "TestMethodName", "TestMethodCode", "Record_uid",
    ])

    def format_html_cell(value):
        return html.escape(str(value)) if value else "N/A"

    html_table_rows = ""
    for record in alert_records:
        analyte_name, result, result_unit, address, city, sample_date, client_name, \
            test_method_code, test_method_name, result_type, record_uid, contaminant_group = record
        sample_date_text = sample_date.strftime("%Y-%m-%d") if sample_date else ""

        csv_writer.writerow([
            contaminant_group, analyte_name, result_type, result, result_unit, client_name,
            sample_date_text, address, city, test_method_name, test_method_code, record_uid,
        ])

        html_table_rows += (
            f"<tr><td>{format_html_cell(contaminant_group)}</td><td>{format_html_cell(analyte_name)}</td>"
            f"<td>{format_html_cell(result_type)}</td><td>{format_html_cell(result)}</td>"
            f"<td>{format_html_cell(result_unit)}</td><td>{format_html_cell(client_name)}</td>"
            f"<td>{sample_date_text or 'N/A'}</td><td>{format_html_cell(address)}</td>"
            f"<td>{format_html_cell(city)}</td><td>{format_html_cell(test_method_name)}</td>"
            f"<td>{format_html_cell(test_method_code)}</td><td>{format_html_cell(record_uid)}</td></tr>\n"
        )

    html_table = (
        "<table border='1' cellspacing='0' cellpadding='5'>\n"
        "<tr><th>Classification</th><th>Analyte</th><th>ResultType</th><th>Result</th><th>Unit</th>"
        "<th>Client</th><th>Sample Date</th><th>Location</th><th>City</th>"
        "<th>TestMethodName</th><th>TestMethodCode</th><th>Record_uid</th></tr>\n"
        f"{html_table_rows}</table>\n"
    )

    body = f"""
    <html><body>
    <p>- Weekly Groundwater Chemistry Analyte Exceedance Report -</p>
    <p>Hello,</p>
    <p>Analyte exceedances found for <b>{len(alert_records)}</b> record(s) in the last 7 days ending on {datetime.now().strftime('%Y-%m-%d')}.</p>
    <p>The attached CSV file contains a downloadable copy of this data.</p>
    {html_table}
    <p>Contact the AHS GIS & Data Viz team for questions: ADS.VCGIAHSTechs@vermont.gov.</p>
    <p>Thank you.</p>
    </body></html>
    """

    today_text = datetime.now().strftime("%Y-%m-%d")
    attachment_filename = f"Groundwater_Exceedance_Report_{today_text}.csv"
    send_email_notification(body, email_sender, email_recipients, csv_output.getvalue(), attachment_filename)
    csv_output.close()


# =====================================================================================
# STEP 3 - Clean up sample locations and geocode them to map points.
# =====================================================================================

def fix_zip_codes(memory_table):
    """
    Cleans up a handful of known zip code formatting problems in the raw data: zip codes
    that were entered with a leading dash instead of a zero, zip codes that were entered
    starting with "1" where "0" was meant, and zip codes that are missing their leading
    zero entirely (Vermont zips all start with 0).
    """
    dash_prefix_selection = arcpy.management.SelectLayerByAttribute(
        memory_table, "NEW_SELECTION", "SampleLocationPhysicalAddressZi LIKE '-%'")
    arcpy.management.CalculateField(
        dash_prefix_selection, "SampleLocationPhysicalAddressZi",
        "!SampleLocationPhysicalAddressZi!.replace('-','0')")

    leading_one_selection = arcpy.management.SelectLayerByAttribute(
        memory_table, "NEW_SELECTION", "SampleLocationPhysicalAddressZi LIKE '1%'")
    arcpy.management.CalculateField(
        leading_one_selection, "SampleLocationPhysicalAddressZi",
        "'0' + !SampleLocationPhysicalAddressZi![1:5]")

    missing_leading_zero_selection = arcpy.management.SelectLayerByAttribute(
        memory_table, "NEW_SELECTION",
        "SampleLocationPhysicalAddressZi NOT LIKE '0%' "
        "AND SampleLocationPhysicalAddressZi NOT IN ('NA','VT','Not Report','Well')")
    arcpy.management.CalculateField(
        missing_leading_zero_selection, "SampleLocationPhysicalAddressZi",
        "'0' + !SampleLocationPhysicalAddressZi!")


def standardize_water_source_values(memory_table, water_source_standardization):
    """
    Standardizes the free-text "water source" field down to a short, consistent set of
    values (Drilled Well, Dug Well, Well, Spring, or Unknown). When the source is a vague
    catch-all value like "Other" or "Not Reported By Client", this also checks the
    sampling-location description field for a more specific answer before giving up and
    calling it Unknown.
    """
    vague_source_values = ("other", "not reported by client", "none")
    specific_source_values = ("drilled well", "dug well", "well", "spring")

    with arcpy.da.UpdateCursor(memory_table, ["WaterSource", "SamplingLocationDescription"]) as cursor:
        for row in cursor:
            water_source = str(row[0]).lower().strip()
            location_description = str(row[1]).lower().strip()

            if water_source in vague_source_values:
                matched_source = next(
                    (source for source in specific_source_values if source == location_description), None)
                row[0] = water_source_standardization[matched_source] if matched_source else "Unknown"
            elif water_source in water_source_standardization:
                row[0] = water_source_standardization[water_source]
            # otherwise leave the value as-is

            cursor.updateRow(row)


def build_town_alias_lookup(town_alias_table):
    """
    Builds a lookup dictionary that maps a lowercase town name (including known misspellings
    and out-of-state towns) to its correct, standardized municipality name. Historically,
    many SampleLocationPhysicalAddressCi values from labs turned out to be typos, out-of-state
    towns bordering Vermont, or ambiguous placeholders - this table of known exceptions was
    built up over time to correct them rather than discard the records outright. It would be
    better to validate this at data-entry time, but that hasn't happened yet.
    """
    alias_lookup = {}
    with arcpy.da.SearchCursor(town_alias_table, ["Municipality", "Town", "Alias"]) as cursor:
        for municipality, town, alias_list in cursor:
            if town.lower() not in alias_lookup:
                alias_lookup[town.lower()] = municipality
            if municipality.lower() not in alias_lookup:
                alias_lookup[municipality.lower()] = municipality
            if alias_list is not None:
                for alias in alias_list.split(","):
                    if alias not in alias_lookup:
                        alias_lookup[alias.lower()] = municipality
    return alias_lookup


def apply_town_aliases(memory_table, town_alias_lookup):
    """
    Walks every record and, where possible, replaces a messy/misspelled town name with its
    standardized municipality name using the lookup built by build_town_alias_lookup().
    Also blanks out a few fields when they come back as database NULL, so downstream string
    operations (like the address concatenation used for geocoding) don't choke on None.
    """
    fields = ["SampleLocationPhysicalAddress1", "SampleLocationPhysicalAddressCi", "SampleLocationPhysicalAddressZi"]
    with arcpy.da.UpdateCursor(memory_table, fields) as cursor:
        for row in cursor:
            address, town, zip_code = row
            if address is None:
                row[0] = ""
            elif town is None:
                row[1] = ""
            elif zip_code is None:
                row[2] = ""

            if town is not None and town.lower() in town_alias_lookup:
                row[1] = town_alias_lookup[town.lower()]

            cursor.updateRow(row)


def standardize_analyte_names(memory_table, analyte_name_standardization):
    """
    Adds the AnalyteAlias field and populates it with a standardized analyte name wherever
    the raw AnalyteName matches a known variant (for example "Arsenic Total" becomes
    "Arsenic"). Records whose analyte isn't recognized are left with a blank AnalyteAlias,
    and get filtered out later before anything is published.
    """
    arcpy.management.AddField(memory_table, "AnalyteAlias", "TEXT", "", "", 200, "AnalyteAlias")
    with arcpy.da.UpdateCursor(memory_table, ["AnalyteName", "AnalyteAlias"]) as cursor:
        for row in cursor:
            analyte_name = str(row[0]).lower().strip()
            if analyte_name in analyte_name_standardization:
                row[1] = analyte_name_standardization[analyte_name]
            cursor.updateRow(row)


def geocode_sample_locations(memory_table, geocoder_url):
    """
    Geocodes every sample location to an X/Y point using the state's E911 address locator.
    Builds a "street, city, VT, zip" address string for every record whose state is Vermont
    (or blank/unknown), geocodes those addresses, and then geocodes any records that still
    came back with no geometry a second time using just the town name, snapped to that
    town's centroid - so most records end up with *some* point on the map, even if it's
    only town-level precision.

    Records that still can't be geocoded after both passes (addresses from the handful of
    out-of-state codes that are never even attempted, or Vermont addresses that just don't
    match anything) are NOT discarded. They're kept with no geometry, and their
    ConcatAddress field - the same field already used to mark "<town> Centroid" and
    "DELETE" rows - is set to a plain-language "EXCLUDED - ..." reason instead, so a
    privileged user can later find and understand every record that never made it onto a
    map. Returns the path to the final geocoded feature class.
    """
    geocode_eligible_selection = arcpy.management.SelectLayerByAttribute(
        memory_table, "NEW_SELECTION",
        "SampleLocationPhysicalAddressSt NOT IN "
        "('TN','NH','KY','MA','ME','RI','MD','NJ','TX','CT','VA','NY')")
    address_concat_expression = (
        '!SampleLocationPhysicalAddress1!+", "!SampleLocationPhysicalAddressCi!+", VT, "+!SampleLocationPhysicalAddressZi!'
    )
    arcpy.management.CalculateField(geocode_eligible_selection, "ConcatAddress", address_concat_expression)
    arcpy.management.SelectLayerByAttribute(memory_table, "CLEAR_SELECTION")

    geocoded_points = "memory/geocodedAddresses"
    arcpy.geocoding.GeocodeAddresses(
        memory_table,
        address_locator=geocoder_url,
        in_address_fields="'Single Line Input' ConcatAddress VISIBLE NONE",
        out_feature_class=geocoded_points,
        out_relationship_type="STATIC",
        country=None, location_type="", category=None,
        output_fields="LOCATION_ONLY",
    )

    arcpy.management.Delete(memory_table)

    # Anything that didn't geocode to a real address gets a second pass, geocoded to its
    # town's centroid instead, so it still shows up somewhere on the map.
    ungeocoded_selection = arcpy.management.SelectLayerByAttribute(geocoded_points, "NEW_SELECTION", "SHAPE IS NULL")
    ungeocoded_records = "memory/FlattenedNullShapes"
    arcpy.conversion.TableToTable(ungeocoded_selection, "memory", "FlattenedNullShapes")
    arcpy.management.DeleteFeatures(ungeocoded_selection)

    town_centroid_points = "memory/geocodedTownCentroids"
    arcpy.geocoding.GeocodeAddresses(
        ungeocoded_records,
        address_locator=geocoder_url,
        in_address_fields="'Single Line Input' SampleLocationPhysicalAddressCi VISIBLE NONE",
        out_feature_class=town_centroid_points,
        out_relationship_type="STATIC",
        country=None, location_type="CENTROID", category=None,
        output_fields="LOCATION_ONLY",
    )
    geocoded_to_centroid_selection = arcpy.management.SelectLayerByAttribute(town_centroid_points, "NEW_SELECTION", "SHAPE IS NOT NULL")
    arcpy.management.CalculateField(geocoded_to_centroid_selection, "ConcatAddress", "!SampleLocationPhysicalAddressCi! ' Centroid'")

    # Still no geometry after both passes - keep the record, but mark why instead of
    # deleting it. Split confirmed out-of-state (never had a real address to try) from
    # everything else that simply didn't match anything. This has to be a NEW_SELECTION
    # for the out-of-state case followed by a SWITCH_SELECTION for "everything else that's
    # still null" - NOT a second explicit "NOT IN" clause - because SampleLocationPhysicalAddressSt
    # is blank/NULL for a large share of records, and in SQL "NULL NOT IN (list)" is
    # neither true nor false, so a second "NOT IN" clause would silently skip blank-state
    # records and leave them untagged.
    still_ungeocoded_out_of_state = arcpy.management.SelectLayerByAttribute(
        town_centroid_points, "NEW_SELECTION",
        "SHAPE IS NULL AND SampleLocationPhysicalAddressSt IN "
        "('TN','NH','KY','MA','ME','RI','MD','NJ','TX','CT','VA','NY')")
    arcpy.management.CalculateField(still_ungeocoded_out_of_state, "ConcatAddress", f"'{GEOCODE_EXCLUSION_OUT_OF_STATE_MARKER}'")

    still_ungeocoded_everything_else = arcpy.management.SelectLayerByAttribute(
        town_centroid_points, "NEW_SELECTION", "SHAPE IS NULL")
    still_ungeocoded_everything_else = arcpy.management.SelectLayerByAttribute(
        still_ungeocoded_everything_else, "REMOVE_FROM_SELECTION",
        "SampleLocationPhysicalAddressSt IN ('TN','NH','KY','MA','ME','RI','MD','NJ','TX','CT','VA','NY')")
    arcpy.management.CalculateField(still_ungeocoded_everything_else, "ConcatAddress", f"'{GEOCODE_EXCLUSION_NOT_GEOCODED_MARKER}'")

    arcpy.management.Append(town_centroid_points, geocoded_points)
    return geocoded_points


def clean_and_geocode_points(raw_data_memory_table, town_alias_table, town_boundaries):
    """
    Runs the full location-cleanup pipeline on the raw data: fixes zip codes, standardizes
    water source and analyte names, replaces messy town names with their standardized
    alias, geocodes every record to a point (falling back to a town centroid when a full
    address can't be geocoded), and finally spatially joins each point to the Vermont town
    it falls within. Returns the path to the resulting joined points feature class.
    """
    fix_zip_codes(raw_data_memory_table)
    standardize_water_source_values(raw_data_memory_table, WATER_SOURCE_STANDARDIZATION)

    town_alias_lookup = build_town_alias_lookup(town_alias_table)
    apply_town_aliases(raw_data_memory_table, town_alias_lookup)
    standardize_analyte_names(raw_data_memory_table, ANALYTE_NAME_STANDARDIZATION)

    geocoded_points = geocode_sample_locations(raw_data_memory_table, E911_GEOCODER_URL)

    joined_points = "memory/GWCDPoints_TownJoin"
    arcpy.analysis.SpatialJoin(
        geocoded_points, town_boundaries, joined_points,
        "JOIN_ONE_TO_ONE", "KEEP_ALL", "", "INTERSECT", "", "")
    arcpy.management.Delete(geocoded_points)

    return joined_points


# =====================================================================================
# STEP 4 - Filter out records that shouldn't be published, calculate per-record exceedance
# flags, de-duplicate, and roll up to town/analyte summary statistics.
# =====================================================================================

def _sql_in_list(values):
    """Turns a Python tuple of strings into a SQL 'a','b','c' list, quoted correctly."""
    return ",".join(f"'{value}'" for value in values)


def build_published_record_filter_clause():
    """
    Builds the SQL where-clause used to decide which records are allowed to be published
    at all (as opposed to kept only for internal exceedance calculations). This excludes
    rejected/invalid results, public/municipal water sources (this script is about PRIVATE
    drinking water), records from schools, daycares, and other institutional clients whose
    results aren't meaningful as "household drinking water" data, post-treatment samples,
    and records that could never be matched to a Vermont town (couldn't be geocoded at
    all, or landed outside every town boundary). This is the one filter clause shared by
    both the exceedance-calculation step and the final publish step below, so the two can
    never disagree with each other.

    Note: the IS NULL checks throughout are required - in SQL, NULL is never considered
    "in" or "not in" a list, so without them any record with a NULL value in one of these
    fields would be silently excluded even though it should pass.
    """
    return (
        f"(Result IS NULL OR lower(Result) NOT IN ({_sql_in_list(REJECTED_RESULT_TEXT_VALUES)})) AND "
        f"(WHCombinedResult IS NULL OR lower(WHCombinedResult) NOT IN ({_sql_in_list(REJECTED_RESULT_TEXT_VALUES)})) AND "
        f"(WaterSource IS NULL OR lower(WaterSource) NOT IN ({_sql_in_list(EXCLUDED_WATER_SOURCE_VALUES)})) AND "
        f"(ClientName IS NULL OR lower(ClientName) NOT IN ({_sql_in_list(EXCLUDED_CLIENT_NAME_VALUES)})) AND "
        f"(SamplingLocationDescription IS NULL OR lower(SamplingLocationDescription) NOT IN "
        f"({_sql_in_list(EXCLUDED_SAMPLING_LOCATION_DESCRIPTION_VALUES)})) AND "
        "(lower(PostTreatmentSample) = 'n' OR PostTreatmentSample IS NULL) AND "
        "(TOWNNAME IS NOT NULL)"
    )


def add_exceedance_calculation_fields(joined_points):
    """
    Adds the numeric fields used throughout the exceedance calculation step: a per-record
    Count flag, the ResultCalc value actually used for comparisons, and one Above.../flag
    field for each of the four threshold types (MCL, SMCL, VHA, and Vermont's own
    "Threshold" level).
    """
    for field_name in ("Count", "ResultCalc", "AboveMCL", "AboveSMCL", "AboveVHA", "AboveThreshold"):
        arcpy.management.AddField(joined_points, field_name, "DOUBLE")


def calculate_result_and_exceedances(selection, exceedance_thresholds):
    """
    For every selected record, this:
      1. Converts Uranium and Chloride results from micrograms/liter (or picocuries/liter,
         for Uranium) into milligrams/liter, so they're comparable to the thresholds below.
      2. Sets ResultCalc to the actual lab result, or - for a non-detect with a numeric
         reporting limit - to half the reporting limit (a standard way of estimating a
         "most likely" value for a result below the detection limit).
      3. Compares ResultCalc against that analyte's MCL/SMCL/VHA/Threshold limits and sets
         the corresponding AboveMCL/AboveSMCL/AboveVHA/AboveThreshold flag to 1 (above), 0
         (at or below), or leaves it as None (can't be determined, e.g. a non-detect with
         no numeric reporting limit).
    E.coli, Total Coliform, pH, and Hardness are handled as a special case afterward,
    since they're reported as present/absent text, a pH range, or a hardness range rather
    than a simple numeric exceedance.
    """
    fields = [
        "WHResultValueNumeric", "AnalyteAlias", "ResultUnit", "ReportingLimit", "ReportingLimitUnit",
        "Result", "Count", "ResultCalc", "WHResultType", "AboveMCL", "AboveSMCL", "AboveVHA",
        "AboveThreshold", "WHResultValueAlpha",
    ]

    unit_conversions = {
        ("Uranium", "ug/L"): ("mg/L", 0.001),
        ("Chloride", "ug/L"): ("mg/L", 0.001),
        ("Uranium", "pCi/L"): ("mg/L", 0.00149),
    }

    with arcpy.da.UpdateCursor(selection, fields) as cursor:
        for row in cursor:
            (result_value, analyte_name, result_unit, reporting_limit, reporting_limit_unit,
             result, count, result_calc, result_type, above_mcl, above_smcl, above_vha,
             above_threshold, result_value_alpha) = row

            count = None if result is None else 1

            conversion = unit_conversions.get((analyte_name, result_unit))
            if conversion:
                new_unit, factor = conversion
                result_value = result_value * factor
                result_unit = new_unit
                if reporting_limit is not None:
                    reporting_limit = reporting_limit * factor
                    reporting_limit_unit = new_unit

            # A non-detect ("<") uses half the reporting limit as a stand-in result value,
            # except for the three analytes handled as a special case below.
            if result_type == "<" and analyte_name not in ("Total Coliform", "E.coli", "Hardness"):
                if reporting_limit is not None:
                    result_calc = reporting_limit / 2
            else:
                result_calc = result_value

            if analyte_name in exceedance_thresholds and analyte_name not in ("Total Coliform", "E.coli", "Hardness", "pH"):
                thresholds = exceedance_thresholds[analyte_name]
                mcl, smcl, vha, threshold = thresholds["mcl"], thresholds["smcl"], thresholds["vha"], thresholds["threshold"]
                if result_calc:
                    above_mcl = 1 if mcl and result_calc > mcl else 0 if mcl and result_calc <= mcl else None
                    above_smcl = 1 if smcl and result_calc > smcl else 0 if smcl and result_calc <= smcl else None
                    above_vha = 1 if vha and result_calc > vha else 0 if vha and result_calc <= vha else None
                    above_threshold = 1 if threshold and result_calc > threshold else 0 if threshold and result_calc <= threshold else None

            elif analyte_name in ("E.coli", "Total Coliform", "pH", "Hardness"):
                thresholds = exceedance_thresholds[analyte_name]
                mcl, smcl, vha, threshold = thresholds["mcl"], thresholds["smcl"], thresholds["vha"], thresholds["threshold"]
                is_ecoli = analyte_name == "E.coli"
                is_total_coliform = analyte_name == "Total Coliform"
                is_ph = analyte_name == "pH"
                is_hardness = analyte_name == "Hardness"
                is_present_or_detected = result_value_alpha in {"Present", "Detected"}
                is_absent_or_not_detected = result_value_alpha in {"Absent", "Not detected"}
                is_equal_or_greater = result_type in {"=", ">"}
                is_less_than = result_type == "<"

                if mcl:
                    if result_calc is None:
                        if is_total_coliform:
                            above_mcl = 1 if is_present_or_detected else 0 if is_absent_or_not_detected else None
                    else:
                        if is_total_coliform:
                            above_mcl = (
                                1 if result_calc > mcl and is_equal_or_greater
                                else 0 if (result_calc == 1 and (is_equal_or_greater or is_less_than)) or (result_calc < mcl)
                                else None
                            )

                if smcl and result_calc is not None and is_ph:
                    above_smcl = 1 if result_calc < smcl[0] or result_calc > smcl[1] else 0 if smcl[0] <= result_calc <= smcl[1] else None

                if is_ecoli:
                    if result_calc is None:
                        above_mcl = 1 if is_present_or_detected else 0 if is_absent_or_not_detected else None
                    else:
                        above_mcl = 1 if result_calc > mcl and is_equal_or_greater else 0 if result_calc < mcl or is_less_than else None

                if is_total_coliform:
                    if result_calc is None:
                        above_threshold = 1 if is_present_or_detected else 0 if is_absent_or_not_detected else None
                    else:
                        above_threshold = (
                            1 if result_calc > threshold and is_equal_or_greater
                            else 0 if (result_calc == 1 and (is_equal_or_greater or is_less_than)) or (result_calc < threshold)
                            else None
                        )
                elif threshold and is_hardness and result_calc is not None:
                    above_threshold = 1 if result_calc < threshold[0] or result_calc > threshold[1] else 0 if threshold[0] <= result_calc <= threshold[1] else None
                else:
                    above_threshold = None

            cursor.updateRow((
                result_value, analyte_name, result_unit, reporting_limit, reporting_limit_unit,
                result, count, result_calc, result_type, above_mcl, above_smcl, above_vha,
                above_threshold, result_value_alpha,
            ))


def remove_duplicate_location_records(selection):
    """
    When the same address has more than one result for the same analyte, this keeps only
    one: the highest numeric result (or, for E.coli/Total Coliform without a numeric
    result, the one most recently reported that shows "above threshold"). Every other
    record for that address/analyte/town combination is marked for deletion by setting
    its ConcatAddress to "DELETE" (the caller is responsible for actually removing those
    rows afterward).
    """
    fields = ["ConcatAddress", "AnalyteAlias", "TOWNNAME", "ResultCalc", "Record_uid", "ReportedDateTime", "AboveThreshold"]
    best_record_by_location = {}

    with arcpy.da.SearchCursor(selection, fields) as cursor:
        for concat_address, analyte_name, town_name, result_calc, record_uid, reported_date, above_threshold in cursor:
            location_key = (concat_address, analyte_name, town_name)
            candidate = (result_calc, record_uid, reported_date, above_threshold)

            if location_key not in best_record_by_location:
                best_record_by_location[location_key] = candidate
                continue

            existing_result, existing_record_uid, existing_reported_date, existing_above_threshold = best_record_by_location[location_key]

            if result_calc is not None and existing_result is not None:
                if result_calc > existing_result:
                    best_record_by_location[location_key] = candidate
                elif result_calc == existing_result and reported_date and existing_reported_date and reported_date > existing_reported_date:
                    best_record_by_location[location_key] = candidate
            elif result_calc is not None:
                best_record_by_location[location_key] = candidate
            elif result_calc is None and analyte_name in ("Total Coliform", "E.coli"):
                if above_threshold == 1 and existing_above_threshold == 0:
                    best_record_by_location[location_key] = candidate
                elif above_threshold == 1 and existing_above_threshold == 1 and reported_date and existing_reported_date:
                    if reported_date > existing_reported_date:
                        best_record_by_location[location_key] = candidate

    record_uids_to_keep = {record_uid for _, record_uid, _, _ in best_record_by_location.values()}

    with arcpy.da.UpdateCursor(selection, ["Record_uid", "ConcatAddress"]) as cursor:
        for row in cursor:
            if row[0] not in record_uids_to_keep:
                row[1] = "DELETE"
                cursor.updateRow(row)


# Decimal places to round summary statistics to, per analyte. Chosen so that typical
# results for that analyte don't get rounded down to zero.
SUMMARY_STAT_ROUNDING_BY_ANALYTE = {
    "Arsenic": 4, "Fluoride": 3, "Gross Alpha": 1, "Nitrate": 4, "Radon": 1, "Uranium": 6,
}
DEFAULT_SUMMARY_STAT_ROUNDING = 6


def summarize_by_town_and_analyte(selection):
    """
    Rolls the (already de-duplicated) records up into one summary row per town/analyte
    combination: how many samples, how many and what percent were above each threshold
    type, and the mean/median/min/max/95th percentile/standard deviation of the results.
    Writes those summary values back onto every record sharing that town/analyte so the
    later flatten-and-publish step can pull a single representative row per combination.
    """
    all_field_names = [field.name for field in arcpy.ListFields(selection)]

    records_by_town_and_analyte = defaultdict(list)
    with arcpy.da.SearchCursor(selection, all_field_names) as cursor:
        for row in cursor:
            analyte_name = row[all_field_names.index("AnalyteAlias")]
            town_name = row[all_field_names.index("TOWNNAME")]
            if analyte_name is not None and town_name is not None:
                records_by_town_and_analyte[f"{analyte_name}|{town_name}"].append(row)

    def field_values(records, field_name):
        index = all_field_names.index(field_name)
        return [record[index] for record in records if record[index] is not None]

    summary_by_town_and_analyte = {}
    for key, records in records_by_town_and_analyte.items():
        result_values = field_values(records, "ResultCalc")
        if not result_values:
            continue

        above_mcl_values = field_values(records, "AboveMCL")
        above_smcl_values = field_values(records, "AboveSMCL")
        above_vha_values = field_values(records, "AboveVHA")
        above_threshold_values = field_values(records, "AboveThreshold")
        sample_counts = field_values(records, "Count")
        analyte_name = records[0][all_field_names.index("AnalyteAlias")]
        rounding = SUMMARY_STAT_ROUNDING_BY_ANALYTE.get(analyte_name, DEFAULT_SUMMARY_STAT_ROUNDING)
        total_samples = sum(sample_counts)

        summary_by_town_and_analyte[key] = {
            "CityCount": round(total_samples),
            "CityAboveMCL": round(sum(above_mcl_values)) if above_mcl_values else None,
            "CityAboveSMCL": round(sum(above_smcl_values)) if above_smcl_values else None,
            "CityAboveVHA": round(sum(above_vha_values)) if above_vha_values else None,
            "CityAboveThreshold": round(sum(above_threshold_values)) if above_threshold_values else None,
            "PctAboveMCL": round((sum(above_mcl_values) / total_samples) * 100, 1) if above_mcl_values else None,
            "PctAboveSMCL": round((sum(above_smcl_values) / total_samples) * 100, 1) if above_smcl_values else None,
            "PctAboveVHA": round((sum(above_vha_values) / total_samples) * 100, 1) if above_vha_values else None,
            "PctAboveThreshold": round((sum(above_threshold_values) / total_samples) * 100, 1) if above_threshold_values else None,
            "Mean": round(np.mean(result_values), rounding),
            "Median": round(np.median(result_values), rounding),
            "Min_": round(np.min(result_values), rounding),
            "Max_": round(np.max(result_values), rounding),
            "Percentile95": round(np.percentile(result_values, 95), rounding),
            "StdDev": round(np.std(result_values), rounding),
        }

    summary_field_names = [
        "CityCount", "CityAboveMCL", "CityAboveSMCL", "CityAboveVHA", "CityAboveThreshold",
        "PctAboveMCL", "PctAboveSMCL", "PctAboveVHA", "PctAboveThreshold",
        "Mean", "Median", "Min_", "Max_", "Percentile95", "StdDev",
    ]
    for field_name in summary_field_names:
        arcpy.management.AddField(selection, field_name, "DOUBLE")

    all_field_names = [field.name for field in arcpy.ListFields(selection)]
    with arcpy.da.UpdateCursor(selection, all_field_names) as cursor:
        for row in cursor:
            analyte_name = row[all_field_names.index("AnalyteAlias")]
            town_name = row[all_field_names.index("TOWNNAME")]
            if analyte_name is None or town_name is None:
                continue
            key = f"{analyte_name}|{town_name}"
            if key not in summary_by_town_and_analyte:
                continue
            for field_name in summary_field_names:
                row[all_field_names.index(field_name)] = summary_by_town_and_analyte[key][field_name]
            cursor.updateRow(row)


def calculate_exceedances_and_summaries(joined_points, record_filter_clause, exceedance_thresholds):
    """
    Runs the full exceedance-calculation pipeline on the geocoded/joined points: selects
    only the records allowed to be published, computes each record's ResultCalc value and
    MCL/SMCL/VHA/Threshold exceedance flags, removes duplicate records for the same
    address/analyte, and rolls everything up into town/analyte summary statistics. Returns
    the resulting selection, ready to be appended to the live points feature class.
    """
    add_exceedance_calculation_fields(joined_points)
    selection = arcpy.management.SelectLayerByAttribute(joined_points, "NEW_SELECTION", record_filter_clause)

    calculate_result_and_exceedances(selection, exceedance_thresholds)
    remove_duplicate_location_records(selection)
    summarize_by_town_and_analyte(selection)

    return selection


# =====================================================================================
# STEP 5 - Build the final, flattened external/public summary table and publish
# everything to SDE.
# =====================================================================================

def build_external_public_table(joined_points, record_filter_clause):
    """
    Starting from the calculated points, this removes any record that fails the shared
    publish filter (records marked "DELETE" by the de-duplication step are removed as a
    side effect of this, since they fail the filter in other ways too), trims the table
    down to just the town/analyte summary fields, removes duplicate town/analyte rows, and
    drops any record with a blank AnalyteAlias. The result is one row per town/analyte
    combination, ready to be turned into map-popup text. Returns the path to the flattened
    table.
    """
    excluded_selection = arcpy.management.SelectLayerByAttribute(joined_points, "NEW_SELECTION", record_filter_clause)
    excluded_selection = arcpy.management.SelectLayerByAttribute(excluded_selection, "SWITCH_SELECTION")
    arcpy.management.DeleteRows(excluded_selection)

    arcpy.management.DeleteField(joined_points, EXTERNAL_PUBLIC_TABLE_FIELDS, "KEEP_FIELDS")
    arcpy.management.DeleteIdentical(joined_points, EXTERNAL_PUBLIC_TABLE_FIELDS)

    layer_name = "joined_points_layer"
    arcpy.management.MakeFeatureLayer(joined_points, layer_name)
    arcpy.management.SelectLayerByAttribute(layer_name, "NEW_SELECTION", "AnalyteAlias = ''")
    arcpy.management.DeleteFeatures(layer_name)
    arcpy.management.Delete(layer_name)

    flattened_table = "memory/ExternalTableInMemory"
    arcpy.conversion.TableToTable(joined_points, "memory", "ExternalTableInMemory")
    arcpy.management.Delete(joined_points)
    return flattened_table


def add_map_popup_text(flattened_table, public_map_analyte_settings):
    """
    Adds the plain-language popup text fields used by the public map (MapMean, MapMedian,
    MapMin, MapMax, MapPercentile95, MapStdDev, MapMDL, and MapPopupHeading), and suppresses
    any town/analyte combination with fewer than 20 samples by deleting that row entirely -
    this is the one safeguard between a small, potentially identifiable sample size and the
    public map, so it needs to stay in place. Values below the lab's typical reporting
    limit are shown as "*" with a footnote, rather than a precise number that implies more
    precision than the lab actually measured.
    """
    text_fields = ["MapMean", "MapMedian", "MapMin", "MapMax", "MapPercentile95", "MapStdDev", "MapMDL"]
    for field_name in text_fields:
        arcpy.management.AddField(flattened_table, field_name, "TEXT", "", "", 100, field_name)
    arcpy.management.AddField(flattened_table, "MapPopupHeading", "TEXT", "", "", 255, "MapPopupHeading")

    fields = [
        "AnalyteAlias", "Mean", "Median", "Min_", "Max_", "Percentile95", "StdDev",
        "MapMean", "MapMedian", "MapMin", "MapMax", "MapPercentile95", "MapStdDev", "MapMDL", "MapPopupHeading",
        "CityAboveMCL", "PctAboveMCL", "CityAboveThreshold", "PctAboveThreshold",
        "CityAboveVHA", "PctAboveVHA", "CityAboveSMCL", "PctAboveSMCL",
        "TOWNNAME", "CityCount",
    ]

    with arcpy.da.UpdateCursor(flattened_table, fields) as cursor:
        for row in cursor:
            (analyte_alias, mean, median, min_value, max_value, percentile95, std_dev,
             map_mean, map_median, map_min, map_max, map_percentile95, map_std_dev, map_mdl, map_popup_heading,
             city_above_mcl, pct_above_mcl, city_above_threshold, pct_above_threshold,
             city_above_vha, pct_above_vha, city_above_smcl, pct_above_smcl,
             town_name, city_count) = row

            # Suppress any town/analyte combination with too few samples to publish.
            if city_count is not None and float(city_count) < 20:
                cursor.deleteRow()
                continue

            if mean is not None:
                settings = public_map_analyte_settings.get(analyte_alias)
                if settings:
                    exceedance_field_values = {
                        "MCL": (city_above_mcl, pct_above_mcl),
                        "Threshold": (city_above_threshold, pct_above_threshold),
                        "VHA": (city_above_vha, pct_above_vha),
                    }
                    city_above_value, pct_above_value = exceedance_field_values[settings["exceedance_type"]]
                    threshold_label = settings["threshold_label"]
                    non_detect_display_threshold = settings["non_detect_display_threshold"]
                    units = settings["units"]
                else:
                    city_above_value = pct_above_value = threshold_label = non_detect_display_threshold = units = None

                if city_above_value in (0, None):
                    map_popup_heading = f"There are no {analyte_alias.lower()} tests above the {threshold_label} in {town_name}."
                else:
                    map_popup_heading = (
                        f"{round(pct_above_value, 1)} % of {analyte_alias.lower()} tests "
                        f"({city_above_value} out of {city_count}) are above the {threshold_label} in {town_name}."
                    )

                def format_stat(value):
                    return "*" if value < 0.001 else f"{round(value, 3)} {units}"

                map_mean = format_stat(mean)
                map_median = format_stat(median)
                map_min = format_stat(min_value)
                map_max = format_stat(max_value)
                map_percentile95 = format_stat(percentile95)
                map_std_dev = format_stat(std_dev)
                map_mdl = (
                    f"* Less than the reporting limit (RL) of the laboratory test, typically "
                    f"{non_detect_display_threshold} {units} for {analyte_alias.lower()}."
                    if any(value < 0.001 for value in (mean, median, min_value, max_value, percentile95, std_dev))
                    else ""
                )

            cursor.updateRow((
                analyte_alias, mean, median, min_value, max_value, percentile95, std_dev,
                map_mean, map_median, map_min, map_max, map_percentile95, map_std_dev, map_mdl, map_popup_heading,
                city_above_mcl, pct_above_mcl, city_above_threshold, pct_above_threshold,
                city_above_vha, pct_above_vha, city_above_smcl, pct_above_smcl,
                town_name, city_count,
            ))


def rebuild_table_indexes(editor_connection, tables):
    """
    Rebuilds the database indexes on the given tables. Run after the heavy delete/append
    refresh above, since large inserts/deletes can leave indexes fragmented.
    """
    for table in tables:
        arcpy.management.RebuildIndexes(editor_connection, "NO_SYSTEM", os.path.basename(table), "ALL")


# =====================================================================================
# STEP 6 - Update the "data last refreshed" date on SharePoint.
# =====================================================================================

def update_sharepoint_last_updated_date(azure_client_id, azure_client_secret, azure_tenant_id,
                                         site_url, list_id, application_domain):
    """
    Updates the "LatestDataUpdate" field on the SharePoint list item for the Groundwater
    Chemistry application domain, so staff can see at a glance when this data was last
    refreshed. This talks to Microsoft Graph using an Azure AD app registration (client
    credentials flow). This step isn't critical to the data pipeline itself, so any
    failure here is caught, printed as a warning, and doesn't stop the rest of the script.
    """
    try:
        token_response = requests.post(
            f"https://login.microsoftonline.com/{azure_tenant_id}/oauth2/v2.0/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": azure_client_id,
                "client_secret": azure_client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        token_response.raise_for_status()
        access_token = token_response.json().get("access_token")
        auth_headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json", "Content-Type": "application/json"}

        site_response = requests.get(f"https://graph.microsoft.com/v1.0/sites/{site_url}", headers=auth_headers)
        site_response.raise_for_status()
        site_id = site_response.json().get("id")

        # SharePoint stores this as UTC; adding 4 hours nudges it to display correctly in
        # Vermont's local time zone on the list view.
        display_adjusted_time = (datetime.now() + timedelta(hours=4)).isoformat() + "Z"

        items_response = requests.get(
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/items?expand=fields",
            headers=auth_headers)
        items_response.raise_for_status()

        for item in items_response.json().get("value", []):
            if item.get("fields", {}).get("ApplicationDomain1") == application_domain:
                update_response = requests.patch(
                    f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/items/{item['id']}/fields",
                    headers=auth_headers,
                    json={"LatestDataUpdate": display_adjusted_time},
                )
                update_response.raise_for_status()
                print("SharePoint 'last updated' date refreshed successfully.")

    except Exception as error:
        print(f"Warning: failed to update the SharePoint 'last updated' date: {error}")


# =====================================================================================
# STEP 7 - Republish the long-to-wide pivoted CSV export to ArcGIS Online.
# =====================================================================================

def build_wide_format_dataframe(points_feature_class):
    """
    Pulls every published point record and reshapes it from "one row per sample" (long
    format) into "one row per address/analyte, with Result1/ResultUnit1/SampleDate1,
    Result2/ResultUnit2/SampleDate2, etc. for repeat samples" (wide format). This is a
    separate, internal-use export - it isn't used by either public-facing map.
    """
    fields_of_interest = ["AnalyteAlias", "ConcatAddress", "Result", "ResultUnit", "SampleCollectionDateTime"]

    known_analytes = tuple(sorted({
        row[0] for row in arcpy.da.SearchCursor(points_feature_class, ["AnalyteAlias"])
        if row[0]
    }))
    where_clause = (
        f"lower(ConcatAddress) NOT IN ('delete') AND lower(ConcatAddress) NOT LIKE '%centroid%' "
        f"AND lower(ConcatAddress) NOT LIKE 'excluded%' AND AnalyteAlias IN {known_analytes}"
    )

    numpy_array = arcpy.da.TableToNumPyArray(points_feature_class, fields_of_interest, where_clause=where_clause)
    long_format_df = pd.DataFrame(numpy_array)
    long_format_df.sort_values(["ConcatAddress", "AnalyteAlias", "SampleCollectionDateTime"], inplace=True)
    long_format_df["sample_num"] = long_format_df.groupby(["ConcatAddress", "AnalyteAlias"]).cumcount() + 1

    wide_format_df = long_format_df.pivot_table(
        index=["ConcatAddress", "AnalyteAlias"],
        columns="sample_num",
        values=["Result", "ResultUnit", "SampleCollectionDateTime"],
        aggfunc="first",
    )
    wide_format_df.columns = [f"{value_name}{sample_num}" for value_name, sample_num in wide_format_df.columns]
    wide_format_df.reset_index(inplace=True)

    key_columns = ["AnalyteAlias", "ConcatAddress"]
    data_columns = sorted(
        (column for column in wide_format_df.columns if column not in key_columns),
        key=lambda column: (int("".join(filter(str.isdigit, column))), column),
    )
    wide_format_df = wide_format_df[key_columns + data_columns]

    for date_column in wide_format_df.filter(like="SampleCollectionDateTime").columns:
        wide_format_df[date_column] = pd.to_datetime(wide_format_df[date_column]).dt.strftime("%Y-%m-%d %H:%M:%S")

    return wide_format_df


def publish_pivoted_csv_to_agol(points_feature_class, ago_username, ago_password):
    """
    Builds the wide-format CSV export and uploads it to ArcGIS Online, replacing the
    existing "PivotedGroundwaterData" item's data. This is a non-critical, internal-use
    export, so any failure here is caught, printed as a warning, and doesn't stop the
    rest of the script. Always cleans up its temporary files, even if something goes wrong.
    """
    temp_dir = tempfile.gettempdir()
    csv_path = os.path.join(temp_dir, f"{PIVOTED_CSV_ITEM_TITLE}.csv")
    zip_path = os.path.join(temp_dir, f"{PIVOTED_CSV_ITEM_TITLE}.zip")

    try:
        wide_format_df = build_wide_format_dataframe(points_feature_class)
        wide_format_df.to_csv(csv_path, index=False, encoding="utf-8")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.write(csv_path, arcname=os.path.basename(csv_path))

        gis = GIS(AGOL_PORTAL_URL, username=ago_username, password=ago_password)
        search_results = gis.content.search(
            query=f'title:"{PIVOTED_CSV_ITEM_TITLE}" AND owner:{gis.users.me.username}', item_type="CSV")
        existing_item = next((item for item in search_results if item.title == PIVOTED_CSV_ITEM_TITLE), None)

        if existing_item is None:
            print(f"Warning: could not find an existing AGOL item titled '{PIVOTED_CSV_ITEM_TITLE}' to update.")
            return

        existing_item.update(data=zip_path)
        print("Pivoted CSV republished to ArcGIS Online successfully.")

    except Exception as error:
        print(f"Warning: failed to republish the pivoted CSV to ArcGIS Online: {error}")

    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)
        if os.path.exists(zip_path):
            os.remove(zip_path)


# =====================================================================================
# STEP 8 - Characterize every record whose location did not geocode cleanly, for
# privileged internal review. No new fields or app widgets - this just reads the
# internal points table (ConcatAddress already carries the geocode outcome, written by
# geocode_sample_locations() above) and republishes a CSV report to AGOL, the same way
# the pivoted CSV export already does.
# =====================================================================================

def generate_excluded_records_report(points_feature_class):
    """
    Scans every record on the (already-refreshed) internal points table and builds a
    report of every record whose address did not geocode to a real street-level match:
    records that failed to geocode at all (tagged "EXCLUDED - ..." in ConcatAddress by
    geocode_sample_locations()) and records that only reached their town's centroid
    (tagged "<town> Centroid", a lower-precision fallback). Centroid-geocoded records
    still count toward the public map's town/analyte statistics - this report exists so a
    privileged user can review geocoding precision, not to flag records as excluded from
    publish. Includes every field on points_feature_class, plus the point's
    longitude/latitude and a plain-language GeocodeOutcome column. Returns a pandas
    DataFrame ready to be written out as a CSV, with one row per record that failed to
    geocode or only reached centroid precision.
    """
    attribute_field_names = [
        field.name for field in arcpy.ListFields(points_feature_class)
        if field.type not in ("Geometry", "Blob", "Raster")
    ]
    cursor_fields = attribute_field_names + ["SHAPE@X", "SHAPE@Y"]
    with arcpy.da.SearchCursor(points_feature_class, cursor_fields) as cursor:
        records = list(cursor)
    report_df = pd.DataFrame.from_records(records, columns=attribute_field_names + ["Longitude", "Latitude"])

    concat_address_text = report_df["ConcatAddress"].astype("string")
    is_geocode_excluded = concat_address_text.str.startswith(GEOCODE_EXCLUSION_MARKER_PREFIX, na=False)
    is_centroid_only = concat_address_text.str.endswith(" Centroid", na=False)

    report_df["GeocodeOutcome"] = pd.NA
    report_df.loc[concat_address_text == GEOCODE_EXCLUSION_OUT_OF_STATE_MARKER, "GeocodeOutcome"] = \
        "Out-of-state address, not attempted"
    report_df.loc[concat_address_text == GEOCODE_EXCLUSION_NOT_GEOCODED_MARKER, "GeocodeOutcome"] = \
        "Address could not be geocoded"
    report_df.loc[is_centroid_only, "GeocodeOutcome"] = \
        "Geocoded to town centroid only (reduced spatial precision)"

    excluded_df = report_df.loc[is_geocode_excluded | is_centroid_only].reset_index(drop=True)
    return excluded_df


def publish_excluded_records_report_to_agol(report_df, ago_username, ago_password):
    """
    Uploads the excluded-records report to ArcGIS Online as a CSV item, in the same
    AGOL folder as the pivoted CSV export, so privileged users can
    find and download it from AGOL Content without needing any new map or app widget. If
    the item doesn't exist yet, this creates it and shares it the same way the existing
    pivoted CSV item is shared; otherwise it just replaces the data. This step is not
    critical to the data pipeline, so any failure here is caught, printed as a warning,
    and doesn't stop the rest of the script.
    """
    temp_dir = tempfile.gettempdir()
    csv_path = os.path.join(temp_dir, f"{EXCLUDED_RECORDS_REPORT_ITEM_TITLE}.csv")
    zip_path = os.path.join(temp_dir, f"{EXCLUDED_RECORDS_REPORT_ITEM_TITLE}.zip")

    try:
        report_df.to_csv(csv_path, index=False, encoding="utf-8")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.write(csv_path, arcname=os.path.basename(csv_path))

        gis = GIS(AGOL_PORTAL_URL, username=ago_username, password=ago_password)
        search_results = gis.content.search(
            query=f'title:"{EXCLUDED_RECORDS_REPORT_ITEM_TITLE}" AND owner:{gis.users.me.username}', item_type="CSV")
        existing_item = next((item for item in search_results if item.title == EXCLUDED_RECORDS_REPORT_ITEM_TITLE), None)

        if existing_item is not None:
            existing_item.update(data=zip_path)
            print(f"Excluded-records report updated ({len(report_df)} records) in ArcGIS Online.")
            return

        # First run - the item doesn't exist yet. Create it in the same folder as, and
        # share it the same way as, the pivoted CSV export, so it lands somewhere
        # privileged users already know to look.
        reference_item = next(
            (item for item in gis.content.search(
                query=f'title:"{PIVOTED_CSV_ITEM_TITLE}" AND owner:{gis.users.me.username}', item_type="CSV")
             if item.title == PIVOTED_CSV_ITEM_TITLE), None)

        # gis.content.add(..., folder=...) is deprecated in this version of the arcgis
        # package (and removed entirely in 3.0) - it silently mishandled the old-style
        # {"type": "CSV"} key (the modern API wants "item_type") and crashed with a
        # confusing "can only concatenate str (not NoneType) to str" error the first time
        # this code path actually ran for real. The modern replacement gets the folder as
        # its own object and adds to it directly, and returns a Job rather than the item
        # itself, so the actual Item has to be pulled out with .result().
        folder_obj = gis.content.folders.get(folder=PIVOTED_CSV_FOLDER_NAME, owner=gis.users.me.username)
        if folder_obj is None:
            raise RuntimeError(
                f"Could not find an AGOL folder named '{PIVOTED_CSV_FOLDER_NAME}' "
                f"owned by {gis.users.me.username}."
            )
        item_properties = ItemProperties(title=EXCLUDED_RECORDS_REPORT_ITEM_TITLE, item_type=ItemTypeEnum.CSV.value)
        add_job = folder_obj.add(item_properties=item_properties, file=zip_path)
        new_item = add_job.result()

        if reference_item is not None:
            # reference_item.sharing.groups is a manager object, not a list - call
            # .list() to get the actual Group objects, then share with each one
            # individually, since .add() only accepts a single group at a time.
            for group in reference_item.sharing.groups.list():
                new_item.sharing.groups.add(group=group)

        print(f"Excluded-records report created ({len(report_df)} records) in ArcGIS Online.")

    except Exception as error:
        print(f"Warning: failed to publish the excluded-records report to ArcGIS Online: {error}")

    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)
        if os.path.exists(zip_path):
            os.remove(zip_path)


# =====================================================================================
# MAIN - runs every step in order.
# =====================================================================================

def main():
    ago_username, ago_password = read_comma_separated_credentials_file(AGO_CREDS_FILE)

    # Step 1: mirror raw lab results into SDE.
    # Updates: RAW_DATA_TABLE (GroundwaterChemistry_GWCDrawdata) -> feeds the
    # "Raw Data (GWCD) - Internal" layer in the Internal experience. No other
    # application reads this table.
    refresh_raw_data_table(SQL_SOURCE_TABLE, RAW_DATA_TABLE, SQL_TO_SDE_FIELD_MAP)

    raw_data_memory_table = "memory/GroundwaterChemistry_GWCDrawdataCleaned"
    arcpy.conversion.TableToTable(RAW_DATA_TABLE, "memory", "GroundwaterChemistry_GWCDrawdataCleaned")

    # Step 2: weekly exceedance alert email (runs against the raw, not-yet-geocoded data).
    # Updates: nothing in SDE or AGOL - sends an email to EMAIL_RECIPIENTS. Does not
    # touch any table or application.
    run_weekly_exceedance_alert(raw_data_memory_table, EMAIL_SENDER, EMAIL_RECIPIENTS)

    # Step 3: clean up and geocode sample locations.
    # Updates: nothing yet - builds an in-memory intermediate table only. Nothing is
    # published to any live table or application until Step 5.
    joined_points = clean_and_geocode_points(raw_data_memory_table, TOWN_ALIAS_TABLE, TOWN_BOUNDARIES)

    # Step 4: calculate exceedances, de-duplicate, and summarize by town/analyte.
    # Updates: nothing yet - still an in-memory intermediate table.
    record_filter_clause = build_published_record_filter_clause()
    calculated_points = calculate_exceedances_and_summaries(joined_points, record_filter_clause, EXCEEDANCE_THRESHOLDS_BY_ANALYTE)

    # Step 5a: publish the full (internal) points to SDE.
    # Updates: POINTS_FEATURE_CLASS (GroundwaterChemistry_GWCDPoints) -> feeds the
    # "Geocoded GWCD Points - Internal" layer in the Internal experience, and is the
    # source table for the pivoted CSV (Step 7) and excluded-records report (Step 8).
    arcpy.management.SelectLayerByAttribute(calculated_points, "CLEAR_SELECTION")
    arcpy.management.DeleteFeatures(POINTS_FEATURE_CLASS)
    arcpy.management.Append(calculated_points, POINTS_FEATURE_CLASS, "NO_TEST")

    # Step 5b: build and publish the flattened, suppressed, public summary table.
    # Updates: EXTERNAL_PUBLIC_TABLE (GroundwaterChemistry_GWCDPointTableExternal) ->
    # feeds BOTH the "Analyte Data - External" layer in the Internal experience AND the
    # live public ArcGIS Server service behind the Public experience's "Private
    # Drinking Water Quality" page. That public service has no caching, so this is the
    # one step whose effects reach the public within one request.
    flattened_public_table = build_external_public_table(calculated_points, record_filter_clause)
    add_map_popup_text(flattened_public_table, PUBLIC_MAP_ANALYTE_SETTINGS)

    arcpy.management.DeleteRows(EXTERNAL_PUBLIC_TABLE)
    arcpy.management.Append(flattened_public_table, EXTERNAL_PUBLIC_TABLE, "NO_TEST")

    # Updates: no data changes - just rebuilds indexes on the three tables just written,
    # since large deletes/appends can leave them fragmented.
    rebuild_table_indexes(GIS_EDITOR_CONNECTION, [RAW_DATA_TABLE, POINTS_FEATURE_CLASS, EXTERNAL_PUBLIC_TABLE])

    # Step 6: update the "data last refreshed" date on SharePoint.
    # Updates: the "LatestDataUpdate" field on the Groundwater Chemistry SharePoint list
    # item (AHS.GISAdministrationGroup site). Not read by either experience directly.
    azure_client_id, azure_client_secret, azure_tenant_id = read_comma_separated_credentials_file(AZURE_CREDS_FILE)
    update_sharepoint_last_updated_date(
        azure_client_id, azure_client_secret, azure_tenant_id,
        SHAREPOINT_SITE_URL, SHAREPOINT_LIST_ID, SHAREPOINT_APPLICATION_DOMAIN)

    # Step 7: republish the pivoted CSV export to ArcGIS Online.
    # Updates: the "PivotedGroundwaterData" AGOL CSV item
    # (AHS_VDH_EnvHealth_GroundwaterInternal folder) - internal analysis export only,
    # not used by either experience.
    publish_pivoted_csv_to_agol(POINTS_FEATURE_CLASS, ago_username, ago_password)

    # Step 8: characterize every record that didn't geocode cleanly and publish that
    # report too.
    # Updates: the "GroundwaterChemistry_ExcludedRecords" AGOL CSV item
    # (AHS_VDH_EnvHealth_GroundwaterInternal folder) - internal review export only, not
    # used by either experience.
    excluded_records_report = generate_excluded_records_report(POINTS_FEATURE_CLASS)
    publish_excluded_records_report_to_agol(excluded_records_report, ago_username, ago_password)


if __name__ == "__main__":
    main()
