"""
NMVS Busines Intelligense Data Extractor (NMVS-BIDE)

Purpose:
- Ingest data from SSR NMVS Blueprint Reporting API
- Normalize datatypes (dates, numerics)
- Persist into MySQL with utf8mb4 encoding
- Create simple indexes on selected columns
"""

# =========================
# Standard library imports
# =========================
import logging
import argparse
import hashlib
import io
import os
import sys
from io import StringIO, BytesIO
from datetime import datetime, timezone, timedelta

# =========================
# Third-party imports
# - pandas: CSV/DataFrame utilities, to_sql
# - SQLAlchemy: DB engine, data types, raw SQL
# =========================
import pandas as pd
from sqlalchemy import (
    create_engine, event, text,
    DateTime, Integer, String, Boolean
)
from sqlalchemy.dialects.mysql import DATETIME, VARCHAR

# =========================
# Local imports
# - Reports: NMVS webservice wrapper
# - Refdata, Refdata2, Swissmedic: master-data importers
# - MyConfiguration: central config (env, logging, DB URL/name)
# =========================
from nmvs.importer.nmvs_data import Reports
# from nmvs.importer.master_data import Refdata, Refdata2, Swissmedic
from nmvs.conf.myconfigparser import MyConfiguration

# ======================================================
# Logging Initialization Helper
# ======================================================
def init_logging():
    """Initialize logging via MyConfiguration or fallback."""
    try:
        MyConfiguration.initialize_logging()
    except Exception:
        logging.basicConfig(level=logging.INFO)


def run_environment_checks():
    """Run software and environment checks without contacting external services."""
    checks_passed = True

    if sys.version_info >= (3, 11):
        print(f"OK: Python {sys.version.split()[0]}")
    else:
        print(f"FAIL: Python 3.11 or newer required, found {sys.version.split()[0]}")
        checks_passed = False

    required_modules = ("pandas", "sqlalchemy", "pymysql", "requests", "zeep")
    for module_name in required_modules:
        try:
            __import__(module_name)
            print(f"OK: {module_name} is installed")
        except ImportError:
            print(f"FAIL: {module_name} is not installed")
            checks_passed = False

    required_environment = (
        "database_url",
        "nmvs_report_url",
        "nmvs_token_url",
        "nmvs_client_id",
        "nmvs_client_secret",
        "emvs_api_version",
        "nmvs_user_agent",
    )
    for variable_name in required_environment:
        if os.getenv(variable_name):
            print(f"OK: {variable_name} is set")
        else:
            print(f"FAIL: {variable_name} is not set")
            checks_passed = False

    try:
        MyConfiguration.initialize_logging()
        print("OK: logging configuration and log directory")
        logging.info("System check run... so far good.")
    except Exception as error:
        print(f"FAIL: logging configuration: {error}")
        checks_passed = False

    try:
        reports = Reports()
        token = reports._Reports__get_token()
        if token:
            print("OK: NMVS token endpoint connectivity")
        else:
            print("FAIL: NMVS token endpoint returned no token")
            checks_passed = False
    except Exception as error:
        print(f"FAIL: NMVS token endpoint: {error}")
        checks_passed = False

    try:
        response = Reports().get_all_available_report_types()
        if response is not None and response.ok:
            print(f"OK: NMVS API connectivity (HTTP {response.status_code})")
        else:
            status = response.status_code if response is not None else "no response"
            print(f"FAIL: NMVS API connectivity ({status})")
            checks_passed = False
    except Exception as error:
        print(f"FAIL: NMVS API connectivity: {error}")
        checks_passed = False

    try:
        engine = _get_engine()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        print("OK: database connectivity")
    except Exception as error:
        print(f"FAIL: database connectivity: {error}")
        checks_passed = False

    print("Environment checks passed." if checks_passed else "Environment checks failed.")
    return checks_passed

# ======================================================================
# Utility: Get Engine
# ======================================================================
def _get_engine():
    """Create a UTF‑8 safe MySQL SQLAlchemy engine."""
    url = MyConfiguration.get_value("database_url")  
    engine = create_engine(
        url,
        pool_pre_ping=True,
        future=True,
    )
    enforce_utf8mb4(engine)
    return engine

# ======================================================================
# UTF‑8 Enforcement for MySQL Connections
# ======================================================================
def enforce_utf8mb4(engine):
    """Ensure every new DBAPI connection uses UTF‑8."""
    @event.listens_for(engine, "connect")
    def _set_names(dbapi_con, _):
        try:
            cur = dbapi_con.cursor()
            cur.execute("SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;")
            cur.close()
        except Exception:
            pass

# ======================================================
# NMVS Column Normalization
# ======================================================
def normalize_nmvs_column_name(col: str) -> str:
    """
    Apply normalization rules ONLY to NMVS tables:
        1. strip()
        2. replace spaces  -> "_"
        3. remove "(" and ")"
        4. replace "-" with "_"
        5. collapse repeated "__+" into "_"
        6. strip leading/trailing "_"
        7. preserve original capitalization
    """
    if not isinstance(col, str):
        return col

    c = col.strip()

    # Basic replacements
    c = c.replace(" ", "_")
    c = c.replace("(", "")
    c = c.replace(")", "")
    c = c.replace("-", "_")

    # Collapse multi-underscores
    while "__" in c:
        c = c.replace("__", "_")

    # Strip leading/trailing underscores
    c = c.strip("_")

    return c

