#!/usr/bin/env python3
"""
Import NMVO Exceptions into MySQL using SQLAlchemy (Core).

This refactors the previous PyMySQL/cursor-based version to SQLAlchemy while
keeping CLI, API flow, and field mapping as intact as possible.

Flow:
1) Obtain OAuth token (client_credentials) from https://{auth_base}/identity/connect/token
2) POST https://{alerts_host}/alerts with start/end -> returns requestID
3) GET  https://{alerts_host}/alerts/data/{requestID}?page=1&pagesize=...
4) INSERT records into MySQL with SQLAlchemy Core (executemany)

Usage examples:
  python nmvs_exceptions_sqlalchemy.py \
    --env IQE \
    --client-id YOUR_CLIENT_ID \
    --client-secret YOUR_CLIENT_SECRET \
    --start 2025-04-23T00:00:00Z \
    --end   2025-04-26T00:00:00Z \
    --mysql-url "mysql+pymysql://root:secret@127.0.0.1:3306/nmvo" \
    --table exceptions

  python nmvs_exceptions_sqlalchemy.py --env PROD ...

Notes:
- Default pagesize is 6000.
- Table is created if missing (SQLAlchemy DDL).
"""

import argparse
import datetime as dt
import json
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple
import logging
import requests
from sqlalchemy import (
    create_engine, MetaData, Table, Column, Boolean, BigInteger, Integer, String, DateTime, JSON,
    Index, insert, text
)
from sqlalchemy.engine import Engine
from nmvs.conf.myconfigparser import MyConfiguration

# !!! USer-Agend & emvs-api-version ??? correct?
def make_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token.strip()}",
        "User-Agent": "python-import/1.0",   # exakt so benennen
        "emvs-api-version": "1.0",
        "Accept": "application/json",
    }



def iso_to_datetime(iso_str: Optional[str]) -> Optional[dt.datetime]:
    if not iso_str:
        return None
    try:
        s = iso_str.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def get_token(auth_base: str, client_id: str, client_secret: str, verify_tls: bool) -> str:
    url = f"https://{auth_base}/identity/connect/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded", "user-agent": "python-import/1.0"}
    resp = requests.post(url, data=data, headers=headers, timeout=30, verify=verify_tls)
    resp.raise_for_status()
    payload = resp.json()
    t = payload.get("access_token")
    if not t:
        raise RuntimeError(f"No access_token in response: {payload}")
    return t


def request_alerts(alerts_host: str, token: str, start_iso: str, end_iso: str, verify_tls: bool) -> Tuple[str, Optional[str]]:
    url = f"https://{alerts_host}/alerts"
   
    headers = {**make_headers(token), "Content-Type": "application/json"}  

    body = {"startTimestamp": start_iso, "endTimestamp": end_iso}
    resp = requests.post(url, headers=headers, json=body, timeout=60, verify=verify_tls)
    resp.raise_for_status()
    j = resp.json()
    request_id = j.get("requestID") or j.get("requestId") or j.get("id")
    if not request_id:
        raise RuntimeError(f"Could not find requestID in response: {j}")
    

    logging.debug("=== ALERTS RESPONSE ===")
    logging.debug(f"Status: {resp.status_code}")
    logging.debug(f"Headers: {dict(resp.headers)}")
    try:
        logging.debug(f"JSON body: {resp.json()}")
    except Exception:
        logging.debug(f"Text body: {resp.text}")
    logging.debug("=======================")

    return request_id, resp.headers.get("Location")

