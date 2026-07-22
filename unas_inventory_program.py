from __future__ import annotations

import logging
import os
import socket
import sys
import time as time_module
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time
from io import BytesIO
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_URL: Final[str] = "https://api.unas.eu/shop"
LOGIN_URL: Final[str] = f"{BASE_URL}/login"
PRODUCTDB_URL: Final[str] = f"{BASE_URL}/getProductDB"
BUDAPEST_TZ: Final[ZoneInfo] = ZoneInfo("Europe/Budapest")

DEFAULT_STORE_CODE: Final[str] = "03343192712828716513"
DEFAULT_OUTPUT_DIR: Final[str] = "public"
DEFAULT_TXT_FILENAME: Final[str] = "product_database_raw.txt"
DEFAULT_XLSX_FILENAME: Final[str] = "product_database_raw.xlsx"

# A blokkolt GitHub runner IP-ket gyorsan fel kell ismerni. Az új kimenő IP-t
# a workflow külön jobban, új runneren próbálja meg, ezért itt nem érdemes egy
# órán át ugyanarról az IP-ről újrakapcsolódni.
CONNECT_TIMEOUT: Final[int] = 15
READ_TIMEOUT: Final[int] = 120
TOKEN_ATTEMPTS: Final[int] = 1
PRODUCTDB_ATTEMPTS: Final[int] = 2
DOWNLOAD_ATTEMPTS: Final[int] = 2

REQUIRED_COLUMNS: Final[set[str]] = {
    "Cikkszám",
    "Státusz",
    "Raktárkészlet",
    "Min. Menny.",
    "Bruttó Ár",
    "Akciós Bruttó Ár",
    "Akció Kezdet",
    "Akció Lejárat",
}

OUTPUT_COLUMNS: Final[list[str]] = [
    "id",
    "price",
    "sale_price",
    "quantity",
    "store_code",
    "availability",
    "pickup_method",
    "pickup_sla",
    "sale_price_effective_date",
]


@dataclass(frozen=True)
class Config:
    unas_api_key: str
    output_dir: Path
    store_code: str
    multiply_by_min_qty: bool
    write_debug_xlsx: bool
    txt_filename: str = DEFAULT_TXT_FILENAME
    xlsx_filename: str = DEFAULT_XLSX_FILENAME


def env_bool(name: str, default: bool = False) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "y", "igen", "i"}


def load_config() -> Config:
    unas_api_key = os.environ.get("UNAS_API_KEY", "").strip()

    if not unas_api_key:
        raise RuntimeError("Hiányzik az UNAS_API_KEY környezeti változó.")

    output_dir = Path(os.environ.get("OUTPUT_DIR", DEFAULT_OUTPUT_DIR)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    return Config(
        unas_api_key=unas_api_key,
        output_dir=output_dir,
        store_code=os.environ.get("GOOGLE_STORE_CODE", DEFAULT_STORE_CODE).strip() or DEFAULT_STORE_CODE,
        multiply_by_min_qty=env_bool("MULTIPLY_BY_MIN_QTY", default=False),
        write_debug_xlsx=env_bool("WRITE_DEBUG_XLSX", default=False),
    )


def log_network_diagnostics() -> None:
    logging.info("UNAS API diagnosztika indul...")

    try:
        ip = socket.gethostbyname("api.unas.eu")
        logging.info("api.unas.eu DNS IP: %s", ip)
    except Exception as exc:
        logging.warning("DNS feloldás sikertelen api.unas.eu esetén: %s", exc)

    try:
        response = requests.get(
            "https://api.ipify.org",
            timeout=(10, 20),
        )
        logging.info("GitHub runner publikus IP: %s", response.text.strip())
    except Exception as exc:
        logging.warning("Runner publikus IP lekérése sikertelen: %s", exc)


def build_http_session() -> requests.Session:
    retry = Retry(
        total=2,
        # A connect timeout jellemzően az adott runner IP-jének blokkolását
        # jelenti. Ugyanarról az IP-ről ne ismételjük automatikusan.
        connect=0,
        read=2,
        status=2,
        backoff_factor=2,
        status_forcelist=(408, 425, 429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
        respect_retry_after_header=True,
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=10,
        pool_maxsize=10,
    )

    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": "Buildox-UNAS-Merchant-Feed/1.0",
        }
    )
    return session


def parse_xml_field(xml_content: bytes, field_name: str, context: str) -> str:
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        body_preview = xml_content[:800].decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{context}: az UNAS válasza nem érvényes XML. response={body_preview}"
        ) from exc

    value = root.findtext(field_name)

    if not value:
        body_preview = xml_content[:800].decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{context}: hiányzik a <{field_name}> mező az UNAS válaszból. response={body_preview}"
        )

    return value.strip()