def normalize_nmvs_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize all NMVS DataFrame column names using the naming rules.
    """
    df.columns = [normalize_nmvs_column_name(c) for c in df.columns]
    return df

# Reinhold : for converting datatypes. Need a better solution, e. g. create map from API Call https://api-ite.nmvo.eu/report/report-types/{reportTypeId}

# ======================================================
# DTYPE MAP FOR NMVS TABLES
# Normalized according to naming rules B2 + C2 + C3
# ======================================================

DTYPE_MAP = {

    # --------------------------------------------------
    # NMVS Products
    # --------------------------------------------------
    "NMVS_Products": {
        "Product_Code_Scheme": String(10),
        "Product_Code": VARCHAR(64),
        "Product_State": String(255),
        "Product_Name": String(600),
        "Product_Common_Name": String(600),
        "Product_Version_Number": Integer(),
        "Pack_Type": String(255),
        "Pack_Size": Integer(),
        "Form": String(255),
        "Strength": String(255),
        "National_Code": String(255),
        "Article_57_Code": String(255),
        "Creation_Date": DateTime(),
        "MAH_Name": String(255),
        "EMVS_MAH_Id": String(255),
        "OBP_Id": String(255),
        "OBP_Name": String(255),
        "Withdrawal_Date": DateTime(),
        "Withdrawal_Reason": String(255),
        "Number_Of_Batches": Integer(),
        "Number_Of_Packs": Integer(),
        "Number_Of_Active_Packs": Integer(),
        "_load_date_utc": DateTime(),
    },

    # --------------------------------------------------
    # NMVS Batches
    # --------------------------------------------------
    "NMVS_Batches": {
        "Product_Code_Scheme": String(10),
        "Product_Code": VARCHAR(64),
        "Batch_Id": VARCHAR(64),
        "Batch_Expiry_Date": String(6),
        "Batch_State": String(50),
        "Is_Multimarket": String(10),
        "Product_Version_Number": Integer(),
        "Creation_Date": DateTime(),
        "Manufacturer_Name": String(255),
        "Recall_Date": DateTime(),
        "Recall_Reason": String(255),
        "Markets": String(255),
        "Min_SN_Length": Integer(),
        "Max_SN_Length": Integer(),
        "SN_Format": String(10),
        "Number_Of_Packs": Integer(),
        "Batch_Length": Integer(),
        "Batch_Format": String(10),
        "Number_Of_Active_Packs": Integer(),
        "_load_date_utc": DateTime(),
    },

    # --------------------------------------------------
    # NMVS Organisations
    # --------------------------------------------------
    "NMVS_Organisations": {
        "Organisation_Id": Integer(),
        "Organisation_Type": String(50),
        "Organisation_Sub_Type": String(50),
        "Organisation_Name": VARCHAR(255),
        "Organisation_Status": String(50),
        "Creation_Date": DateTime(),
        "Registration_Date": DateTime(),
        "Rate_Limiting_Plan": String(50),
        "Expiry_Date": DateTime(),
        "_load_date_utc": DateTime(),
    },

    # --------------------------------------------------
    # NMVS Locations
    # --------------------------------------------------
    "NMVS_Locations": {
        "Organisation_Id": Integer(),
        "Organisation_Type": String(50),
        "Organisation_Sub_Type": String(50),
        "Organisation_Name": VARCHAR(255),
        "Location_Id": String(255),
        "Location_Name": String(255),
        "Legitimacy_Information": String(255),
        "Address": String(255),
        "City": String(255),
        "Postal_Code": String(10),
        "Equipment_Count": Integer(),
        "Location_Status": String(50),
        "Creation_Date": DateTime(),
        "_load_date_utc": DateTime(),
    },

    # --------------------------------------------------
    # NMVS API Versions
    # --------------------------------------------------
    "NMVS_API_Versions": {
        "Organisation_Id": Integer(),
        "Organisation_Type": String(50),
        "Organisation_Name": String(255),
        "Prime_Contact": String(255),
        "Prime_Contact_Email": String(255),
        "Location_Id": String(255),
        "Client_Id": String(255),
        "API_Version": String(5),
        "Requested_API_Version": String(5),
        "User_Agent": String(255),
        "IP_Address": String(255),
        "Last_API_Request": DateTime(),
        "_load_date_utc": DateTime(),
    },

    # --------------------------------------------------
    # NMVS Organisations Summary
    # --------------------------------------------------
    "NMVS_OrganisationsSummary": {
        "Organisation_ID": Integer(),
        "Creation_Date": DATETIME(fsp=3),
        "Organisation_Type": String(50),
        "Organisation_Sub_Type": String(50),
        "Organisation_Name": String(255),
        "Status": String(50),
        "Prime_Contact_First_Name": String(255),
        "Prime_Contact_Last_Name": String(255),
        "Prime_Contact_Email": String(255),
        "Rate_Limiting_Policy": String(50),
        "Organisation_Expiry_Date": DATETIME(fsp=3),
        "Number_Of_Active_Locations": Integer(),
        "Registration_Last_Invitation_Date": DATETIME(fsp=3),
        "Registration_Expiry_Date": DATETIME(fsp=3),
        "Registration_Date": DATETIME(fsp=3),
        "Has_Extended_Product_Dataset": Boolean(),
        "Known_Fact_Question_1": String(255),
        "Known_Fact_Answer_1": String(255),
        "Known_Fact_Question_2": String(255),
        "Known_Fact_Answer_2": String(255),
        "Known_Fact_Question_3": String(255),
        "Known_Fact_Answer_3": String(255),
        "Known_Fact_Question_4": String(255),
        "Known_Fact_Answer_4": String(255),
        "Known_Fact_Question_5": String(255),
        "Known_Fact_Answer_5": String(255),
        "_load_date_utc": DateTime(),
    },
}

# ======================================================================
# DATETIME NORMALIZATION
# ======================================================================
def to_mysql_datetime_series(s: pd.Series, keep_millis: bool = False) -> pd.Series:
    """
    Convert a pandas Series to a MySQL-compatible DATETIME or DATETIME(3):
        - Convert ["-", ""] → NaT
        - Parse timestamps as UTC when possible
        - Drop timezone (MySQL DATETIME is naive)
        - Keep milliseconds or floor to seconds
    """
    s = pd.to_datetime(
        s.replace(["-", ""], pd.NaT),
        errors="coerce",
        utc=True
    )

    # Convert UTC → tz-naive
    s = s.dt.tz_localize(None)

    if keep_millis:
        return s.dt.round("ms")     # DATETIME(3)
    else:
        return s.dt.floor("s")      # DATETIME

def normalize_table_datetimes(df: pd.DataFrame, cols: list[str], keep_millis: bool = False) -> None:
    """
    Normalize a list of datetime columns in-place.
    """
    for c in cols:
        if c in df.columns:
            df[c] = to_mysql_datetime_series(df[c], keep_millis=keep_millis)

# ======================================================================
# NUMERIC NORMALIZATION
# ======================================================================
def normalize_numeric(df: pd.DataFrame,
                      cols: list[str],
                      as_int: bool = False,
                      missing_markers: tuple = ("-", "", None)) -> None:
    """
    Convert numeric columns to numeric, coercing errors to NaN, replacing missing markers, and filling with 0.
    """
    for c in cols:
        if c in df.columns:
            series = df[c].replace(missing_markers, pd.NA)
            num = pd.to_numeric(series, errors="coerce").fillna(0)
            df[c] = num.astype(int) if as_int else num

# ======================================================================
# Per‑table DataFrame fix‑ups
# ======================================================================
def fix_df(df: pd.DataFrame, table: str) -> None:
    """
    Apply table-specific normalization:
      - datetime normalization
      - numeric normalization
      - boolean normalization
    Column names MUST already be normalized before calling this.
    """

    # Normalization rules for each NMVS table
    rules = {
        "NMVS_Products": dict(
            dates=[
                "Creation_Date",
                "Withdrawal_Date"
            ],
            ints=[
                "Product_Version_Number",
                "Pack_Size",
                "Number_Of_Batches",
                "Number_Of_Packs",
                "Number_Of_Active_Packs"
            ],
            keep_ms=False
        ),

        "NMVS_Batches": dict(
            dates=[
                "Creation_Date",
                "Recall_Date"
            ],
            ints=[
                "Product_Version_Number",
                "Number_Of_Packs",
                "Number_Of_Active_Packs",
                "Min_SN_Length",
                "Max_SN_Length",
                "Batch_Length"
            ],
            keep_ms=False
        ),

        "NMVS_Organisations": dict(
            dates=[
                "Creation_Date",
                "Registration_Date",
                "Expiry_Date"
            ],
            ints=[
                "Organisation_Id"
            ],
            keep_ms=False
        ),

        "NMVS_Locations": dict(
            dates=["Creation_Date"],
            ints=[
                "Organisation_Id",
                "Equipment_Count"
            ],
            keep_ms=False
        ),

        "NMVS_API_Versions": dict(
            dates=["Last_API_Request"],
            ints=["Organisation_Id"],
            keep_ms=True
        ),

        "NMVS_OrganisationsSummary": dict(
            dates=[
                "Creation_Date",
                "Organisation_Expiry_Date",
                "Registration_Last_Invitation_Date",
                "Registration_Expiry_Date",
                "Registration_Date"
            ],
            ints=["Number_Of_Active_Locations"],
            keep_ms=True
        )
    }

    # Apply table-specific rules
    if table in rules:
        r = rules[table]
        normalize_table_datetimes(
            df,
            r.get("dates", []),
            keep_millis=r.get("keep_ms", False)
        )
        normalize_numeric(
            df,
            r.get("ints", []),
            as_int=True
        )

    # Normalize boolean-like columns
    if "Has_Extended_Product_Dataset" in df.columns:
        df["Has_Extended_Product_Dataset"] = (
            df["Has_Extended_Product_Dataset"]
            .astype(str)
            .str.strip()
            .str.lower()
            .map({
                "true": True, "false": False,
                "1": True, "0": False,
                "-": False, "": False
            })
            .fillna(False)
            .astype(bool)
        )

# ==============================================================================
# Robust CSV Reading
# - Try UTF-8 first
# - Fall back to ISO-8859-1 only if UTF-8 raises UnicodeDecodeError
# ==============================================================================
def decode_text_robust(raw_bytes: bytes) -> str:
    """
    Attempt UTF-8 decoding first; fall back to ISO-8859-1.
    NMVS sometimes returns ISO-based content containing umlauts.
    """
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes.decode("iso-8859-1", errors="replace")

def split_snapshot_blocks(csv_text: str) -> list[str]:
    """
    Split the NMVS snapshot payload into blocks.
    The NMVS format uses blank lines to separate tables, but the exact
    newline sequences vary. Detect blocks robustly.
    """
    blocks = []
    current = []

    for line in csv_text.splitlines():
        if line.strip() == "":
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)

    if current:
        blocks.append("\n".join(current))

    return blocks[1:]  # block 0 is metadata; skip it

def parse_snapshot_block(block: str, prefix: str) -> tuple[str, pd.DataFrame] | None:
    """
    Parse a single NMVS snapshot block:
        line 0 = table name
        subsequent lines = CSV with headers + rows

    Returns:
        (table_name, dataframe)
    or None if parsing fails.
    """
    lines = block.strip().splitlines()
    if len(lines) < 2:
        return None  # invalid block

    # Table name (strip quotes)
    raw_table_name = lines[0].strip().strip('"')
    table_name = prefix + "_" + raw_table_name.replace(" ", "_")

    # Remainder is CSV content
    csv_payload = "\n".join(lines[1:])

    try:
        df = pd.read_csv(io.StringIO(csv_payload), dtype=str)  # keep raw strings
    except Exception as e:
        logging.error("Failed to parse snapshot block '%s': %s", table_name, e)
        return None

    # Normalize NMVS column names
    df = normalize_nmvs_columns(df)

    return table_name, df

# =============================================================================================
# NMVS Snapshot parser (for reports with multiple tables). The payload is split by blank lines.
# =============================================================================================
def parse_csv_string(csv_text: str, prefix: str = "NMVS") -> dict:
    """
    Main entry point to parse NMVS snapshot into dict:
        { table_name: { "headers": [...], "rows": [...] } }

    This structure is used by save_dict_to_mysql().
    """
    tables = {}
    blocks = split_snapshot_blocks(csv_text)

    for block in blocks:
        parsed = parse_snapshot_block(block, prefix)
        if not parsed:
            continue

        table_name, df = parsed
        tables[table_name] = {
            "headers": list(df.columns),
            "rows": df.values.tolist()
        }

    return tables

# ======================================================
# Provide a robust CSV reader
# ======================================================
def read_csv_robust(raw_bytes: bytes, skiprows: int = 0) -> pd.DataFrame:
    """
    Read CSV bytes robustly:
      - Try UTF-8
      - Fall back to ISO-8859-1 on UnicodeDecodeError
    """
    try:
        return pd.read_csv(BytesIO(raw_bytes), skiprows=skiprows, encoding="utf-8")
    except UnicodeDecodeError:
        return pd.read_csv(BytesIO(raw_bytes), skiprows=skiprows, encoding="iso-8859-1")

# ======================================================
# NMVS Writer & MySQL _load_date_utc Handling
# ======================================================
def apply_mysql_load_timestamp_default(engine, table_name: str):
    """
    Ensure _load_date_utc exists with a MySQL default.
    Compatible with MySQL 8.0 (no IF NOT EXISTS for columns).
    """

    add_sql = text(f"""
        ALTER TABLE `{table_name}`
        ADD COLUMN `_load_date_utc`
        DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3));
    """)

    modify_sql = text(f"""
        ALTER TABLE `{table_name}`
        MODIFY COLUMN `_load_date_utc`
        DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3));
    """)

    with engine.begin() as conn:
        try:
            # First try: add column (will fail if column already exists)
            conn.execute(add_sql)
        except Exception:
            # Column already exists → ignore
            pass

        # Always enforce correct default & datatype
        conn.execute(modify_sql)

    logging.info(f"_load_date_utc ensured on table '{table_name}'")

# ======================================================================
# MySQL Writer
# ======================================================================
def save_dict_to_mysql(tables: dict, engine):
    """
    Persist a dict of parsed NMVS tables to MySQL.
    Each entry consists of:
        { "headers": [...], "rows": [...] }
    Column names will already be normalized by the snapshot parser.
    """

    for table_name, table_data in tables.items():

        # Materialize a DataFrame
        df = pd.DataFrame(table_data["rows"], columns=table_data["headers"])

        # Normalize column names again defensively (snapshot parser should have done it)
        df = normalize_nmvs_columns(df)

        # Apply table-specific normalizations
        fix_df(df, table_name)

        # Look up dtype mapping (NMVS or None)
        dtype = DTYPE_MAP.get(table_name)

        logging.info(f"Writing table {table_name} to MySQL…")

        # Write to SQL (replace existing table)
        rows_written = df.to_sql(
            table_name,
            con=engine,
            if_exists="replace",
            index=False,
            method="multi",
            chunksize=10_000,
            dtype=dtype
        )

        logging.info(
            f"Table '{table_name}' successfully written: "
            f"{rows_written} records."
        )

        # If NMVS table → apply default timestamp
        if table_name in DTYPE_MAP:
            apply_mysql_load_timestamp_default(engine, table_name)

# ==================================================================================
# NMVS Organisations Summary (single CSV)
# ==================================================================================
def import_organisations_summary_report():
    """
    Import the NMVS Organisations Summary report:
      - Fetch CSV via Reports()
      - Robustly parse
      - Normalize NMVS columns
      - Apply table-specific normalization
      - Persist with dtype map
      - Ensure _load_date_utc default (MySQL-side)
    """
    table_name = "NMVS_OrganisationsSummary"
    engine = _get_engine()

    # 1) Download report
    try:
        resp = Reports().get_organisations_summary_report()
    except Exception as e:
        logging.error("Failed to request OrganisationsSummary report: %s", e)
        return

    if resp is None or not getattr(resp, "ok", False):
        logging.error("OrganisationsSummary report HTTP error or empty response.")
        return

    # 2) Parse CSV
    try:
        # NMVS often has 3 banner lines before the header; try with skiprows=3 first.
        try:
            df = read_csv_robust(resp.content, skiprows=3)
            if df.empty or df.columns.size == 1:
                # Fallback: some payloads have no banner
                df = read_csv_robust(resp.content, skiprows=0)
        except Exception:
            # Fallback catch-all
            df = read_csv_robust(resp.content, skiprows=0)
    except Exception as e:
        logging.error("Failed to parse OrganisationsSummary CSV: %s", e)
        return

    if df is None or df.empty:
        logging.warning("OrganisationsSummary CSV parsed but is empty; creating empty table with schema.")
        # Create an empty DataFrame with expected columns so to_sql can create a table
        expected_cols = list(DTYPE_MAP.get(table_name, {}).keys())
        df = pd.DataFrame(columns=expected_cols)

    # 3) Normalize NMVS column names (B2 + C2 + C3) & apply table-specific fixes
    df = normalize_nmvs_columns(df)
    fix_df(df, table_name)

    # 4) Persist to MySQL
    dtype = DTYPE_MAP.get(table_name, None)
    try:
        rows_written = df.to_sql(
            table_name,
            con=engine,
            if_exists="replace",
            index=False,
            method="multi",
            chunksize=10_000,
            dtype=dtype
        )
        logging.info(
            "Table '%s' successfully written to MySQL: %s records.",
            table_name,
            rows_written,
        )
    except Exception as e:
        logging.error("Error writing table '%s': %s", table_name, e)
        return

    # 5) Ensure MySQL-side default for _load_date_utc
    apply_mysql_load_timestamp_default(engine, table_name)

# ======================================================================
# Exceptions Importer & Merge Logic
# ======================================================================

def read_exceptions_csv(raw: bytes, skiprows: int = 3) -> pd.DataFrame:
    """
    Robust parser for the NMVS Exceptions Audit Trail CSV.
    Uses python engine to support:
      - irregular row lengths
      - embedded commas
      - embedded semicolons
      - mixed quoting
      - JSON fragments inside fields
    """
    # Try UTF-8 first
    try:
        return pd.read_csv(
            BytesIO(raw),
            skiprows=skiprows,
            engine="python",
            sep=None,              # auto-detect delimiter (, ; \t)
            on_bad_lines="skip",   # skip malformed rows
            encoding="utf-8"
        )
    except UnicodeDecodeError:
        # Fall back to ISO-8859-1
        return pd.read_csv(
            BytesIO(raw),
            skiprows=skiprows,
            engine="python",
            sep=None,
            on_bad_lines="skip",
            encoding="iso-8859-1"
        )

def parse_event_details(val: str) -> dict:
    """
    Parse Event_Details formatted like:
    Key: Value;
    Key2: Value2;

    Returns dict of {key: value}
    """
    if not isinstance(val, str):
        return {}

    result = {}
    for part in val.split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        key, value = part.split(":", 1)
        result[key.strip()] = value.strip()
    return result

# ----- Normalization for Exceptions DF -----
def normalize_exceptions_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize/prepare the Exceptions dataframe:
      - Normalize NMVS column names (B2 + C2 + C3)
      - Parse Date_and_Time_UTC with millisecond precision
      - Compute _dedupe_key (MD5)
      - Drop duplicates BY KEY
      - DO NOT add _load_date_utc (MySQL will generate default)
    """
    df = normalize_nmvs_columns(df)

    # Normalize timestamp column
    if "Date_and_Time_UTC" in df.columns:
        ts = pd.to_datetime(df["Date_and_Time_UTC"], errors="coerce", utc=True)
        df["Date_and_Time_UTC"] = ts.dt.tz_localize(None).dt.round("ms")
    
    #Ensure key columns exist so filters don't error
    for key in ("Transaction_ID", "Event_Code"):
        if key not in df.columns:
            df[key] = ""

    # Drop rows with no identifiers at all → prevents “key-only” junk rows
    df = df[~(
        df["Transaction_ID"].astype(str).str.strip().eq("") &
        df["Event_Code"].astype(str).str.strip().eq("")
    )]

    # ---- PARSE EVENT DETAILS INTO MULTIPLE COLUMNS ----
    if "Event_Details" in df.columns:
        parsed = df["Event_Details"].apply(parse_event_details)

        # List your expected keys:
        detail_keys = [
            "ActualState",
            "APIVersion",
            "AttemptedOperation",
            "BatchExpiryDate",
            "BatchId",
            "ClientEquipmentId",
            "ClientId",
            "ClientLocation",
            "ClientOrganisationId",
            "DataEntryMode",
            "EmvsErrorCode",
            "EUPublicPackState",
            "InitialState",
            "InitiatingMessageType",
            "IpAddress",
            "IsBadData",
            "IsBulk",
            "IsIntermarketResponse",
            "Location",
            "Market",
            "NumberOfDispenseAttempts",
            "PackLastUpdateLocation",
            "PackLastUpdateMarket",
            "PackLastUpdateTimestamp",
            "ProductCode",
            "ProductCodeScheme",
            "ProductName",
            "RequestedAPIVersion",
            "RequestedState",
            "SerialNumber",
            "StoredBatchExpiryDate",
            "StoredBatchId",
            "StoredNHRN",
            "TargetState",
            "User",
            "UserAgent",
        ]

        for k in detail_keys:
            df[k] = parsed.apply(lambda d, kk=k: d.get(kk, ""))

    # Build stable dedupe key
    def build_md5(row):
        dt = row.get("Date_and_Time_UTC")
        dt_str = (
            dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            if isinstance(dt, pd.Timestamp)
            else ""
        )
        payload = f"{row.get('Transaction_ID','')}|{row.get('Event_Code','')}|{dt_str}"
        return hashlib.md5(payload.encode("utf-8")).hexdigest()

    df["_dedupe_key"] = df.apply(build_md5, axis=1)

    # Deduplicate within this file
    df = df.drop_duplicates(subset=["_dedupe_key"], keep="first")

    return df