def fetch_page_by_location(
    base_location_url: str,
    token: str,
    page: int,
    pagesize: int,
    verify_tls: bool = True,
    max_attempts: int = 200,   # ~200 * 20s = ~4000s max Wartezeit
):
    """
    Query the result URL (from the Location header) with pagination.
    If 4xx is returned (result still being processed), the status is logged,
    the system waits 20 seconds, and then tries again. The same applies to 5xx (defensive).
    If successful, returns the JSON (dict or list, depending on the API).
    """
    session = requests.Session()
    headers = {
        "Authorization": f"Bearer {token}",
        "emvs-api-version": "1.0",
        "user-agent": "python-import/1.0",
        "Accept": "application/json",
    }

    url = f"{base_location_url}?page={page}&pageSize={pagesize}"

    attempt = 0
    while True:
        attempt += 1
        try:
            resp = session.get(url, headers=headers, timeout=60, verify=verify_tls)
        except requests.RequestException as e:
            # Netzwerkfehler → defensiv wie 5xx behandeln
            logging.debug(f"[Attempt {attempt}] Netzwerkfehler: {e}. Warte 20s und versuche erneut...")
            if attempt >= max_attempts:
                raise
            time.sleep(20)
            continue

        # Ergebnis interpretieren
        sc = resp.status_code

        # 200/206: Daten da
        if sc in (200, 206):
            # Falls die API einen leeren Body liefert, vorsichtig behandeln
            text = (resp.text or "").strip()
            if not text:
                return []  # kein Inhalt
            try:
                return resp.json()
            except ValueError:
                # Kein JSON → leer annehmen
                logging.error(f"[Attempt {attempt}] Hinweis: Antwort ohne JSON-Inhalt (Status {sc}).")
                return []

        # 202: theoretisch "accepted, still processing" (falls so implementiert)
        if sc == 202:
            logging.debug(f"[Attempt {attempt}] Status 202 (in Bearbeitung). Warte 20s...")
            if attempt >= max_attempts:
                raise RuntimeError("Max. Wartezeit erreicht (202).")
            time.sleep(20)
            continue

        # 4xx: laut Vorgabe warten und erneut probieren
        if 400 <= sc < 500:
            logging.debug(f"[Attempt {attempt}] HTTP {sc} {resp.reason}. Body: {resp.text[:300]} ... Warte 20s und versuche erneut.")
            if attempt >= max_attempts:
                raise RuntimeError(f"Max. Versuche erreicht bei 4xx ({sc}).")
            time.sleep(20)
            continue

        # 5xx: ebenfalls warten und erneut probieren (defensiv)
        if 500 <= sc < 600:
            logging.error(f"[Attempt {attempt}] Serverfehler {sc}. Body: {resp.text[:300]} ... Warte 20s und versuche erneut.")
            if attempt >= max_attempts:
                raise RuntimeError(f"Max. Versuche erreicht bei 5xx ({sc}).")
            time.sleep(20)
            continue

        # Unerwartete Statuscodes
        logging:error(f"[Attempt {attempt}] Unerwarteter Status {sc}. Body: {resp.text[:300]}")
        if attempt >= max_attempts:
            raise RuntimeError(f"Max. Versuche erreicht (Status {sc}).")
        time.sleep(20)

def fetch_page(location_url: str,
               token: str,
               page: int,
               page_size: int,
               verify_tls: bool = True,
               max_attempts: int = 200,
               refresh_token_cb=None  # function() -> new_token
               ) -> Tuple[Dict[str, Any], str]:
    """
    Holt eine Seite über die Location-URL. Bei 401 wird 1x das Token via refresh_token_cb() erneuert.
    Gibt (response_json, possibly_new_token) zurück. response_json kann {} sein.
    """
    url = f"{location_url}?page={int(page)}&pageSize={int(page_size)}"
    attempt = 0
    refreshed = False
    cur_token = token

    while True:
        attempt += 1
        try:
            r = requests.get(url, headers=make_headers(cur_token), timeout=60, verify=verify_tls)
        except requests.RequestException as e:
            logging.error(f"[Attempt {attempt}] Netzwerkfehler: {e}. Warte 20s…")
            if attempt >= max_attempts:
                raise
            time.sleep(20)
            continue

        sc = r.status_code
        if sc in (200, 206):
            try:
                return r.json(), cur_token
            except ValueError:
                logging.error(f"[Attempt {attempt}] 200 ohne JSON. Body(300): {(r.text or '')[:300]!r}")
                return {}, cur_token

        if sc == 401:
            logging.error(f"[Attempt {attempt}] 401 Unauthorized. Body(300): {(r.text or '')[:300]}")
            if not refreshed and callable(refresh_token_cb):
                try:
                    cur_token = refresh_token_cb().strip()
                    refreshed = True
                    logging.info("Token refreshed. Retry now…")
                    continue
                except Exception as e:
                    raise RuntimeError(f"Token refresh failed: {e}") from e
            raise RuntimeError("401 trotz Token-Refresh.")

        if sc in (404, 409, 422):  # „not ready“ / conflict / unprocessable
            logging.debug(f"[Attempt {attempt}] {sc} {r.reason}. Body(300): {(r.text or '')[:300]} … Warte 20s…")
            if attempt >= max_attempts:
                raise RuntimeError(f"Max retries for {sc}")
            time.sleep(20)
            continue

        if 500 <= sc < 600:
            logging.error(f"[Attempt {attempt}] Serverfehler {sc}. Body(300): {(r.text or '')[:300]} … Warte 20s…")
            if attempt >= max_attempts:
                raise RuntimeError(f"Max retries for {sc}")
            time.sleep(20)
            continue

        raise RuntimeError(f"Unexpected status {sc}: {(r.text or '')[:300]}")