def raise_for_status_with_body(response: requests.Response, context: str) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body_preview = response.text[:800].replace("\n", " ")
        raise RuntimeError(
            f"{context}: HTTP hiba. status={response.status_code}, response={body_preview}"
        ) from exc


def request_with_manual_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    context: str,
    attempts: int,
    **kwargs,
) -> requests.Response:
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            logging.info("%s: próbálkozás %s/%s", context, attempt, attempts)

            response = session.request(
                method=method,
                url=url,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                **kwargs,
            )

            logging.info(
                "%s: válasz érkezett. status=%s, bytes=%s",
                context,
                response.status_code,
                len(response.content or b""),
            )

            return response

        except (
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectionError,
        ) as exc:
            last_exc = exc
            logging.warning("%s: kapcsolódási hiba: %s", context, exc)

            if attempt < attempts:
                sleep_seconds = min(30 * attempt, 120)
                logging.info("%s: várakozás újrapróbálás előtt: %s mp", context, sleep_seconds)
                time_module.sleep(sleep_seconds)

    raise RuntimeError(
        f"{context}: nem sikerült kapcsolódni az UNAS API-hoz {attempts} próbálkozás után. "
        f"Ez valószínűleg UNAS API elérhetőségi, tűzfal, IP-szűrés vagy GitHub runner hálózati probléma."
    ) from last_exc


def get_token(session: requests.Session, config: Config) -> str:
    xml = f"""
<Request>
  <ApiKey>{config.unas_api_key}</ApiKey>
  <WebshopInfo>true</WebshopInfo>
</Request>
""".strip()

    headers = {
        "Content-Type": "application/xml",
        "Accept": "application/xml",
    }

    response = request_with_manual_retry(
        session,
        "POST",
        LOGIN_URL,
        context="UNAS login token lekérése",
        attempts=TOKEN_ATTEMPTS,
        data=xml.encode("utf-8"),
        headers=headers,
    )

    raise_for_status_with_body(response, "UNAS login")
    return parse_xml_field(response.content, "Token", "UNAS login")


def request_product_db_url(session: requests.Session, token: str) -> str:
    xml = """
<Request>
  <Format>xlsx</Format>
  <Compress>no</Compress>
  <GetStatus>1</GetStatus>
  <GetStock>1</GetStock>
  <GetPrice>1</GetPrice>
  <GetPriceSale>1</GetPriceSale>
  <GetMinQty>1</GetMinQty>
</Request>
""".strip()

    headers = {
        "Content-Type": "application/xml",
        "Accept": "application/xml",
        "Authorization": f"Bearer {token}",
    }

    response = request_with_manual_retry(
        session,
        "POST",
        PRODUCTDB_URL,
        context="UNAS termékadatbázis URL lekérése",
        attempts=PRODUCTDB_ATTEMPTS,
        data=xml.encode("utf-8"),
        headers=headers,
    )

    raise_for_status_with_body(response, "UNAS termékadatbázis URL lekérése")
    return parse_xml_field(response.content, "Url", "UNAS termékadatbázis URL lekérése")


def download_excel(session: requests.Session, download_url: str) -> BytesIO:
    response = request_with_manual_retry(
        session,
        "GET",
        download_url,
        context="UNAS XLSX letöltése",
        attempts=DOWNLOAD_ATTEMPTS,
    )

    raise_for_status_with_body(response, "UNAS XLSX letöltése")

    if not response.content:
        raise RuntimeError("UNAS XLSX letöltése: üres fájlt kaptunk.")

    return BytesIO(response.content)


def parse_date_or_default(value: object, fallback: date) -> date:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return fallback

    parsed = pd.to_datetime(value, errors="coerce")

    if pd.isna(parsed):
        return fallback

    return parsed.date()


def format_merchant_datetime(value: date) -> str:
    local_midnight = datetime.combine(value, time.min, tzinfo=BUDAPEST_TZ)
    return local_midnight.strftime("%Y-%m-%dT%H:%M%z")


def convert_sale_date(start: object, end: object, sale_price: object) -> str:
    sale_price_numeric = pd.to_numeric(sale_price, errors="coerce")

    if pd.isna(sale_price_numeric) or float(sale_price_numeric) <= 0:
        return ""

    today = datetime.now(BUDAPEST_TZ).date()
    default_end = (pd.Timestamp(today) + pd.DateOffset(years=1)).date()

    start_date = parse_date_or_default(start, today)
    end_date = parse_date_or_default(end, default_end)

    return f"{format_merchant_datetime(start_date)}/{format_merchant_datetime(end_date)}"