# ----- Target table DDL (normalized column names) -----
EXC_TABLE = "NMVS_ExceptionsAuditTrailReport"

EXC_TARGET_COLUMNS = [
    
"Date_and_Time_UTC",
    "Process",
    "Event_Name",
    "Event_Description",
    "Transaction_ID",
    "Event_Code",
    "Event_Message",
    "Event_Details",
    "Category",
    "Severity",
    "ActualState",
    "APIVersion",
    "AttemptedOperation",
    "BatchExpiryDate",
    "BatchId",
    "ClientEquipmentId",
    "ClientId",
    "ClientLocation",
    "ClientOrganisationId",
    "DataEntryMode",
    "EmvsErrorCode",
    "EUPublicPackState",
    "InitialState",
    "InitiatingMessageType",
    "IpAddress",
    "IsBadData",
    "IsBulk",
    "IsIntermarketResponse",
    "Location",
    "Market",
    "NumberOfDispenseAttempts",
    "PackLastUpdateLocation",
    "PackLastUpdateMarket",
    "PackLastUpdateTimestamp",
    "ProductCode",
    "ProductCodeScheme",
    "ProductName",
    "RequestedAPIVersion",
    "RequestedState",
    "SerialNumber",
    "StoredBatchExpiryDate",
    "StoredBatchId",
    "StoredNHRN",
    "TargetState",
    "User",
    "UserAgent",
    "_dedupe_key",
    "_load_date_utc", # MySQL default, not provided in DF
]