def escalate_full_dataset(request_id: str, base_host: str, verify_tls=True):
    url = f"https://{base_host}/alerts/fulldataset/{request_id}"
    r = requests.post(url, headers={**REQ_HEADERS, "Content-Type": "application/json"}, timeout=60, verify=verify_tls)
    if r.status_code != 202:
        raise RuntimeError(f"Escalation failed: {r.status_code} {r.text[:300]}")
    logging.info("Escalation accepted (202).")


def ensure_table(engine: Engine, table_name: str) -> Table:
    """
    Create table if it doesn't exist. Für bestehende Tabellen bitte die ALTERs verwenden.
    """
    meta = MetaData()
    tbl = Table(
        table_name, meta,
        Column("id", BigInteger, primary_key=True, autoincrement=True),

        # Ergebnisfelder (Swagger AlertDetails)
        Column("alertDateTime", String(64)),           # optional später auf DATETIME(3) umstellen
        Column("uniqueAlertID", String(128)),
        Column("errorCode", String(32)),
        Column("transactionID", String(128)),
        Column("errorMessage", String(512)),
        Column("attemptedOperation", String(64)),
        Column("organisationID", Integer),
        Column("clientID", String(128)),
        Column("userAgent", String(256)),
        Column("apiVersion", String(32)),
        Column("manualEntry", Boolean),
        Column("operationCode", String(32)),
        Column("eventMessage", String(512)),
        Column("isIntermarket", Boolean),
        Column("numberOfDispenseAttempts", Integer),
        Column("numberOfDecommissionAttempts", Integer),
        Column("productCodeScheme", String(32)),
        Column("productCode", String(64)),
        Column("productName", String(255)),
        Column("serialNumber", String(128)),
        Column("providedBatchNumber", String(64)),
        Column("providedExpiryDate", String(16)),
        Column("storedBatchNumber", String(64)),
        Column("storedExpiryDate", String(16)),
        Column("sourceMarket", String(8)),
        Column("sourceLocationID", String(128)),
        Column("requestedPackTargetState", String(32)),
        Column("currentPackState", String(32)),
        Column("packLastUpdateLocationID", String(64)),
        Column("packLastUpdateTimestamp", DateTime(timezone=False)),
        Column("packLastUpdateMarket", String(4)),
        Column("storedNHRN", String(64)),
        Column("sourceBusinessProcess", String(128)),
        Column("alertRecencyValue", BigInteger),

        # Meta je Abruf
        Column("request_id", String(64)),
        Column("page", Integer),
        Column("record_index", Integer),

        # Rohpayload
        Column("payload", JSON),
    )

    # Indizes
    Index("idx_uniqueAlertID", tbl.c.uniqueAlertID, unique=True)
    Index("idx_transactionID", tbl.c.transactionID)
    Index("idx_productCode", tbl.c.productCode)
    Index("idx_serialNumber", tbl.c.serialNumber)
    Index("idx_alertDateTime", tbl.c.alertDateTime)
    Index("ix_err", tbl.c.errorCode)
    Index("ix_op", tbl.c.operationCode)
    Index("ix_src", tbl.c.sourceMarket, tbl.c.alertDateTime)
    Index("ix_loc", tbl.c.sourceLocationID)
    Index("ix_recency", tbl.c.alertRecencyValue)
    Index("uk_req_page_idx", tbl.c.request_id, tbl.c.page, tbl.c.record_index, unique=True)

    meta.create_all(engine, checkfirst=True)
    return tbl


def extract_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    KEYS = [
        "alertDateTime",
        "uniqueAlertID",
        "errorCode",
        "transactionID",
        "errorMessage",
        "attemptedOperation",
        "organisationID",
        "clientID",
        "userAgent",
        "apiVersion",
        "manualEntry",
        "operationCode",
        "eventMessage",
        "isIntermarket",
        "numberOfDispenseAttempts",
        "numberOfDecommissionAttempts",
        "productCodeScheme",
        "productCode",
        "productName",
        "serialNumber",
        "providedBatchNumber",
        "providedExpiryDate",
        "storedBatchNumber",
        "storedExpiryDate",
        "sourceMarket",
        "sourceLocationID",
        "requestedPackTargetState",
        "currentPackState",
        "packLastUpdateLocationID",
        "packLastUpdateTimestamp",
        "packLastUpdateMarket",
        "storedNHRN",
        "sourceBusinessProcess",
        "alertRecencyValue",
    ]
    out = {k: item.get(k) for k in KEYS}

    # Optional: ISO-String -> datetime (falls Spalte DATETIME(3) ist)
    try:
        if out.get("alertDateTime"):
            out["alertDateTime"] = iso_to_datetime(out["alertDateTime"])
        if out.get("packLastUpdateTimestamp"):
            out["packLastUpdateTimestamp"] = iso_to_datetime(out["packLastUpdateTimestamp"])
    except Exception:
        pass

    return out