def validate_columns(df: pd.DataFrame) -> None:
    missing_columns = REQUIRED_COLUMNS - set(df.columns)

    if missing_columns:
        raise RuntimeError(
            "Hiányzó oszlopok az UNAS exportból: " + ", ".join(sorted(missing_columns))
        )


def build_feed_dataframe(excel_data: BytesIO, config: Config) -> pd.DataFrame:
    df = pd.read_excel(excel_data)
    input_row_count = len(df)

    validate_columns(df)

    status_numeric = pd.to_numeric(df["Státusz"], errors="coerce").fillna(0).astype(int)
    stock_as_text = df["Raktárkészlet"].astype(str).str.strip().str.lower()

    df = df[(status_numeric == 1) & (stock_as_text != "off")].copy()

    df["Min. Menny."] = pd.to_numeric(df["Min. Menny."], errors="coerce").fillna(1)

    df["Bruttó Ár"] = pd.to_numeric(df["Bruttó Ár"], errors="coerce").fillna(0)
    df["Akciós Bruttó Ár"] = pd.to_numeric(df["Akciós Bruttó Ár"], errors="coerce").fillna(0)

    if config.multiply_by_min_qty:
        df["Bruttó Ár"] = df["Bruttó Ár"] * df["Min. Menny."]
        df["Akciós Bruttó Ár"] = df["Akciós Bruttó Ár"] * df["Min. Menny."]

    df["Bruttó Ár"] = df["Bruttó Ár"].round(0).astype(int)

    df["_Akciós Bruttó Ár Numeric"] = df["Akciós Bruttó Ár"].round(0)

    df["Akciós Bruttó Ár"] = df["_Akciós Bruttó Ár Numeric"].apply(
        lambda value: int(value) if value > 0 else ""
    )

    df["Raktárkészlet"] = (
        pd.to_numeric(df["Raktárkészlet"], errors="coerce")
        .fillna(0)
        .clip(lower=0)
        .round(0)
        .astype(int)
    )

    feed_df = df[
        [
            "Cikkszám",
            "Bruttó Ár",
            "Akciós Bruttó Ár",
            "Akció Kezdet",
            "Akció Lejárat",
            "Raktárkészlet",
            "_Akciós Bruttó Ár Numeric",
        ]
    ].copy()

    feed_df["store_code"] = config.store_code
    feed_df["availability"] = "in_stock"
    feed_df["pickup_method"] = "buy"
    feed_df["pickup_sla"] = "same day"

    feed_df["sale_price_effective_date"] = feed_df.apply(
        lambda row: convert_sale_date(
            row["Akció Kezdet"],
            row["Akció Lejárat"],
            row["_Akciós Bruttó Ár Numeric"],
        ),
        axis=1,
    )

    feed_df.rename(
        columns={
            "Cikkszám": "id",
            "Bruttó Ár": "price",
            "Akciós Bruttó Ár": "sale_price",
            "Raktárkészlet": "quantity",
        },
        inplace=True,
    )

    feed_df = feed_df[OUTPUT_COLUMNS]

    logging.info(
        "UNAS export feldolgozva. Bejövő sorok: %s, feed sorok: %s",
        input_row_count,
        len(feed_df),
    )

    if feed_df.empty:
        logging.warning("A generált feed üres. Ellenőrizd az UNAS exportot és a szűrési feltételeket.")

    return feed_df


def write_outputs(feed_df: pd.DataFrame, config: Config) -> None:
    txt_path = config.output_dir / config.txt_filename

    feed_df.to_csv(
        txt_path,
        sep="\t",
        index=False,
        encoding="utf-8",
        lineterminator="\n",
    )

    logging.info("TXT feed mentve: %s", txt_path)

    if config.write_debug_xlsx:
        xlsx_path = config.output_dir / config.xlsx_filename
        feed_df.to_excel(xlsx_path, index=False)
        logging.info("Debug XLSX mentve: %s", xlsx_path)


def run() -> None:
    config = load_config()
    session = build_http_session()

    log_network_diagnostics()

    logging.info("UNAS token lekérése...")
    token = get_token(session, config)

    logging.info("UNAS termékadatbázis letöltési URL lekérése...")
    download_url = request_product_db_url(session, token)

    logging.info("UNAS XLSX letöltése...")
    excel_data = download_excel(session, download_url)

    logging.info("Merchant Center feed generálása...")
    feed_df = build_feed_dataframe(excel_data, config)

    write_outputs(feed_df, config)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    try:
        run()
    except Exception:
        logging.exception("A feed generálása sikertelen.")
        return 1

    logging.info("A feed generálása sikeresen befejeződött.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