# ============================================================================
# Create/ensure the NMVS_ExceptionsAuditTrailReport table with UNIQUE key
# ============================================================================
def ensure_exceptions_table(engine, table: str = EXC_TABLE):
    """
    Create Exceptions table with normalized column names.
    Ensures:
      - UNIQUE key on _dedupe_key
      - Index on Date_and_Time_UTC
      - Prefix index on Transaction_ID(191)
      - MySQL-side default on _load_date_utc
    """
    ddl = f"""
    CREATE TABLE IF NOT EXISTS `{table}` (
        `Date_and_Time_UTC`         DATETIME(3) NULL,
        `Process`                   VARCHAR(100),
        `Event_Name`                VARCHAR(150),
        `Event_Description`         VARCHAR(255),
        `Transaction_ID`            VARCHAR(255),
        `Event_Code`                VARCHAR(50),
        `Event_Message`             TEXT,
        `Event_Details`             TEXT,
        `Category`                  VARCHAR(50),
        `Severity`                  VARCHAR(50),
        `ActualState`               VARCHAR(20),
        `APIVersion`                VARCHAR(20),
        `AttemptedOperation`        VARCHAR(100),
        `BatchExpiryDate`           VARCHAR(20),
        `BatchId`                   VARCHAR(50),
        `ClientEquipmentId`         VARCHAR(255),
        `ClientId`                  VARCHAR(100),
        `ClientLocation`            VARCHAR(100),
        `ClientOrganisationId`      VARCHAR(50),
        `ConnectorLocationId`       VARCHAR(100),
        `DataEntryMode`             VARCHAR(50),
        `EmvsErrorCode`             VARCHAR(10),
        `EUPublicPackState`         VARCHAR(20),
        `InitialState`              VARCHAR(20),
        `InitiatingMessageType`     VARCHAR(255),
        `IpAddress`                 VARCHAR(50),
        `IsBadData`                 VARCHAR(10),
        `IsBulk`                    VARCHAR(10),
        `IsIntermarketResponse`     VARCHAR(10),
        `Location`                  VARCHAR(100),
        `Market`                    VARCHAR(20),
        `NumberOfDispenseAttempts`  VARCHAR(10),
        `PackLastUpdateLocation`    VARCHAR(50),
        `PackLastUpdateMarket`      VARCHAR(20),
        `PackLastUpdateTimestamp`   DATETIME(3) NULL,
        `ProductCode`               VARCHAR(100),
        `ProductCodeScheme`         VARCHAR(50),
        `ProductName`               VARCHAR(255),
        `RequestedAPIVersion`       VARCHAR(20),
        `RequestedState`            VARCHAR(20),
        `SerialNumber`              VARCHAR(100),
        `StoredBatchExpiryDate`     VARCHAR(20),
        `StoredBatchId`             VARCHAR(50),
        `StoredNHRN`                VARCHAR(50),
        `TargetState`               VARCHAR(20),
        `User`                      VARCHAR(255),
        `UserAgent`                 VARCHAR(255),
        `_dedupe_key`       CHAR(32) NOT NULL,
        `_load_date_utc`    DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
        UNIQUE KEY `ux_exceptions_dedupe` (`_dedupe_key`),
        KEY `idx_exceptions_event_time` (`Date_and_Time_UTC`),
        KEY `idx_exceptions_txid` (`Transaction_ID`(191))
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))

# ===========================================================================
# 1) Write df to staging (replace).
# 2) Insert new rows into target via INSERT IGNORE on UNIQUE(_dedupe_key).
# 3) Drop staging.
# Returns number of attempted inserted rows (0 if all dupes).
# ============================================================================
def merge_exceptions(engine,
                     df: pd.DataFrame,
                     target_table: str = EXC_TABLE,
                     staging_table: str = "stg_Exceptions") -> int:
    """
    Idempotent merge via staging + INSERT IGNORE.
    Only new rows (based on _dedupe_key) are inserted.
    """
    
    ensure_exceptions_table(engine, target_table)

    with engine.begin() as conn:

        # Write to staging
        rows_written = df.to_sql(staging_table, con=conn, if_exists="replace", index=False, method="multi")
        logging.info(
            "Staging table '%s' written to MySQL: %s records.",
            staging_table,
            rows_written,
        )

        df_cols = set(df.columns)
        insert_cols = [
            c for c in EXC_TARGET_COLUMNS
            if c in df_cols and c != "_load_date_utc"
        ]
        col_sql = ", ".join(f"`{c}`" for c in insert_cols)

        sql = f"""
        INSERT IGNORE INTO `{target_table}` ({col_sql})
        SELECT {col_sql}
        FROM `{staging_table}`;
        """

        result = conn.execute(text(sql))

        # Drop staging
        conn.execute(text(f"DROP TABLE IF EXISTS `{staging_table}`"))

        return result.rowcount or 0

# ======================================================================
# Checkpoint Table for Exceptions Audit Trail
# ======================================================================
def ensure_checkpoints_table(engine):
    sql = """
    CREATE TABLE IF NOT EXISTS `ETL_Checkpoints` (
        `pipeline`         VARCHAR(100) NOT NULL,
        `day_utc`          DATE NOT NULL,
        `days_in_past`     INT NOT NULL,
        `status`           ENUM('success','failed') NOT NULL,
        `rows_inserted`    INT NOT NULL DEFAULT 0,
        `last_attempt_utc` DATETIME(3) NOT NULL,
        PRIMARY KEY (`pipeline`, `day_utc`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """
    with engine.begin() as conn:
        conn.execute(text(sql))

# ===========================================
# Checkpoint table to catch up missed days
# ===========================================
def record_checkpoint(status: str, days_in_past: int, rows: int):
    """
    Record pipeline run status for ExceptionsAuditTrail, keyed by day_utc.
    """
    engine = _get_engine()
    ensure_checkpoints_table(engine)

    day_utc = (datetime.now(timezone.utc) - timedelta(days=days_in_past)).date()
    payload = {
        "pipeline": "ExceptionsAuditTrail",
        "day_utc": str(day_utc),
        "days_in_past": int(days_in_past),
        "status": status,
        "rows_inserted": int(rows),
    }

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO `ETL_Checkpoints`
                (`pipeline`, `day_utc`, `days_in_past`, `status`, `rows_inserted`, `last_attempt_utc`)
            VALUES
                (:pipeline, :day_utc, :days_in_past, :status, :rows_inserted, NOW(3))
            ON DUPLICATE KEY UPDATE
                `status` = VALUES(`status`),
                `rows_inserted` = VALUES(`rows_inserted`),
                `last_attempt_utc` = NOW(3)
        """), payload)