def build_params(item: Dict[str, Any], *, request_id: str, page: int, idx: int) -> Dict[str, Any]:
    fields = extract_fields(item)
    return {
        "request_id": request_id,
        "page": page,
        "record_index": idx,
        **fields,
        "payload": item,
    }


def iso_z(dtobj: dt.datetime) -> str:
    """ISO-String mit 'Z' statt '+00:00' für UTC."""
    return dtobj.astimezone(dt.timezone.utc).replace(tzinfo=dt.timezone.utc).isoformat().replace("+00:00", "Z")

def last_two_days_utc():
    """Von vorgestern 00:00:00 UTC bis jetzt (UTC)."""
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    start = dt.datetime.combine((now - dt.timedelta(days=2)).date(), dt.time.min, tzinfo=dt.timezone.utc)
    return iso_z(start), iso_z(now)

def full_yesterday_utc():
    """Kompletter gestriger Tag: 00:00:00–23:59:59 UTC."""
    today = dt.datetime.now(dt.timezone.utc).date()
    start = dt.datetime.combine(today - dt.timedelta(days=1), dt.time.min, tzinfo=dt.timezone.utc)
    end   = dt.datetime.combine(today, dt.time.min, tzinfo=dt.timezone.utc) - dt.timedelta(seconds=1)
    return iso_z(start), iso_z(end)



def main():

    
    try:
        MyConfiguration.initialize_logging()
    except Exception:
        logging.basicConfig(level=logging.INFO)

    # 1) Auth
    client_id = MyConfiguration.get_value("nmvs_client_id")
    client_secret = MyConfiguration.get_value("nmvs_client_secret")

    alerts_host = MyConfiguration.get_value("nmvs_exc_host")
    auth_base = MyConfiguration.get_value("nmvs_exc_auth_base")

    token = get_token(auth_base, client_id, client_secret, verify_tls=True)

    def refresh_token():
        return get_token(auth_base, client_id, client_secret, verify_tls=True)

    # 2) Request starten 

    # Datum bis Vortag (UTC)
    start, end = last_two_days_utc()
    # start = "2025-11-01T00:00:00Z"
    # end   = "2025-11-11T23:00:00Z"

    request_id, location = request_alerts(alerts_host, token, start, end, verify_tls=True)
    logging.info(f"Created alerts request_id={request_id} (Location={location})")

    # 2) DB Engine
    mysql_url = MyConfiguration.get_value("database_url") + "?charset=utf8mb4"
    engine = create_engine(mysql_url, pool_pre_ping=True, future=True)

    # 3) Tabelle sicherstellen
    tbl = ensure_table(engine, "NMVS_Exceptions")

    # 4) Insert-Loop (Paging über Location-URL)
    pagesize = 1000
    total = 0
    page = 1
    stmt = insert(tbl).prefix_with("IGNORE")  # MySQL: INSERT IGNORE für Idempotenz


    while True:

        res, token = fetch_page(
            location_url=location,
            token=token,
            page=page,
            page_size=pagesize,
            verify_tls=True,
            refresh_token_cb=refresh_token
        )

        if not res:
            if page == 1:
                logging.info("No data returned (JSON leer).")
            break

        # Struktur gemäss Swagger:
        data = res.get("data") or []
        pages = res.get("pages") or 1
        is_truncated = bool(res.get("isTruncated"))
        is_over_limit = bool(res.get("isOverLimit"))

        if not data and page == 1:
            logging.info("No data returned for this request window.")
            break

        params = [build_params(item, request_id=request_id, page=page, idx=i) for i, item in enumerate(data)]
        with engine.begin() as conn:
            conn.execute(stmt, params)

        total += len(data)
        logging.info(f"Page {page}/{pages}: inserted {len(data)} (total {total})")

        if page >= pages:
            # Falls gekürzt, optional Escalation anstossen und weiterpollen
            if is_truncated and not is_over_limit:
                logging.info("Results truncated. Attempting escalation to full dataset…")
                escalate_full_dataset(request_id, alerts_host, verify_tls=True)
                # Nach Escalation erneut von Seite 1 laden
                page = 1
                total_page_loop = 0
                continue
            break

        page += 1
        time.sleep(0.3)

    logging.info(f"Done. Total inserted: {total}")


if __name__ == "__main__":
    main()

