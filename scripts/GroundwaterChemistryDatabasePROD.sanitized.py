# ============================================================================
# SANITIZED COPY - for documentation purposes only.
# Internal server/SDE connection paths, credential file paths, staff email
# addresses, and Azure AD app registration secrets have been redacted/replaced
# with placeholders below. This is not a runnable copy of the production
# script. See ../docs/ for a guided walkthrough of this logic.
# ============================================================================

# for recorduid = 507051, in the final points dataset, the SamplePhysicalAddressCity is set to Athens, but
# a joined value for TOWNNAME and TOWNNAMEMC is set to Townshend.  This needs to be investigated. There are other examples like this.


"""
To Do:
Get Kristine:
 - a list of all analytes and the labs they come from
 - a list of records with other problems, like addresses
 - more





 Title:
Groundwater Chemistry Database Private Drinking Water Application Script

File Name:
GWCD_PUB.py

Description:

This script should run on a weekly basis
to maintain and update the public-facing web application for the display of private
drinking water exceedances by town and analyte.

Created by Victoria Treto (victoria.treto@vermont.gov)

Changelog:
01/23/23  - Created - Victoria Treto
11/01/23  - Finalized - Victoria Treto
3/24/2025 - Rewritten - Daniel Jarvis

ADDED MUNICIPAL TO THE WATER SOURCE FILTER - is this ok to remove?
"""


# ----------------------------------- Module Imports ----------------------------
# standard library + third party modules
import arcpy
from collections import defaultdict
import numpy as np
from datetime import datetime, timedelta
import os
import requests
import pandas as pd
import tempfile
import zipfile
from arcgis.gis import GIS
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import io
import csv
import html


# ----------------------------------- paths -------------------------------------
# main paths
# NOTE: internal server/SDE connection paths redacted for this public-facing copy.
GDBEnvHealthEditor = "<SDE_CONNECTION_PATH>/EnvHealth_PROD_Editor.sde"
groundwaterChemistryDatabaseGISTable = f"{GDBEnvHealthEditor}/GDB_ENVHEALTH_ADMIN.GroundwaterChemistry_GWCDrawdata"
groundwaterChemistryDatabaseGISAliasTable = f"{GDBEnvHealthEditor}/GDB_ENVHEALTH_ADMIN.GroundwaterChemistryAliasTable"
groundwaterChemistryDatabaseGISPoints = f"{GDBEnvHealthEditor}/GDB_ENVHEALTH_ADMIN.GroundwaterChemistry_GWCDPoints"
groundwaterChemistryDatabaseGISPointTableExternal = f"{GDBEnvHealthEditor}/GDB_ENVHEALTH_ADMIN.GroundwaterChemistry_GWCDPointTableExternal"
townBounds = f"{GDBEnvHealthEditor}/GDB_ENVHEALTH_ADMIN.GroundwaterChemistry_TownBounds"

groundwaterChemistryDatabaseSQLDB = "<SDE_CONNECTION_PATH>/<SQL_CONNECTION_FILE>.sde"
groundwaterChemistryDatabaseSQLTable = f"{groundwaterChemistryDatabaseSQLDB}/groundwater.ChemistryResults"
E911GeocoderService = "https://maps.vcgi.vermont.gov/arcgis/rest/services/EGC_services/GCS_E911_COMPOSITE_SP_v2/GeocodeServer/GCS_E911_COMPOSITE_SP_v2"
agoCredsFile = "<REDACTED_CREDENTIALS_FILE_PATH>"

# --- Email Configuration ---
# NOTE: real staff addresses redacted for this public-facing copy.
EMAIL_SENDER = "<REDACTED_SENDER_ADDRESS>"
EMAIL_RECIPIENTS = ["<REDACTED_RECIPIENT_1>", "<REDACTED_RECIPIENT_2>", "<REDACTED_RECIPIENT_3>", "<REDACTED_RECIPIENT_4>"]

# Get AGO EnvHealth Credentials
# NOTE: credential loading redacted. In production this reads a username/password
# pair from a secured, access-restricted local file - no secrets are hardcoded here.
agoUsername = "<REDACTED>"
agoPassword = "<REDACTED>"

# Appending Raw GWCD Data to GIS Table GWCDrawdata
arcpy.management.DeleteRows(groundwaterChemistryDatabaseGISTable)

fields = {'AdditionalEmail': 'AdditionalEmail', 'AnalysisType': 'AnalysisType', 
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
          'WHResultValueNumeric': 'WHResultValueNumeric', 'WaterSource': 'WaterSource', 'pH': 'pH'}

with arcpy.da.InsertCursor(groundwaterChemistryDatabaseGISTable, list(fields.values())) as insertCursor:
    with arcpy.da.SearchCursor(groundwaterChemistryDatabaseSQLTable, list(fields.keys())) as searchCursor:
        for row in searchCursor:
            insertCursor.insertRow(row)

groundwaterChemistryDatabaseGISTableCleanedInMemory = "memory/GroundwaterChemistry_GWCDrawdataCleaned"
arcpy.TableToTable_conversion(groundwaterChemistryDatabaseGISTable, "memory", "GroundwaterChemistry_GWCDrawdataCleaned")