# ==================================================================================
# NMVS Exceptions Audit Trail Report (single CSV):
# - Fetch report, read bytes as CSV
# - Normalize types
# - Write to DB with millisecond-capable DATETIME columns
# ==================================================================================
def import_exceptions_audit_trail_report(days: int = 1):
    """
    Full ETL for NMVS Exceptions Audit Trail:
      - Fetch report for X days in past
      - Robust CSV parse (engine=python)
      - Normalize NMVS columns
      - Compute dedupe key
      - Idempotent merge via staging
      - Record checkpoint
    """
    engine = _get_engine()

    try:
        resp = Reports().get_exceptions_audit_trail_report(days)
    except Exception as e:
        logging.error("Failed to request ExceptionsAuditTrail report: %s", e)
        record_checkpoint("failed", days, 0)
        return

    if resp is None or not getattr(resp, "ok", False):
        logging.error("ExceptionsAuditTrail HTTP error or empty response.")
        record_checkpoint("failed", days, 0)
        return

    # --- Robust CSV parse ---
    try:
        df = read_exceptions_csv(resp.content, skiprows=3)
        # Fallback if nmvs has no banner rows
        if df.empty or df.shape[1] == 1:
            df = read_exceptions_csv(resp.content, skiprows=0)
    except Exception as e:
        logging.error("Failed to parse ExceptionsAuditTrail CSV: %s", e)
        record_checkpoint("failed", days, 0)
        return

    if df is None or df.empty:
        logging.info("ExceptionsAuditTrail CSV empty; nothing to insert.")
        record_checkpoint("success", days, 0)
        return

    # Normalize NMVS column names first
    df = normalize_nmvs_columns(df)

    # Drop rows where *all* values are empty/whitespace/NaN/"nan"/"None".
    # This prevents a bogus _dedupe_key from ever being computed.
    df = df[
        df.apply(
            lambda row: any(str(v).strip() not in ("", "nan", "None") for v in row),
            axis=1
        )
    ]

    # If nothing meaningful left, stop here (no staging, no merge, no dedupe)
    if df.empty:
        logging.info("ExceptionsAuditTrail: no meaningful rows returned by API; nothing to insert.")
        record_checkpoint("success", days, 0)
        return

    # --- normalize & compute dedupe key ---
    df = normalize_exceptions_df(df)

    # --- merge ---
    try:
        inserted = merge_exceptions(engine, df)
        logging.info("Exceptions Audit Trail: days=%s, inserted=%s", days, inserted)
        record_checkpoint("success", days, inserted)
    except Exception as e:
        logging.error("Merge into Exceptions table failed: %s", e)
        record_checkpoint("failed", days, 0)

# ============================================================================
# Index helper: creates missing single-column indexes using INFORMATION_SCHEMA
# Note:
# - Uses UPPER() for case-insensitive checks
# - Creates non-unique indexes named idx_<table>_<col>
# - Assumes column is indexable (VARCHAR/INT). TEXT/BLOB need prefix length.
# ============================================================================
def ensure_indexes(engine, database_name: str, table: str, columns: list[str], prefix_len: int = 64) -> None:
    """
    Create simple single-column indexes if missing.
    - Name: idx_<table_lower>_<col_lower_underscored>
    - If column is TEXT/BLOB, create a prefix index with (prefix_len) to avoid MySQL 1170.
    - Resolves original column case via INFORMATION_SCHEMA to quote correctly.
    """
    q_stats = text("""
        SELECT INDEX_NAME, COLUMN_NAME
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table
    """)
    q_cols = text("""
        SELECT COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table
    """)

    with engine.begin() as conn:
        # Existing indexes → { idx_name: {COL1, COL2, ...} }
        rows = conn.execute(q_stats, {"schema": database_name, "table": table}).fetchall()
        existing: dict[str, set[str]] = {}
        for idx_name, col_name in rows:
            existing.setdefault(idx_name, set()).add((col_name or "").upper())

        # Columns metadata → { UPPER(col): (orig_name, data_type) }
        col_rows = conn.execute(q_cols, {"schema": database_name, "table": table}).fetchall()
        cols = {r[0].upper(): (r[0], (r[1] or "").lower()) for r in col_rows}

        for col in columns:
            lookup = (col or "").upper()
            if lookup not in cols:
                logging.info(f"Warning: Column '{col}' in {table} not found – index skipped.")
                continue

            orig_name, data_type = cols[lookup]
            # Build clean index name (avoid spaces)
            idx_name = f"idx_{table.lower()}_{orig_name.lower().replace(' ', '_')}"

            # Already present?
            if idx_name in existing and orig_name.upper() in existing[idx_name]:
                continue

            # TEXT/BLOB need a prefix length
            needs_prefix = data_type in {
                "text", "tinytext", "mediumtext", "longtext",
                "blob", "tinyblob", "mediumblob", "longblob"
            }
            col_sql = f"`{orig_name}`" + (f"({prefix_len})" if needs_prefix else "")

            logging.info(f"CREATE INDEX {idx_name} ON {table}({col_sql}) …")
            conn.execute(text(f"CREATE INDEX `{idx_name}` ON `{table}` ({col_sql})"))