def AnalyteThresholdDetection(groundwaterChemistryDatabaseGISTableCleanedInMemory, EMAIL_SENDER, EMAIL_RECIPIENTS):
    """
    GLOBAL FILTERS
    Location Filter: (UPPER(SampleLocationPhysicalAddressSt) IN ('VT','VERMONT','VTG','VT 0','VR','VRT','WATERV','0','q',
                      'EEEEEEEEEEEEE','VTP','VTT','VST','V','VTD','```','VGT','VERM','AAAAAAAAAAAAA')
                      OR SampleLocationPhysicalAddressSt = '' OR SampleLocationPhysicalAddressSt IS NULL)
        Selects records where the physical address state is Vermont, a known typo/placeholder variant of "VT"
        seen in the source data (e.g. 'VTG', 'q', '```', 'AAAAAAAAAAAAA'), blank, or NULL. The typo list was
        built up over time from real bad data so those records aren't silently dropped.
    Data Quality Filter: (Result IS NULL OR (LOWER(Result) NOT LIKE '%not tested%' AND LOWER(Result) NOT LIKE '%error in result%'
                          AND LOWER(Result) NOT LIKE '%rejected%' AND LOWER(Result) NOT LIKE '%rejection%'
                          AND LOWER(Result) NOT LIKE '%error%' AND LOWER(Result) NOT LIKE '%fail%' AND LOWER(Result) NOT LIKE '%complete%'))
        Case-insensitive and NULL-safe: a NULL Result passes through (excluded later by the numeric CAST in the
        contaminant filters below), and text results are excluded if they indicate the sample wasn't validly tested.
    Client Exclusion Filter: (ClientName IS NULL OR LOWER(ClientName) NOT LIKE '%vdh lab proficiency%')
        Case-insensitive and NULL-safe exclusion of VDH Lab Proficiency test records.
    Date Filter: SampleCollectionDateTime >= timestamp 'YYYY-MM-DD HH:MI:SS'
        - timedelta(days=7)
        This is a dynamic filter that restricts the data to the last 7 days from the date the script is run. It ensures that only relatively recent data is analyzed.

    CONTAMINANT-SPECIFIC FILTERS
    Metals Filters: ResultUnit must be in milligrams per liter ('mg/L'), ResultType must be '=', and Result must be
    greater than or equal to a specific threshold:
        Barium: >= 5 mg/L
        Cadmium: >= 0.005 mg/L
        Chromium: >= 0.1 mg/L
        Mercury: >= 0.002 mg/L
        Selenium: >= 0.05 mg/L
        Silver: >= 0.1 mg/L
        Antimony: >= 0.006 mg/L
        Beryllium: >= 0.004 mg/L
        Nickel: >= 0.021 mg/L
        Thallium: >= 0.002 mg/L
        Zinc: >= 5 mg/L
    VOCs Filter: (TestMethodCode LIKE '%524%' OR TestMethodName LIKE '%524%' OR TestMethodCode LIKE '%551%' OR TestMethodName LIKE '%551%')
        AND (ResultUnit IS NULL OR ResultUnit NOT LIKE '%!%%' ESCAPE '!') AND ResultType = '='
        Targets Volatile Organic Compounds (VOCs) analyzed using method code or name containing '524' or '551',
        excluding records whose ResultUnit literally contains a '%' character (escaped so it isn't a wildcard),
        while still allowing a NULL/blank unit through.
    BNAs Filter: (TestMethodCode LIKE '%525%' OR TestMethodName LIKE '%525%')
        AND (ResultUnit IS NULL OR ResultUnit NOT LIKE '%!%%' ESCAPE '!') AND ResultType = '='
        Targets Base/Neutral Acids (BNAs) analyzed using method code or name containing '525'.
    PCBs Filter: (TestMethodCode LIKE '%505%' OR TestMethodCode LIKE '%508%' OR TestMethodName LIKE '%505%' OR TestMethodName LIKE '%508%')
        AND (ResultUnit IS NULL OR ResultUnit NOT LIKE '%!%%' ESCAPE '!') AND ResultType = '='
        Targets Polychlorinated Biphenyls (PCBs) analyzed using method codes or names containing '505' or '508'.
    Herbicides Filter: (TestMethodCode LIKE '%515%' OR TestMethodCode LIKE '%552%' OR TestMethodName LIKE '%515%' OR TestMethodName LIKE '%552%')
        AND (ResultUnit IS NULL OR ResultUnit NOT LIKE '%!%%' ESCAPE '!') AND ResultType = '='
        Targets herbicides analyzed using method codes or names containing '515' or '552'. (No AnalyteName
        exclusions are currently applied.)
    PFOS/PFAS Filter: (TestMethodCode LIKE '%533%' OR TestMethodCode LIKE '%537%' OR TestMethodName LIKE '%533%' OR TestMethodName LIKE '%537%')
        AND (ResultUnit IS NULL OR ResultUnit NOT LIKE '%!%%' ESCAPE '!') AND ResultType = '='
        AND (SamplingLocationDescription IS NULL OR UPPER(SamplingLocationDescription) NOT LIKE '%BLANK%')
        Targets Perfluorooctanesulfonic acid (PFOS) and Per- and polyfluoroalkyl substances (PFAS) analyzed using
        method codes or names containing '533' or '537', excluding blank samples (case-insensitive).
    """

    # =============================================================================
    # CONFIGURATION
    # =============================================================================

    # --- ArcGIS Data Configuration ---
    groundwater_table = groundwaterChemistryDatabaseGISTableCleanedInMemory

    def emailNotification(body, email_sender, email_recipients, csv_string=None, attachment_filename=None):
        """
        Sends a multipart email with an HTML body and an optional CSV attachment.
        """
        try:
            # Create the container email message.
            msg = MIMEMultipart()
            msg['Subject'] = '|| Automated Alert || - Weekly Groundwater Chemistry Analyte Exceedance Report'
            msg['From'] = email_sender
            msg['To'] = ", ".join(email_recipients)

            # 1. Attach the HTML body part.
            html_part = MIMEText(body, 'html')
            msg.attach(html_part)

            # 2. If a CSV string is provided, attach it as a file.
            if csv_string and attachment_filename:
                csv_part = MIMEApplication(csv_string.encode('utf-8'), Name=attachment_filename)
                csv_part['Content-Disposition'] = f'attachment; filename="{attachment_filename}"'
                msg.attach(csv_part)

            # 3. Send the complete message.
            server = smtplib.SMTP('relay.state.vt.us')
            server.sendmail(email_sender, email_recipients, msg.as_string())
            
            if attachment_filename:
                print(f"Summary email with CSV attachment '{attachment_filename}' sent successfully.")
            else:
                print("Email sent successfully.")
            
        except Exception as e:
            print(f"Failed to send email: {e}")

    def check_groundwater_data():
        """
        Filters data, classifies/sorts results, and sends a summary email
        with a CSV attachment.
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        #start_date = end_date - timedelta(days=30)
        start_date_sql_str = start_date.strftime('%Y-%m-%d %H:%M:%S')
        date_filter = f"SampleCollectionDateTime >= timestamp '{start_date_sql_str}'"

        #all_data_filters = [
        #    "(UPPER(SampleLocationPhysicalAddressSt) = 'VT' OR SampleLocationPhysicalAddressSt = '' OR SampleLocationPhysicalAddressSt IS NULL)",
        #    "(LOWER(Result) NOT LIKE '%not tested%' AND LOWER(Result) NOT LIKE '%error in result%' AND LOWER(Result) NOT LIKE '%rejected%' AND LOWER(Result) NOT LIKE '%rejection%' AND LOWER(Result) NOT LIKE '%error%' AND LOWER(Result) NOT LIKE '%fail%' AND LOWER(Result) NOT LIKE '%complete%')",
        #    "LOWER(ClientName) NOT LIKE '%vdh lab proficiency%'",
        #    date_filter,
        #]

        all_data_filters = [
            #"(UPPER(SampleLocationPhysicalAddressSt) = 'VT' OR SampleLocationPhysicalAddressSt = '' OR SampleLocationPhysicalAddressSt IS NULL)",
            "(UPPER(SampleLocationPhysicalAddressSt) IN ('VT','VERMONT','VTG','VT 0','VR','VRT','WATERV','0','q','EEEEEEEEEEEEE','VTP','VTT','VST','V','VTD','```','VGT','VERM','AAAAAAAAAAAAA') OR SampleLocationPhysicalAddressSt = '' OR SampleLocationPhysicalAddressSt IS NULL)",

            "("
            "Result IS NULL OR "
            "("
            "LOWER(Result) NOT LIKE '%not tested%' "
            "AND LOWER(Result) NOT LIKE '%error in result%' "
            "AND LOWER(Result) NOT LIKE '%rejected%' "
            "AND LOWER(Result) NOT LIKE '%rejection%' "
            "AND LOWER(Result) NOT LIKE '%error%' "
            "AND LOWER(Result) NOT LIKE '%fail%' "
            "AND LOWER(Result) NOT LIKE '%complete%'"
            ")"
            ")",

            "(ClientName IS NULL OR LOWER(ClientName) NOT LIKE '%vdh lab proficiency%')",

            date_filter,
        ]

        metals_filters = [
            "(AnalyteName LIKE '%Barium%' AND ResultUnit = 'mg/L' AND CAST(Result AS FLOAT) >= 5 AND ResultType = '=')",
            "(AnalyteName LIKE '%Cadmium%' AND ResultUnit = 'mg/L' AND CAST(Result AS FLOAT) >= 0.005 AND ResultType = '=')",
            "(AnalyteName LIKE '%Chromium%' AND ResultUnit = 'mg/L' AND CAST(Result AS FLOAT) >= 0.1 AND ResultType = '=')",
            "(AnalyteName LIKE '%Mercury%' AND ResultUnit = 'mg/L' AND CAST(Result AS FLOAT) >= 0.002 AND ResultType = '=')",
            "(AnalyteName LIKE '%Selenium%' AND ResultUnit = 'mg/L' AND CAST(Result AS FLOAT) >= 0.05 AND ResultType = '=')",
            "(AnalyteName LIKE '%Silver%' AND ResultUnit = 'mg/L' AND CAST(Result AS FLOAT) >= 0.1 AND ResultType = '=')",
            "(AnalyteName LIKE '%Antimony%' AND ResultUnit = 'mg/L' AND CAST(Result AS FLOAT) >= 0.006 AND ResultType = '=')",
            "(AnalyteName LIKE '%Beryllium%' AND ResultUnit = 'mg/L' AND CAST(Result AS FLOAT) >= 0.004 AND ResultType = '=')",
            "(AnalyteName LIKE '%Nickel%' AND ResultUnit = 'mg/L' AND CAST(Result AS FLOAT) >= 0.021 AND ResultType = '=')",
            "(AnalyteName LIKE '%Thallium%' AND ResultUnit = 'mg/L' AND CAST(Result AS FLOAT) >= 0.002 AND ResultType = '=')",
            "(AnalyteName LIKE '%Zinc%' AND ResultUnit = 'mg/L' AND CAST(Result AS FLOAT) >= 5 AND ResultType = '=')"
        ]

        #vocs_filter = "((TestMethodCode LIKE '%524%' OR TestMethodName LIKE '%524%' OR TestMethodCode LIKE '%551%' OR TestMethodName LIKE '%551%') AND ResultUnit NOT LIKE '%!%%' ESCAPE '!' AND ResultType = '=')"
        vocs_filter = (
            "((TestMethodCode LIKE '%524%' "
            "OR TestMethodName LIKE '%524%' "
            "OR TestMethodCode LIKE '%551%' "
            "OR TestMethodName LIKE '%551%') "
            "AND "
            "(ResultUnit IS NULL OR ResultUnit NOT LIKE '%!%%' ESCAPE '!') "
            "AND ResultType = '=')"
        )
        #bnas_filter = "((TestMethodCode LIKE '%525%' OR TestMethodName LIKE '%525%') AND NOT ResultUnit LIKE '%%' AND ResultUnit NOT LIKE '%!%%' ESCAPE '!' AND ResultType = '=')"
        bnas_filter = (
            "((TestMethodCode LIKE '%525%' "
            "OR TestMethodName LIKE '%525%') "
            "AND "
            "(ResultUnit IS NULL OR ResultUnit NOT LIKE '%!%%' ESCAPE '!') "
            "AND ResultType = '=')"
        )
        #pcbs_filter = "((TestMethodCode LIKE '%505%' OR TestMethodCode LIKE '%508%' OR TestMethodName LIKE '%505%' OR TestMethodName LIKE '%508%') AND ResultUnit NOT LIKE '%!%%' ESCAPE '!' AND ResultType = '=')"
        pcbs_filter = (
            "((TestMethodCode LIKE '%505%' "
            "OR TestMethodCode LIKE '%508%' "
            "OR TestMethodName LIKE '%505%' "
            "OR TestMethodName LIKE '%508%') "
            "AND "
            "(ResultUnit IS NULL OR ResultUnit NOT LIKE '%!%%' ESCAPE '!') "
            "AND ResultType = '=')"
        )
        #herbicides_filter = "((TestMethodCode LIKE '%515%' OR TestMethodCode LIKE '%552%' OR TestMethodName LIKE '%515%' OR TestMethodName LIKE '%552%') AND ResultUnit NOT LIKE '%!%%' ESCAPE '!' AND ResultType = '=')"
        herbicides_filter = (
            "((TestMethodCode LIKE '%515%' "
            "OR TestMethodCode LIKE '%552%' "
            "OR TestMethodName LIKE '%515%' "
            "OR TestMethodName LIKE '%552%') "
            "AND "
            "(ResultUnit IS NULL OR ResultUnit NOT LIKE '%!%%' ESCAPE '!') "
            "AND ResultType = '=')"
        )
        #pfos_pfas_filter = "((TestMethodCode LIKE '%533%' OR TestMethodCode LIKE '%537%' OR TestMethodName LIKE '%533%' OR TestMethodName LIKE '%537%') AND ResultUnit NOT LIKE '%!%%' ESCAPE '!' AND ResultType = '=' AND NOT Upper(SamplingLocationDescription) LIKE '%BLANK%')"
        pfos_pfas_filter = (
            "((TestMethodCode LIKE '%533%' "
            "OR TestMethodCode LIKE '%537%' "
            "OR TestMethodName LIKE '%533%' "
            "OR TestMethodName LIKE '%537%') "
            "AND "
            "(ResultUnit IS NULL OR ResultUnit NOT LIKE '%!%%' ESCAPE '!') "
            "AND ResultType = '=' "
            "AND "
            "(SamplingLocationDescription IS NULL "
            "OR UPPER(SamplingLocationDescription) NOT LIKE '%BLANK%'))"
        )

        contaminant_filters = f"({ ' OR '.join(metals_filters) } OR {vocs_filter} OR {bnas_filter} OR {pcbs_filter} OR {herbicides_filter} OR {pfos_pfas_filter})"
        where_clause = f"({' AND '.join(all_data_filters)}) AND ({contaminant_filters})"

        fields = ["AnalyteName", "Result", "ResultUnit", "SampleLocationPhysicalAddress1", "SampleLocationPhysicalAddressCi", "SampleCollectionDateTime",
                "ClientName", "TestMethodCode", "TestMethodName", "ResultType", "Record_uid"]

        alert_records = []
        with arcpy.da.SearchCursor(groundwater_table, fields, where_clause) as cursor:
            for row in cursor:
                record_class = get_record_class(fields, row)
                alert_records.append(list(row) + [record_class])

        if alert_records:
            alert_records.sort(key=lambda record: record[5] if record[5] else datetime.min, reverse=True) # Index adjusted for new field

            csv_header = ["Classification", "Analyte", "ResultType", "Result", "Unit", "Client", "Sample_Date",
                        "Location", "City", "TestMethodName", "TestMethodCode", "Record_uid"]

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(csv_header)

            for record in alert_records:
                csv_row = [
                    record[11],  # Classification
                    record[0],   # AnalyteName
                    record[9],   # ResultType
                    record[1],   # Result
                    record[2],   # ResultUnit
                    record[6],   # ClientName
                    record[5].strftime('%Y-%m-%d') if record[5] else "", # SampleCollectionDateTime
                    record[3],   # SampleLocationPhysicalAddress1
                    record[4],   # SampleLocationPhysicalAddressCi
                    record[8],   # TestMethodName
                    record[7],   # TestMethodCode
                    record[10]    # Record_uid
                ]
                writer.writerow(csv_row)

            csv_content_string = output.getvalue()
            output.close()

            html_table = "<table border='1' cellspacing='0' cellpadding='5'>\n"
            html_table += (
                "<tr>"
                "<th>Classification</th><th>Analyte</th><th>ResultType</th><th>Result</th><th>Unit</th>"
                "<th>Client</th><th>Sample Date</th><th>Location</th><th>City</th>"
                "<th>TestMethodName</th><th>TestMethodCode</th><th>Record_uid</th>"
                "</tr>\n"
            )
            def esc(value):
                return html.escape(str(value)) if value else 'N/A'

            for record in alert_records:
                # Note: All indices after the new field are shifted by 1
                html_table += (
                    f"<tr>"
                    f"<td>{esc(record[11])}</td>" # Classification
                    f"<td>{esc(record[0])}</td>"  # AnalyteName
                    f"<td>{esc(record[9])}</td>"  # ResultType
                    f"<td>{esc(record[1])}</td>"  # Result
                    f"<td>{esc(record[2])}</td>"  # ResultUnit
                    f"<td>{esc(record[6])}</td>"  # ClientName
                    f"<td>{record[5].strftime('%Y-%m-%d') if record[5] else 'N/A'}</td>" # Date
                    f"<td>{esc(record[3])}</td>"  # Location
                    f"<td>{esc(record[4])}</td>"  # City
                    f"<td>{esc(record[8])}</td>"  # TestMethodName
                    f"<td>{esc(record[7])}</td>"  # TestMethodCode
                    f"<td>{esc(record[10])}</td>"  # Record_uid
                    f"</tr>\n"
                )
            html_table += "</table>\n"

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

            today_str = datetime.now().strftime('%Y-%m-%d')
            attachment_filename = f"Groundwater_Exceedance_Report_{today_str}.csv"

            emailNotification(body, EMAIL_SENDER, EMAIL_RECIPIENTS, csv_content_string, attachment_filename)

        else:
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
            emailNotification(body, EMAIL_SENDER, EMAIL_RECIPIENTS)
            
    def get_record_class(record_fields, record_row):
        """
        Classifies a record into a contaminant group based on its AnalyteName
        and TestMethod.
        """
        row_dict = dict(zip(record_fields, record_row))
        
        analyte = row_dict.get("AnalyteName", "")
        test_code = row_dict.get("TestMethodCode", "") or ""
        test_name = row_dict.get("TestMethodName", "") or ""

        metal_analytes = [
            'Barium', 'Cadmium', 'Chromium', 'Mercury', 'Selenium', 'Silver',
            'Antimony', 'Beryllium', 'Nickel', 'Thallium', 'Zinc'
        ]
        if any(metal in analyte for metal in metal_analytes):
            return "Metals"
        
        if '533' in test_code or '537' in test_code or '533' in test_name or '537' in test_name:
            return "PFOS/PFAS"
        if '524' in test_code or '524' in test_name or '551' in test_code or '551' in test_name:
            return "VOCs"
        if '525' in test_code or '525' in test_name:
            return "BNAs"
        if '505' in test_code or '508' in test_code or '505' in test_name or '508' in test_name:
            return "PCBs"
        if '515' in test_code or '552' in test_code or '515' in test_name or '552' in test_name:
            return "Herbicides"
            
        return "Other"

    check_groundwater_data()

AnalyteThresholdDetection(groundwaterChemistryDatabaseGISTableCleanedInMemory, EMAIL_SENDER, EMAIL_RECIPIENTS)

def GetJoinedPoints(groundwaterChemistryDatabaseGISTableCleanedInMemory, groundwaterChemistryDatabaseGISAliasTable, townBounds):
    """
    Returns the joined points table from the groundwater chemistry database.
    """

    # Zip code fixes
    # Fix zip dashes for zeros
    clause = """SampleLocationPhysicalAddressZi LIKE '-%'"""
    selection = arcpy.management.SelectLayerByAttribute(groundwaterChemistryDatabaseGISTableCleanedInMemory,"NEW_SELECTION",clause)
    arcpy.management.CalculateField(selection, "SampleLocationPhysicalAddressZi", "!SampleLocationPhysicalAddressZi!.replace('-','0')")
    # Fix zip one replacements
    clause = """SampleLocationPhysicalAddressZi LIKE '1%'"""
    selection = arcpy.management.SelectLayerByAttribute(groundwaterChemistryDatabaseGISTableCleanedInMemory,"NEW_SELECTION",clause)
    arcpy.management.CalculateField(selection, "SampleLocationPhysicalAddressZi", "'0' + !SampleLocationPhysicalAddressZi![1:5]")
    # Fix missing leading zeros
    clause = """SampleLocationPhysicalAddressZi NOT LIKE '0%' AND SampleLocationPhysicalAddressZi NOT IN ('NA','VT','Not Report','Well')"""    
    selection = arcpy.management.SelectLayerByAttribute(groundwaterChemistryDatabaseGISTableCleanedInMemory,"NEW_SELECTION",clause)
    arcpy.management.CalculateField(selection, "SampleLocationPhysicalAddressZi", "'0' + !SampleLocationPhysicalAddressZi!")

    # Update Sample Location values
    sampleLocationsDictionary = {
        'drilled well':'Drilled Well',
        'dug well':'Dug Well',
        'other':'Unknown',
        'not reported by client':'Unknown',
        'well':'Well',
        'spring':'Spring',
        'unknown':'Unknown'
    }

    # Update Water Source values and substitute unknown values where the description field has the needed value
    with arcpy.da.UpdateCursor(groundwaterChemistryDatabaseGISTableCleanedInMemory, ["WaterSource","SamplingLocationDescription"]) as updateCursor:
        for row in updateCursor:
            waterSource = str(row[0]).lower().strip()
            description = str(row[1]).lower().strip()
            if waterSource in ['other','not reported by client','none']:
                for source in ['drilled well','dug well','well','spring']:
                    if source == description:
                        row[0] = sampleLocationsDictionary[source]
                    else:
                        row[0] = "Unknown"
            elif waterSource in sampleLocationsDictionary:
                row[0] = sampleLocationsDictionary[waterSource]
            else:
                pass
            updateCursor.updateRow(row)

    # Update town values (get alias values then update the values)
    """
    here are the out of state and problematic SampleLocationPhysicalAddressCi values.
    This discounts the fact that they are all problematic, and that the alias table
    is really just a series of exceptions. It would be better to validate the data 
    during entry, and slowly update all these problematic values to be correct.

    Barre	MultiField Required
    Champlain	MultiField Required
    Kitchen	MultiField Required
    Orleans	MultiField Required

    Qsue	Unknown
    TC	Unknown
    W	Westbrook, CT
    Westbrook CT	Westbrook, CT
    Westbrook	Westbrook, CT
    Casco	Casco, ME
    Boston	Boston, MA
    Brooksville	likely Brooksville, ME
    Ceadshore	maybe Readsboro
    Checkerberry Village	Milton or Charlotte
    Chestertown	Chestertown, NY
    Claremont	Claremont, NH
    Clemons	Clemons, NY
    Columbia	Columbia, MD
    Cornish	Cornish, NH
    Dalton	Dalton, NH
    Ellenburg Center	Ellenburg Center, NY
    Enfield	Enfield, NH
    Etna	Etna, NH
    Exeter	Exeter, RI
    Fort Edward	Fort Edward, NY
    Gorham	Gorham, NH
    Grantham	Grantham, NH
    Groveton	Groveton, NH
    Hadley	Hadley, MA
    Hanover	Hanover, NH
    Hubbard Corner	Castleton or Georgia
    Huletts Landing	Huletts Landing, NY
    Keene	Keene, NH
    Lebanon	Lebanon, NH
    Littleton	Littleton, NH
    Lyme	Lyme, NH
    Meredith	Meredith, NH
    Miranda Morse	Unknown
    Mooers	Mooers, NY
    New London	New London, NH
    Newcomb	Newcomb, NY
    Not Porvided	Unknown
    Orford	Orford, NH
    Oxford	Oxford, CT
    Piermont	Piermont, NH
    Plattsburgh	Plattsburgh, NY
    ST CATHERIE	Unknown
    Salem	Salem, MA
    Somerville	Somerville, MA
    West West	Likely Westminster pr Putney
    Whitehall	Whitehall, NY
    Whitney	Unknown
    Willsboro	Willsboro, NY
    """

    aliasDictionary = dict()
    with arcpy.da.SearchCursor(groundwaterChemistryDatabaseGISAliasTable, ['Municipality', 'Town', 'Alias']) as searchCursor:
        for row in searchCursor:
            municipality = row[0]
            town = row[1]
            aliasList = row[2]
            if town not in aliasDictionary:
                aliasDictionary[town.lower()] = municipality
            if municipality.lower() not in aliasDictionary:
                aliasDictionary[municipality.lower()] = municipality
            if aliasList != None:
                for alias in aliasList.split(","):
                    if alias not in aliasDictionary:
                        aliasDictionary[alias.lower()] = municipality

    fields = ['SampleLocationPhysicalAddress1','SampleLocationPhysicalAddressCi','SampleLocationPhysicalAddressZi']
    with arcpy.da.UpdateCursor(groundwaterChemistryDatabaseGISTableCleanedInMemory, fields) as updateCursor:
        for row in updateCursor:
            address = row[0]
            town = row[1].lower()
            zipCode = row[2]
            if address == None:
                row[0] = ""
            elif town == None:
                row[1] = ""
            elif zipCode == None:
                row[2] = ""
            if town in aliasDictionary:
                townAlias = aliasDictionary[town]
                row[1] = townAlias
            updateCursor.updateRow(row)

    # Update analyte names
    analyteDictionary = {
        'arsenic': 'Arsenic',
        'arsenic total': 'Arsenic',
        'sulfate': 'Sulfate',
        'fluoride': 'Fluoride',
        'total dissolved': 'TDS',
        'tds': 'TDS',
        'gross alpha': 'Gross Alpha',
        'total nitrate/nitrite': 'Total Nitrate and Nitrite',
        'nitrate & nitrite': 'Total Nitrate and Nitrite', 
        'nitrate and nitrite as no3': 'Total Nitrate and Nitrite',
        'total nitrate and nitrite as n': 'Total Nitrate and Nitrite',
        'nitrate': 'Nitrate',
        'nitrate as n': 'Nitrate',
        'nitrite': 'Nitrite',
        'nitrite as n': 'Nitrite',
        'sodium': 'Sodium',
        'chloride': 'Chloride',
        'manganese': 'Manganese',
        'lead': 'Lead',
        'iron': 'Iron',
        'copper': 'Copper',
        'radon': 'Radon',
        'radon-222': 'Radon',
        'radon in water': 'Radon',
        'uranium': 'Uranium',
        'uranium total': 'Uranium',
        'radium': 'Radium',
        'radium-226': 'Radium',
        'radium-228': 'Radium',
        'radium-226/228': 'Radium',
        'e. coli': 'E.coli',
        'e.coli': 'E.coli',
        'escherichia': 'E.coli',
        'coliform': 'Total Coliform',
        'coliforms': 'Total Coliform',
        'turbidity': 'Turbidity',
        'hardness': 'Hardness',
        'odor': 'Odor',
        'ph': 'pH',
    }

    # Update Analyte Alias and Water Source, and find Water Source-Location Description matches and set mismatched to None
    arcpy.management.AddField(groundwaterChemistryDatabaseGISTableCleanedInMemory, "AnalyteAlias","TEXT","","",200,"AnalyteAlias")
    with arcpy.da.UpdateCursor(groundwaterChemistryDatabaseGISTableCleanedInMemory, ["AnalyteName","AnalyteAlias"]) as updateCursor:
        for row in updateCursor:
            analyteName = str(row[0]).lower().strip()
            if analyteName in analyteDictionary:
                analyteAlias = analyteDictionary[analyteName]
                row[1] = analyteAlias
            updateCursor.updateRow(row)

    # Calculate fields for geocoding
    # Address concatenation
    selection = arcpy.management.SelectLayerByAttribute(groundwaterChemistryDatabaseGISTableCleanedInMemory,"NEW_SELECTION","""SampleLocationPhysicalAddressSt NOT IN ('TN','NH','KY','MA','ME','RI','MD','NJ','TX','CT','VA','NY')""")
    addressConcatClause = """!SampleLocationPhysicalAddress1!+", "!SampleLocationPhysicalAddressCi!+", VT, "+!SampleLocationPhysicalAddressZi!"""
    arcpy.management.CalculateField(selection,"ConcatAddress",addressConcatClause)
    arcpy.management.SelectLayerByAttribute(groundwaterChemistryDatabaseGISTableCleanedInMemory,"CLEAR_SELECTION")

    # Geocode Addresses
    geocodedDataTableInMemory = "memory/geocodedAddresses"
    arcpy.geocoding.GeocodeAddresses(
        groundwaterChemistryDatabaseGISTableCleanedInMemory,
        address_locator="https://maps.vcgi.vermont.gov/arcgis/rest/services/EGC_services/GCS_E911_COMPOSITE_SP_v2/GeocodeServer/GCS_E911_COMPOSITE_SP_v2",
        in_address_fields="'Single Line Input' ConcatAddress VISIBLE NONE",
        out_feature_class=geocodedDataTableInMemory,
        out_relationship_type="STATIC",
        country=None,
        location_type="",
        category=None,
        output_fields="LOCATION_ONLY"
    )

    arcpy.management.Delete(groundwaterChemistryDatabaseGISTableCleanedInMemory)

    # Geocode empty geometry records to town centroid
    selection = arcpy.management.SelectLayerByAttribute(geocodedDataTableInMemory,"NEW_SELECTION","SHAPE IS NULL")
    flattenedNullShapesInMemory = "memory/FlattenedNullShapes"
    arcpy.conversion.TableToTable(selection,"memory","FlattenedNullShapes")
    # Remove the null records from the geocoded data table - they will be replaced with the town centroid geocoding results
    # Points from the null records that cannot be geocoded at all will be discarded
    arcpy.management.DeleteFeatures(selection)
    geocodedTownCentroidsInMemory = "memory/geocodedTownownCentroids"
    arcpy.geocoding.GeocodeAddresses(
        flattenedNullShapesInMemory,
        address_locator="https://maps.vcgi.vermont.gov/arcgis/rest/services/EGC_services/GCS_E911_COMPOSITE_SP_v2/GeocodeServer/GCS_E911_COMPOSITE_SP_v2",
        in_address_fields="'Single Line Input' SampleLocationPhysicalAddressCi VISIBLE NONE",
        out_feature_class=geocodedTownCentroidsInMemory,
        out_relationship_type="STATIC",
        country=None,
        location_type="CENTROID",  # Ensure centroids are returned
        category=None,
        output_fields="LOCATION_ONLY"
    )

    arcpy.management.CalculateField(geocodedTownCentroidsInMemory,"ConcatAddress","!SampleLocationPhysicalAddressCi! ' Centroid'")
    selection = arcpy.management.SelectLayerByAttribute(geocodedTownCentroidsInMemory,"NEW_SELECTION","SHAPE IS NULL")
    arcpy.management.DeleteFeatures(selection)

    # Combine address-located points with town centroid points
    arcpy.management.Append(geocodedTownCentroidsInMemory,geocodedDataTableInMemory)

    # Join towns to points
    joinedPointsInMemory = "memory/GWCDPoints_TownJoin"
    arcpy.analysis.SpatialJoin(geocodedDataTableInMemory, townBounds, "memory/GWCDPoints_TownJoin", "JOIN_ONE_TO_ONE", "KEEP_ALL", "", "INTERSECT", "", "")
    arcpy.management.Delete(geocodedDataTableInMemory)

    return joinedPointsInMemory


joinedPointsInMemory = GetJoinedPoints(groundwaterChemistryDatabaseGISTableCleanedInMemory, groundwaterChemistryDatabaseGISAliasTable, townBounds)

def PrepareFieldsAndCalculateExceedances(joinedPointsInMemory):

    # Add new fields to the in-memory table
    calc_fields = ['Count', 'ResultCalc','AboveMCL', 'AboveSMCL', 'AboveVHA', 'AboveThreshold']
    for field in calc_fields:
        arcpy.management.AddField(joinedPointsInMemory, field, "DOUBLE")

    # Set Count to 1 if Result is not Null
    # Converting ResultValueNumeric and ReportingLimit fields from ug/L to mg/L if Uranium (VOCs are all reported in ug/L, so only some will be changed)
    # Set ResultCalc to equal 1/2 the reporting limit if non-detect
    # Exceedance dict, in order of MCL, SMCL, VHA, Threshold
    # Temp edit for nitrate and nitrite threshold to be 0 for flood analysis

    microtomiliAndExceedanceFields = ["WHResultValueNumeric","AnalyteAlias","ResultUnit","ReportingLimit","ReportingLimitUnit","Result","Count",
                                    "ResultCalc","WHResultType","AboveMCL","AboveSMCL","AboveVHA","AboveThreshold","WHResultValueAlpha"]

    # exceedenceDictionary structure: mcl, smcl, vha, threshold
    # for pH there are two smcl values
    # for hardness there are two threshold values
    exceedanceDictionary = {
        "Arsenic": (0.010, None, None, 0.001),
        "Fluoride": (4.000, 2.000, None, 0.700),
        "Gross Alpha": (15, None, None, 5),
        "Nitrate": (10, None, 5, 0),
        "Nitrite": (1, None, None, 0),
        "Total Nitrate and Nitrite": (10, None, None, 5),
        "Sodium": (None, 250, None, 15),
        "Chloride": (None, 250, None, 50),
        "Manganese": (None, 0.05, 0.3, 0.08),
        "Lead": (0.015, None, 0.001, None),
        "Iron": (None, 0.3, None, None),
        "Copper": (1.3, 1, 1.3, None),
        "Radon": (None, None, 4000, None),
        "Uranium": (0.03, None, 0.02, None),
        "Radium": (5, None, None, None),
        "TDS": (None, 500, None, None),
        "Turbidity": (None, None, None, 1),
        "Odor": (None, 3, None, None),
        "E.coli": (0, None, None, 0),
        "Total Coliform": (None, None, None, 0),
        "pH": (None, (6.5, 8.5), None, None),
        "Hardness": (None, None, None, (75, 151))
    }

    # Create selection set to run calculations on
    # Note the explicit calls of IS NULL
    # Those are needed because the NOT IN method will automatically exclude NULL values
    #  because NULL is not considered to be "in" or "not in" any list, so without the IS NULL checks,
    #  any record with a NULL value in those fields would be excluded from the selection, even if they meet all the other criteria.
    clause = (
        "(Result IS NULL OR lower(Result) NOT IN "
        "('rejected','na','n/a','rejection','no data','nd','not tested',"
        "'nda','error','see attached','')) AND "

        "(WHCombinedResult IS NULL OR lower(WHCombinedResult) NOT IN "
        "('rejected','na','n/a','rejection','no data','nd','not tested',"
        "'nda','error','error in result','see attached')) AND "

        "(WaterSource IS NULL OR lower(WaterSource) NOT IN "
        "('public','surface','lake/pond','river','stream','municipal')) AND "

        "(ClientName IS NULL OR lower(ClientName) NOT IN "
        "('learning','school','elem','elementary','daycare','childcare',"
        "'district','childhood','uvmmc','vt agriculture environmental lab',"
        "'early ed','uvm-','uvm','city market','vt agency of agriculture',"
        "'vdh quarterly','vdh lab','vdh laboratory','vdh bottle','uhs',"
        "'child care','environmental health','childrens','academy')) AND "

        "(SamplingLocationDescription IS NULL OR "
        "lower(SamplingLocationDescription) NOT IN "
        "('learning','school','elem','elementary','daycare','childcare',"
        "'district','childhood','uvmmc','early ed','uvm-','vdh laboratory')) AND "

        "(lower(PostTreatmentSample) = 'n' OR PostTreatmentSample IS NULL)"
    )

    calculationSelection = arcpy.management.SelectLayerByAttribute(joinedPointsInMemory,"NEW_SELECTION",clause)
    
    # export joinedPointsInMemory in excel format for records where radon in derby
    # create a selection for radon in derby
    #clauseRadonDerby = "AnalyteAlias = 'Radon' AND TOWNNAME = 'DERBY'"
    #calculationSelectionRadonDerby = arcpy.management.SelectLayerByAttribute(joinedPointsInMemory,"NEW_SELECTION",clauseRadonDerby)
    #outputExcelPath = r"D:/ScratchSpace/Radon_Derby_Records.xlsx"
    #arcpy.conversion.TableToExcel(calculationSelectionRadonDerby, outputExcelPath)

    #clause = "lower(Result) NOT IN ('rejected','na','n/a','rejection','no data','nd','not tested','nda','error','see attached','') And " \
    #    "lower(WHCombinedResult) NOT IN ('rejected','na','n/a','rejection','no data','nd','not tested','nda','error','see attached','') And " \
    #    "lower(WaterSource) NOT IN ('public','surface','lake/pond','river','stream','municipal') And " \
    #    "lower(ClientName) NOT IN ('learning','school','elem','elementary','daycare','childcare','district','childhood','uvmmc','VT Agriculture Environmental Lab','early ed','uvm-','uvm','City Market','VT AGENCY OF AGRICULTURE','VDH Quarterly','vdh lab','vdh laboratory','vdh bottle','uhs','child care','environmental health','childrens','academy') And " \
    #    "lower(SamplingLocationDescription) NOT IN ('learning','school','elem','elementary','daycare','childcare','district','childhood','uvmmc','early ed','uvm-','vdh laboratory') And" \
    #    "(lower(PostTreatmentSample) = 'n' OR PostTreatmentSample IS Null) And " \
    #        "AnalyteAlias = 'Radon' AND TOWNNAME = 'DERBY'"
    # subselection of calculuationSelection that is Radon in DERBY
    #calcRadon = arcpy.management.SelectLayerByAttribute(joinedPointsInMemory, "NEW_SELECTION", clause)
    #arcpy.management.GetCount(calcRadon)
    #arcpy.management.GetCount(calculationSelection)



    with arcpy.da.UpdateCursor(calculationSelection, microtomiliAndExceedanceFields) as updateCursor:
        for row in updateCursor:
            WHResultValueNumeric,AnalyteName,ResultUnit,ReportingLimit,ReportingLimitUnit, \
            Result,Count,ResultCalc,WHResultType,AboveMCL,AboveSMCL,AboveVHA,AboveThreshold,WHResultValueAlpha = row

            # Set count values to 1 when there is a result (most results are Analyte 'odor' test results, some are values when odor is irrelevant)
            Count = None if Result is None else 1

            # Converting ResultValueNumeric and ReportingLimit fields for Uranium and Chloride from ug/L to mg/L
            # and pCI/L to mg/L for Uranium (VOCs are all reported in ug/L so Vic didn't want to change them all)
            if AnalyteName == "Uranium" and ResultUnit == "ug/L":
                WHResultValueNumeric = WHResultValueNumeric * 0.001
                ResultUnit = "mg/L"
                if ReportingLimit is not None:
                    ReportingLimit = ReportingLimit * 0.001
                    ReportingLimitUnit = "mg/L"
            elif AnalyteName == "Chloride" and ResultUnit == "ug/L":
                WHResultValueNumeric = WHResultValueNumeric * 0.001
                ResultUnit = "mg/L"
                if ReportingLimit is not None:
                    ReportingLimit = ReportingLimit * 0.001
                    ReportingLimitUnit = "mg/L"
            elif AnalyteName == "Uranium" and ResultUnit == "pCi/L":
                WHResultValueNumeric = WHResultValueNumeric * 0.00149
                ResultUnit = "mg/L"
                if ReportingLimit is not None:
                    ReportingLimit = ReportingLimit * 0.00149
                    ReportingLimitUnit = "mg/L"

            # Setting ResultCalc to equal 1/2 the reporting limit if non-detect
            if WHResultType == "<" and AnalyteName not in ["Total Coliform","E.coli","Hardness"]:
                if ReportingLimit is not None:
                    ResultCalc = ReportingLimit/2
            else:
                ResultCalc = WHResultValueNumeric

            # Exceedance Calculations ===================================================================================== HANDLE THE UNUSED ANALYTE VALUES
            if AnalyteName in exceedanceDictionary and AnalyteName not in ["Total Coliform","E.coli","Hardness","pH"]:
                mcl, smcl, vha, threshold = exceedanceDictionary[AnalyteName]
                if ResultCalc:
                    AboveMCL = 1 if mcl and ResultCalc > mcl else 0 if mcl and ResultCalc <= mcl else None
                    AboveSMCL = 1 if smcl and ResultCalc > smcl else 0 if smcl and ResultCalc <= smcl else None
                    AboveVHA = 1 if vha and ResultCalc > vha else 0 if vha and ResultCalc <= vha else None
                    AboveThreshold = 1 if threshold and ResultCalc > threshold else 0 if threshold and ResultCalc <= threshold else None

            elif AnalyteName in ["E.coli","Total Coliform","pH","Hardness"]:
                mcl, smcl, vha, threshold = exceedanceDictionary[AnalyteName]
                ecoli = AnalyteName == "E.coli"
                total_coliform = AnalyteName == "Total Coliform"
                ph = AnalyteName == "pH"
                hardness = AnalyteName == "Hardness"
                present_or_detected = WHResultValueAlpha in {"Present", "Detected"}
                absent_or_not_detected = WHResultValueAlpha in {"Absent", "Not detected"}
                equal_or_greater = WHResultType in {"=", ">"}
                less_than = WHResultType == "<"

                if mcl:
                    if ResultCalc is None:
                        if total_coliform:
                            AboveMCL = 1 if present_or_detected else 0 if absent_or_not_detected else None
                    elif ResultCalc is not None:
                        if total_coliform:
                            AboveMCL = 1 if ResultCalc > mcl and equal_or_greater else 0 if (ResultCalc == 1 and (equal_or_greater or less_than)) or (ResultCalc < mcl) else None
                    else:
                        AboveMCL = None

                if smcl and ResultCalc is not None and ph:
                    AboveSMCL = 1 if ResultCalc < smcl[0] or ResultCalc > smcl[1] else 0 if ResultCalc >= smcl[0] and ResultCalc <= smcl[1] else None

                if ecoli:
                    if ResultCalc is None:
                        AboveMCL = 1 if present_or_detected else 0 if absent_or_not_detected else None
                    elif ResultCalc is not None:
                        AboveMCL = 1 if ResultCalc > mcl and equal_or_greater else 0 if ResultCalc < mcl or less_than else None
                    else:
                        AboveMCL = None

                if total_coliform:
                    if ResultCalc is None:
                        AboveThreshold = 1 if present_or_detected else 0 if absent_or_not_detected else None
                    elif ResultCalc is not None:
                        AboveThreshold = 1 if ResultCalc > threshold and equal_or_greater else 0 if (ResultCalc == 1 and (equal_or_greater or less_than)) or (ResultCalc < threshold) else None

                elif threshold and hardness and ResultCalc is not None:
                    AboveThreshold = 1 if ResultCalc < threshold[0] or ResultCalc > threshold[1] else 0 if ResultCalc >= threshold[0] and ResultCalc <= threshold[1] else None
                else:
                    AboveThreshold = None
            
            updatedRow = (WHResultValueNumeric,AnalyteName,ResultUnit,ReportingLimit,ReportingLimitUnit,
                Result,Count,ResultCalc,WHResultType,AboveMCL,AboveSMCL,AboveVHA,AboveThreshold,WHResultValueAlpha)
            
            updateCursor.updateRow(updatedRow)

    # Summary of what the calculation above are doing:
    # 1. Count is set to 1 if there is a result value, otherwise it is set to None. 
    #       This is used for counting the number of results for a given analyte/location grouping, but doesn't count non-detects that don't have a numeric result value.
    # 2. ResultCalc is the field used for all exceedance calculations, 
    #       and is set to the numeric result value when there is a value, 
    #       and set to 1/2 the reporting limit when there is a non-detect with a numeric reporting limit. 
    #       If there is a non-detect without a numeric reporting limit, ResultCalc is set to None and it is not included in any exceedance calculations.
    # 3. AboveMCL, AboveSMCL, AboveVHA, and AboveThreshold are set to 1 when the ResultCalc value exceeds the respective exceedance level, 
    #       0 when it is at or below the exceedance level, 
    #       and None when it cannot be determined if it is above or below the exceedance level (e.g. non-detect without a numeric reporting limit).


    # Account for multiple records for the same analyte at the same geocoded address
    # If the result is numeric, the highest result will be kept for a unique address. If not numeric, the most recent reported date/time is taken.
    unique_records = {}
    unique_location_fields = ["ConcatAddress", "AnalyteAlias", "TOWNNAME", "ResultCalc", "Record_uid", "ReportedDateTime", "AboveThreshold"]
    with arcpy.da.SearchCursor(calculationSelection, unique_location_fields) as cursor:
        for row in cursor:
            concatAddress,analyteName,townName,resultCalc,record_uid,reportedDateTime,aboveThreshold = row
            key = (concatAddress, analyteName, townName)

            if key not in unique_records:
                unique_records[key] = (resultCalc, record_uid, reportedDateTime, aboveThreshold)
            else:
                existing_result, existing_record_uid, existing_reported_datetime, existing_above_threshold = unique_records[key]

                # Check if the current record and existing record are not None
                if resultCalc is not None and existing_result is not None:
                    # Compare the Result_Calc values
                    if resultCalc > existing_result:
                        unique_records[key] = (resultCalc, record_uid, reportedDateTime, aboveThreshold)
                    elif resultCalc == existing_result and reportedDateTime is not None and existing_reported_datetime is not None:
                        if reportedDateTime > existing_reported_datetime:
                            unique_records[key] = (resultCalc, record_uid, reportedDateTime, aboveThreshold)
                elif resultCalc is not None:
                    # Handle case where existing_result is None
                    unique_records[key] = (resultCalc, record_uid, reportedDateTime, aboveThreshold)

                # Add the new condition here
                elif resultCalc is None and analyteName in ["Total Coliform", "E.coli"]:
                    # Check if the AboveThreshold value should be updated
                    if aboveThreshold == 1 and existing_above_threshold == 0:
                        unique_records[key] = (resultCalc, record_uid, reportedDateTime, aboveThreshold)
                    elif aboveThreshold == 1 and existing_above_threshold == 1:
                        # Check if reported_datetime and existing_reported_datetime are not None
                        if reportedDateTime is not None and existing_reported_datetime is not None:
                            # Compare reported_datetime for records with AboveThreshold = 1
                            if reportedDateTime > existing_reported_datetime:
                                unique_records[key] = (resultCalc, record_uid, reportedDateTime, aboveThreshold)

    # Final passing of unique analyte/location records to keep
    records_to_keep = set()
    for result_calc, record_uid, reported_datetime, _ in unique_records.values():
        records_to_keep.add(record_uid)

    # Updating in memory copy of GWCDedit to delete record UIDs not in records_to_keep
    # Mark records to delete using ConcatAddress field
    with arcpy.da.UpdateCursor(calculationSelection, ["Record_uid","ConcatAddress"]) as updateCursor:
        for row in updateCursor:
            if row[0] not in records_to_keep:
                row[1] = "DELETE"
                updateCursor.updateRow(row)
                #updateCursor.deleteRow()

    # Exceedance Summation Calculations (based on unique AnalyteName and spatial TOWNNAME groupings)
    # The following fields are added and summarized by this index: CityCount, [CityAboveMCL,SMCL,VHA,Threshold], [PctAboveMCL,SMCL,VHA,Threshold], Mean, Median, Min, Max, Percentile95, StdDev
    # Mean, Median, Min, Max, Percentile95, StdDev are based on the ResultCalc field, so if a record was non-detect, half of the reporting limit is used

    gwcdinmem_fields = [field.name for field in arcpy.ListFields(calculationSelection)]
    # Read the data using a search cursor and store it in a defaultdict
    data = defaultdict(list)
    with arcpy.da.SearchCursor(calculationSelection, gwcdinmem_fields) as cursor:
        for row in cursor:
            analyte_name = row[gwcdinmem_fields.index('AnalyteAlias')]
            town_name = row[gwcdinmem_fields.index('TOWNNAME')]
            if town_name is not None and analyte_name is not None:
                analyte_city = analyte_name + '|' + town_name
                data[analyte_city].append(row)
            else:
                pass

    # Calculate the required values for each unique combination of 'AnalyteName' and 'City'
    unique_results = {}
    for analyte_city, records in data.items():
        result_calcs = [record[gwcdinmem_fields.index('ResultCalc')] for record in records if record[gwcdinmem_fields.index('ResultCalc')] is not None]
        num_above_mcl = [record[gwcdinmem_fields.index('AboveMCL')] for record in records if record[gwcdinmem_fields.index('AboveMCL')] is not None]
        num_above_smcl = [record[gwcdinmem_fields.index('AboveSMCL')] for record in records if record[gwcdinmem_fields.index('AboveSMCL')] is not None]
        num_above_vha = [record[gwcdinmem_fields.index('AboveVHA')] for record in records if record[gwcdinmem_fields.index('AboveVHA')] is not None]
        num_above_threshold = [record[gwcdinmem_fields.index('AboveThreshold')] for record in records if record[gwcdinmem_fields.index('AboveThreshold')] is not None]
        count = [record[gwcdinmem_fields.index('Count')] for record in records if record[gwcdinmem_fields.index('Count')] is not None]
        analyte_name_value = records[0][gwcdinmem_fields.index('AnalyteAlias')]

        if result_calcs:
                if analyte_name_value == "Arsenic":
                    round_mean = round_median = round_min = round_max = round_percentile95 = round_stddev = 4
                elif analyte_name_value == "Fluoride":
                    round_mean = round_median = round_min = round_max = round_percentile95 = round_stddev = 3
                elif analyte_name_value == "Gross Alpha":
                    round_mean = round_median = round_min = round_max = round_percentile95 = round_stddev = 1
                elif analyte_name_value == "Nitrate":
                    round_mean = round_median = round_min = round_max = round_percentile95 = round_stddev = 4
                elif analyte_name_value == "Radon":
                    round_mean = round_median = round_min = round_max = round_percentile95 = round_stddev = 1
                elif analyte_name_value == "Uranium":
                    round_mean = round_median = round_min = round_max = round_percentile95 = round_stddev = 6
                else:
                    round_mean = round_median = round_min = round_max = round_percentile95 = round_stddev = 6  # Default rounding

        if result_calcs:
            unique_results[analyte_city] = {
                'CityCount': round(sum(count)),
                'CityAboveMCL': round(sum(num_above_mcl)) if num_above_mcl else None,
                'CityAboveSMCL': round(sum(num_above_smcl)) if num_above_smcl else None,
                'CityAboveVHA': round(sum(num_above_vha)) if num_above_vha else None,
                'CityAboveThreshold': round(sum(num_above_threshold)) if num_above_threshold else None,
                'PctAboveMCL': round((sum(num_above_mcl) / sum(count)) * 100, 1) if num_above_mcl else None,
                'PctAboveSMCL': round((sum(num_above_smcl) / sum(count)) * 100, 1) if num_above_smcl else None,
                'PctAboveVHA': round((sum(num_above_vha) / sum(count)) * 100, 1) if num_above_vha else None,
                'PctAboveThreshold': round((sum(num_above_threshold) / sum(count)) * 100, 1) if num_above_threshold else None,
                'Mean': round(np.mean(result_calcs), round_mean),
                'Median': round(np.median(result_calcs), round_median),
                'Min_': round(np.min(result_calcs), round_min),
                'Max_': round(np.max(result_calcs), round_max),
                'Percentile95': round(np.percentile(result_calcs, 95), round_percentile95),
                'StdDev': round(np.std(result_calcs), round_stddev)
            }

    # Add the new fields to the in-memory table
    unique_calc_fields = ['CityCount', 'CityAboveMCL', 'CityAboveSMCL', 'CityAboveVHA', 'CityAboveThreshold', 'PctAboveMCL', 'PctAboveSMCL', 'PctAboveVHA', 'PctAboveThreshold', 'Mean', 'Median', 'Min_', 'Max_', 'Percentile95', 'StdDev']
    for field in unique_calc_fields:
        arcpy.AddField_management(calculationSelection, field, "DOUBLE")

    gwcdtable_fields = [field.name for field in arcpy.ListFields(calculationSelection)]
    with arcpy.da.UpdateCursor(calculationSelection, gwcdtable_fields) as cursor:
        for row in cursor:
            analyte_name = row[gwcdinmem_fields.index('AnalyteAlias')]
            town_name = row[gwcdinmem_fields.index('TOWNNAME')]

            if analyte_name is not None and town_name is not None:
                analyte_city = analyte_name + '|' + town_name

                # Check if analyte_city exists in unique_results before updating fields
                if analyte_city in unique_results:
                    for field in unique_calc_fields:
                        row[gwcdtable_fields.index(field)] = unique_results[analyte_city][field]
                    cursor.updateRow(row)

    return calculationSelection, groundwaterChemistryDatabaseGISPoints


joinedPointsInMemory, groundwaterChemistryDatabaseGISPoints = PrepareFieldsAndCalculateExceedances(joinedPointsInMemory)

# Append all points to SQL
arcpy.management.SelectLayerByAttribute(joinedPointsInMemory,"CLEAR_SELECTION")
arcpy.management.DeleteFeatures(groundwaterChemistryDatabaseGISPoints)
arcpy.management.Append(joinedPointsInMemory, groundwaterChemistryDatabaseGISPoints, "NO_TEST")


# Make the same selection to remove records prior to creating the external table
    # Note the explicit calls of IS NULL
    # Those are needed because the NOT IN method will automatically exclude NULL values
    #  because NULL is not considered to be "in" or "not in" any list, so without the IS NULL checks,
    #  any record with a NULL value in those fields would be excluded from the selection, even if they meet all the other criteria.
clause = (
    "(Result IS NULL OR lower(Result) NOT IN "
    "('rejected','na','n/a','rejection','no data','nd','not tested',"
    "'nda','error','see attached','')) AND "

    "(WHCombinedResult IS NULL OR lower(WHCombinedResult) NOT IN "
    "('rejected','na','n/a','rejection','no data','nd','not tested',"
    "'nda','error','see attached','')) AND "

    "(WaterSource IS NULL OR lower(WaterSource) NOT IN "
    "('public','surface','lake/pond','river','stream','municipal')) AND "

    "(ClientName IS NULL OR lower(ClientName) NOT IN "
    "('learning','school','elem','elementary','daycare','childcare',"
    "'district','childhood','uvmmc','vt agriculture environmental lab',"
    "'early ed','uvm-','uvm','city market','vt agency of agriculture',"
    "'vdh quarterly','vdh lab','vdh laboratory','vdh bottle','uhs',"
    "'child care','environmental health','childrens','academy')) AND "

    "(SamplingLocationDescription IS NULL OR "
    "lower(SamplingLocationDescription) NOT IN "
    "('learning','school','elem','elementary','daycare','childcare',"
    "'district','childhood','uvmmc','early ed','uvm-','vdh laboratory')) AND "

    "(lower(PostTreatmentSample) = 'n' OR PostTreatmentSample IS NULL)"
)
       
selection = arcpy.management.SelectLayerByAttribute(joinedPointsInMemory,"NEW_SELECTION",clause)
selection = arcpy.management.SelectLayerByAttribute(selection,"SWITCH_SELECTION")
arcpy.management.DeleteRows(selection)

# Remove duplicates per town and nulls in the analyte alias field
fields = "AnalyteAlias;TOWNNAME;TOWNNAMEMC;CityCount;CityAboveMCL;CityAboveSMCL;CityAboveVHA;CityAboveThreshold;PctAboveMCL;PctAboveSMCL;PctAboveVHA;PctAboveThreshold;Mean;Median;Min_;Max_;Percentile95;StdDev"
arcpy.management.DeleteField(joinedPointsInMemory, fields, 'KEEP_FIELDS')
arcpy.management.DeleteIdentical(joinedPointsInMemory, fields)
arcpy.management.MakeFeatureLayer(joinedPointsInMemory, "joinedPointsInMemory_lyr")
arcpy.management.SelectLayerByAttribute("joinedPointsInMemory_lyr","NEW_SELECTION","AnalyteAlias = ''")
arcpy.management.DeleteFeatures("joinedPointsInMemory_lyr")
arcpy.management.Delete("joinedPointsInMemory_lyr")

# Flatten points to a table
externalTableInMemory = "memory/ExternalTableInMemory"
arcpy.conversion.TableToTable(joinedPointsInMemory, "memory", "ExternalTableInMemory")
arcpy.management.Delete(joinedPointsInMemory)
# Add pop-up calculations for web app
mapFields = ["MapMean","MapMedian","MapMin","MapMax","MapPercentile95","MapStdDev","MapMDL"]
for field in mapFields:
    arcpy.management.AddField(externalTableInMemory, field, "TEXT", "", "", 100, field)
arcpy.management.AddField(externalTableInMemory, "MapPopupHeading", "TEXT", "", "", 255, "MapPopupHeading")
fields = ["AnalyteAlias","Mean","Median","Min_","Max_","Percentile95","StdDev",
          "MapMean","MapMedian","MapMin","MapMax","MapPercentile95","MapStdDev","MapMDL","MapPopupHeading",
          "CityAboveMCL","PctAboveMCL","CityAboveThreshold","PctAboveThreshold","CityAboveVHA","PctAboveVHA","CityAboveSMCL","PctAboveSMCL",
          "TOWNNAME","CityCount"]

with arcpy.da.UpdateCursor(externalTableInMemory, fields) as updateCursor:
    for row in updateCursor:
        analyteAlias,mean,median,min_,max_,percentile95,stdDev, \
        mapMean,mapMedian,mapMin,mapMax,mapPercentile95,mapStdDev,mapMDL,mapPopupHeading, \
        cityAboveMCL,pctAboveMCL,cityAboveThreshold,pctAboveThreshold,cityAboveVHA,pctAboveVHA,CityAboveSMCL,PctAboveSMCL, \
        townName,cityCount = row

        # Suppress those towns with fewer than 20 samples
        if cityCount is not None:
            if float(cityCount) < 20:
                updateCursor.deleteRow()
                continue
        
        if mean is not None:

            if analyteAlias == "Arsenic":
                cityAboveValue = cityAboveMCL
                pctAboveValue = pctAboveMCL
                thresholdValue = "MCL (0.010 mg/L)"
                popupFooterThreshold = 0.001
                popupFooterUnits = "mg/L"
            elif analyteAlias == "Fluoride":
                cityAboveValue = cityAboveThreshold
                pctAboveValue = pctAboveThreshold
                thresholdValue = "PHS (0.7 mg/L)"
                popupFooterThreshold = 0.3
                popupFooterUnits = "mg/L"
            elif analyteAlias == "Gross Alpha":
                cityAboveValue = cityAboveMCL
                pctAboveValue = pctAboveMCL
                thresholdValue = "MCL (15 pCi/L)"
                popupFooterThreshold = 1.50
                popupFooterUnits = "pCi/L"
            elif analyteAlias == "Nitrate":
                cityAboveValue = cityAboveMCL
                pctAboveValue = pctAboveMCL
                thresholdValue = "MRL (10 mg/L)"
                popupFooterThreshold = 0.5
                popupFooterUnits = "mg/L"
            elif analyteAlias == "Radon":
                cityAboveValue = cityAboveVHA
                pctAboveValue = pctAboveVHA
                thresholdValue = "VHA (4,000 pCi/L)"
                popupFooterThreshold = 100
                popupFooterUnits = "pCi/L"
            elif analyteAlias == "Uranium":
                cityAboveValue = cityAboveVHA
                pctAboveValue = pctAboveVHA
                thresholdValue = "VMCL (0.020 mg/L)"
                popupFooterThreshold = 0.001
                popupFooterUnits = "mg/L"
            else:
                cityAboveValue = None
                pctAboveValue = None
                thresholdValue = None
                popupFooterThreshold = None
                popupFooterUnits = None

            if cityAboveValue in [0,None]:
                mapPopupHeading = f"There are no {analyteAlias.lower()} tests above the {thresholdValue} in {townName}."
            else:
                mapPopupHeading = f"{round(pctAboveValue,1)} % of {analyteAlias.lower()} tests ({cityAboveValue} out of {cityCount}) are above the {thresholdValue} in {townName}."

            mapMean = "*" if mean < 0.001 else str(round(mean,3)) + f" {popupFooterUnits}"
            mapMedian = "*" if median < 0.001 else str(round(median,3)) + f" {popupFooterUnits}"
            mapMin = "*" if min_ < 0.001 else str(round(min_,3)) + f" {popupFooterUnits}"
            mapMax = "*" if max_ < 0.001 else str(round(max_,3)) + f" {popupFooterUnits}"
            mapPercentile95 = "*" if percentile95 < 0.001 else str(round(percentile95,3)) + f" {popupFooterUnits}"
            mapStdDev = "*" if stdDev < 0.001 else str(round(stdDev,3)) + f" {popupFooterUnits}"
            mapMDL = (f"* Less than the reporting limit (RL) of the laboratory test, typically {str(popupFooterThreshold)} {popupFooterUnits} for {analyteAlias.lower()}."
                    if any(stat < 0.001 for stat in [mean, median, min_, max_, percentile95, stdDev])
                    else "")

        updatedRow = (analyteAlias,mean,median,min_,max_,percentile95,stdDev, \
                mapMean,mapMedian,mapMin,mapMax,mapPercentile95,mapStdDev,mapMDL,mapPopupHeading, \
                cityAboveMCL,pctAboveMCL,cityAboveThreshold,pctAboveThreshold,cityAboveVHA,pctAboveVHA,CityAboveSMCL,PctAboveSMCL, \
                townName,cityCount)
        
        updateCursor.updateRow(updatedRow)

# Append to SQL
arcpy.management.DeleteRows(groundwaterChemistryDatabaseGISPointTableExternal)
arcpy.management.Append(externalTableInMemory, groundwaterChemistryDatabaseGISPointTableExternal, "NO_TEST")

# Rebuild indexes
# (commented-out alternate indexing calls redacted - referenced an internal server path)
arcpy.management.RebuildIndexes(GDBEnvHealthEditor, "NO_SYSTEM", os.path.basename(groundwaterChemistryDatabaseGISTable), "ALL")
arcpy.management.RebuildIndexes(GDBEnvHealthEditor, "NO_SYSTEM", os.path.basename(groundwaterChemistryDatabaseGISPoints), "ALL")
arcpy.management.RebuildIndexes(GDBEnvHealthEditor, "NO_SYSTEM", os.path.basename(groundwaterChemistryDatabaseGISPointTableExternal), "ALL")

# Update data updated date field

# Azure AD App Registration details
# NOTE: real credentials redacted for this public-facing copy.
client_id = "<REDACTED>"
client_secret = "<REDACTED>"
tenant_id = "<REDACTED>"

# SharePoint and file details
site_url = "vermontgov.sharepoint.com:/teams/AHS.GISAdministrationGroup"
list_id = "<REDACTED_LIST_ID>"

# Step 1: Get access token from Azure AD
url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
headers = {
    'Content-Type': 'application/x-www-form-urlencoded'
}
data = {
    'grant_type': 'client_credentials',
    'client_id': client_id,
    'client_secret': client_secret,
    'scope': 'https://graph.microsoft.com/.default'
}
response = requests.post(url, headers=headers, data=data)
response.raise_for_status()
access_token = response.json().get('access_token')

# Step 2: Get the site ID
endpoint = f"https://graph.microsoft.com/v1.0/sites/{site_url}"
headers = {
    'Authorization': f'Bearer {access_token}'
}
response = requests.get(endpoint, headers=headers)
response.raise_for_status()
site_id = response.json().get('id')

adjusted_time = datetime.now() + timedelta(hours=4)
new_date = adjusted_time.isoformat() + "Z"

headers = {
    "Authorization": f"Bearer {access_token}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# Step 1: Get all list items
url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/items?expand=fields"
response = requests.get(url, headers=headers)

items = response.json().get("value", [])

for item in items:
    item_id = item.get("id")
    fields = item.get("fields", {})
    if fields.get("ApplicationDomain1") == "Groundwater Chemistry":
        update_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/items/{item_id}/fields"
        payload = {
            "LatestDataUpdate": new_date
        }
        patch_resp = requests.patch(update_url, headers=headers, json=payload)



# Long to wide csv export
# ===================================================================

# --- 1. Configuration ---
OUTPUT_ITEM_TITLE = 'PivotedGroundwaterData'
AGOL_PORTAL_URL = 'https://ahs-vt.maps.arcgis.com/'
AGOL_FOLDER_NAME = 'Water Quality Internal'

fields_of_interest = ["AnalyteAlias", "ConcatAddress", "Result", "ResultUnit", "SampleCollectionDateTime"]

unique_analytes = tuple(set([row[0] for row in arcpy.da.SearchCursor(
    groundwaterChemistryDatabaseGISPoints, ["AnalyteAlias"]
) if row[0] is not None and row[0] != '']))

clause = f"lower(ConcatAddress) NOT IN ('delete') AND lower(ConcatAddress) NOT LIKE '%centroid%' AND AnalyteAlias IN {unique_analytes}"

numpy_array = arcpy.da.TableToNumPyArray(
    groundwaterChemistryDatabaseGISPoints, fields_of_interest, where_clause=clause
)
df = pd.DataFrame(numpy_array)
df.sort_values(['ConcatAddress', 'AnalyteAlias', 'SampleCollectionDateTime'], inplace=True)
df['sample_num'] = df.groupby(['ConcatAddress', 'AnalyteAlias']).cumcount() + 1

wide_df = df.pivot_table(
    index=['ConcatAddress', 'AnalyteAlias'],
    columns='sample_num',
    values=['Result', 'ResultUnit', 'SampleCollectionDateTime'],
    aggfunc='first'
)

wide_df.columns = [f'{val}{num}' for val, num in wide_df.columns]
wide_df.reset_index(inplace=True)

key_cols = ['AnalyteAlias', 'ConcatAddress']
data_cols = sorted(
    [col for col in wide_df.columns if col not in key_cols],
    key=lambda x: (int("".join(filter(str.isdigit, x))), x)
)

wide_df = wide_df[key_cols + data_cols]

date_cols = wide_df.filter(like='SampleCollectionDateTime').columns
for col in date_cols:
    wide_df[col] = pd.to_datetime(wide_df[col]).dt.strftime('%Y-%m-%d %H:%M:%S')

temp_dir = tempfile.gettempdir()
output_csv_path = os.path.join(temp_dir, f"{OUTPUT_ITEM_TITLE}.csv")
output_zip_path = os.path.join(temp_dir, f"{OUTPUT_ITEM_TITLE}.zip")

wide_df.to_csv(output_csv_path, index=False, encoding='utf-8')
with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.write(output_csv_path, arcname=os.path.basename(output_csv_path))

gis = GIS(AGOL_PORTAL_URL, username=agoUsername, password=agoPassword)
query = f'title:"{OUTPUT_ITEM_TITLE}" AND owner:{gis.users.me.username}'
search_results = gis.content.search(query=query, item_type='CSV')

existing_item = next((item for item in search_results if item.title == OUTPUT_ITEM_TITLE), None)

existing_item.update(data=output_zip_path)
if os.path.exists(output_csv_path):
    os.remove(output_csv_path)
if os.path.exists(output_zip_path):
    os.remove(output_zip_path)