# =====================================================================================
# NMVS Snapshot (multi-table):
# - Call NMVS APIs to enumerate types and fetch the daily snapshot
# - Decode bytes safely
# - Split into logical tables and persist each
# - Create indexes to accelerate lookups
# =====================================================================================
def import_snapshot():
    engine = _get_engine()

    try:
        reports = Reports()
        raw = reports.get_daily_snapshot_report(0).content
    except Exception as e:
        logging.error("Failed to download NMVS snapshot: %s", e)
        return

    # Decode & parse the multi-table CSV
    csv_text = decode_text_robust(raw)
    tables = parse_csv_string(csv_text, prefix="NMVS")

    # Persist all tables
    save_dict_to_mysql(tables, engine)

    # Apply indexes to key NMVS tables
    database_name = MyConfiguration.get_value("database_url").rsplit("/", 1)[-1]

    ensure_indexes(engine, database_name, "NMVS_Products", ["Product_Code"])
    ensure_indexes(engine, database_name, "NMVS_Batches", ["Product_Code"])
    ensure_indexes(engine, database_name, "NMVS_Batches", ["Batch_Id"])
    ensure_indexes(engine, database_name, "NMVS_Organisations", ["Organisation_Name"])
    ensure_indexes(engine, database_name, "NMVS_Locations", ["Organisation_Name"])

# ====================================================================================
# CLI entry point: parse flags, bootstrap logging, and delegate to requested importers
# 
# Run it with flags like:
# -r → import Refdata
# -r2 → import new Refdata
# !! -s → import Swissmedic
# -n Snapshot → import NMVS daily snapshot (multi-table CSV)
# -n OrganisationsSummaryReport → import NMVS org summary report (single CSV)
# -n ExceptionsAuditTrailReport -d 1 → import NMVS exceptions report for yesterday (single CSV)
# Example:
# python client.py -r2 -s -n Snapshot
# ====================================================================================
def main():
    parser = argparse.ArgumentParser(description="NMVS Business Intelligence Data Extractor")

    # parser.add_argument("-r", action="store_true", help="Import Refdata")
    # parser.add_argument("-r2", action="store_true", help="Import new Refdata2")
    # Country specific stuff.
    # parser.add_argument("-s", action="store_true", help="Import Swissmedic")
    parser.add_argument("-t", "--test", action="store_true", help="Run software and environment checks only")
    parser.add_argument("-n", type=str, help="Import NMVS report (Snapshot, OrganisationsSummaryReport, ExceptionsAuditTrailReport)")
    parser.add_argument("-d", "--days", type=int, default=1, help="Days in past for ExceptionsAuditTrailReport (0=today, 1=yesterday, etc.)")

    args = parser.parse_args()

    if args.test:
        return 0 if run_environment_checks() else 1

    init_logging()
    
    if args.n:
        match args.n:
            case "Snapshot":
                logging.info("Importing NMVS Snapshot…")
                import_snapshot()

            case "OrganisationsSummaryReport":
                logging.info("Importing OrganisationsSummaryReport…")
                import_organisations_summary_report()

            case "ExceptionsAuditTrailReport":
                logging.info("Importing ExceptionsAuditTrailReport…")
                import_exceptions_audit_trail_report(days=args.days)

            case _:
                logging.error(f"Unknown NMVS report '{args.n}'")

if __name__ == '__main__':
    raise SystemExit(main())