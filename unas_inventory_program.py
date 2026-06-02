import os
import requests
import xml.etree.ElementTree as ET
import sys
import pandas as pd
from io import BytesIO

base_path = os.environ.get("OUTPUT_DIR", "public")
os.makedirs(base_path, exist_ok=True)

# ── Beállítás: szorozzuk-e az árat a min. mennyiséggel? ─────────
MULTIPLY_BY_MIN_QTY = 0  # 1 = IGEN (szoroz), 0 = NEM (nem szoroz)
# ────────────────────────────────────────────────────────────────

# ── Konfiguráció ─────────────────────────────────────────────
API_KEY = os.environ.get("UNAS_API_KEY")

if not API_KEY:
    raise RuntimeError("Hiányzik az UNAS_API_KEY környezeti változó.")
BASE_URL      = "https://api.unas.eu/shop"
LOGIN_URL     = f"{BASE_URL}/login"
PRODUCTDB_URL = f"{BASE_URL}/getProductDB"
# ─────────────────────────────────────────────────────────────

def get_token():
    xml = f"""
<Request>
  <ApiKey>{API_KEY}</ApiKey>
  <WebshopInfo>true</WebshopInfo>
</Request>
"""
    headers = {
        "Content-Type": "application/xml",
        "Accept": "application/xml"
    }
    resp = requests.post(LOGIN_URL, data=xml.encode('utf-8'), headers=headers)
    resp.raise_for_status()
    token = ET.fromstring(resp.content).findtext("Token")
    if not token:
        print("Nincs token.")
        sys.exit(1)
    return token

def convert_sale_date(start, end, sale_price):
    try:
        if pd.to_numeric(sale_price, errors='coerce') > 0:
            today = pd.Timestamp.today().normalize()

            try:
                start_dt = pd.to_datetime(start) if pd.notna(start) else today
            except:
                start_dt = today

            if pd.notna(end):
                try:
                    end_dt = pd.to_datetime(end)
                except:
                    end_dt = today + pd.DateOffset(years=1)
            else:
                end_dt = today + pd.DateOffset(years=1)

            start_str = start_dt.strftime('%Y-%m-%dT00:00+0100')
            end_str = end_dt.strftime('%Y-%m-%dT00:00+0100')
            return f"{start_str}/{end_str}"
    except:
        pass
    return ""

def download_product_db(token):
    xml = f"""
<Request>
  <Format>xlsx</Format>
  <Compress>no</Compress>
  <GetStatus>1</GetStatus>
  <GetStock>1</GetStock>
  <GetPrice>1</GetPrice>
  <GetPriceSale>1</GetPriceSale>
  <GetMinQty>1</GetMinQty>
</Request>
"""
    headers = {
        "Content-Type": "application/xml",
        "Accept": "application/xml",
        "Authorization": f"Bearer {token}"
    }
    resp = requests.post(PRODUCTDB_URL, data=xml.encode('utf-8'), headers=headers)
    resp.raise_for_status()
    url = ET.fromstring(resp.content).findtext("Url")
    if not url:
        print("Nincs letöltési URL.")
        sys.exit(1)

    file_resp = requests.get(url)
    file_resp.raise_for_status()
    excel_data = BytesIO(file_resp.content)
    df = pd.read_excel(excel_data)

    # Szűrés: csak ahol státusz 1 és készlet nem "off"
    df = df[df["Státusz"] == 1]
    df = df[df["Raktárkészlet"] != "off"]

    # Minimum mennyiség oszlop mentése (alapértelmezett: 1)
    df["Min. Menny."] = pd.to_numeric(df["Min. Menny."], errors="coerce").fillna(1)

    # Alap árak számmá alakítása
    df["Bruttó Ár"] = pd.to_numeric(df["Bruttó Ár"], errors="coerce").fillna(0)
    df["Akciós Bruttó Ár"] = pd.to_numeric(df["Akciós Bruttó Ár"], errors="coerce").fillna(0)

    # Ha a kapcsoló 1, akkor szorozzuk fel a min. mennyiséggel
    if MULTIPLY_BY_MIN_QTY == 1:
        df["Bruttó Ár"] = df["Bruttó Ár"] * df["Min. Menny."]
        df["Akciós Bruttó Ár"] = df["Akciós Bruttó Ár"] * df["Min. Menny."]

    # Kerekítés / üres akciós ár, ha nincs akció
    df["Bruttó Ár"] = df["Bruttó Ár"].round(0)
    df["Akciós Bruttó Ár"] = df["Akciós Bruttó Ár"].apply(lambda x: round(x, 0) if x > 0 else "")

    # Készlet konverzió
    df["Raktárkészlet"] = pd.to_numeric(df["Raktárkészlet"], errors="coerce").fillna(0).clip(lower=0).round(0)

    # Csak a szükséges oszlopok megtartása
    df = df[[
        "Cikkszám", "Bruttó Ár", "Akciós Bruttó Ár", "Akció Kezdet", "Akció Lejárat", "Raktárkészlet"
    ]].copy()

    # Új mezők
    df["store_code"] = "03343192712828716513"
    df["availability"] = "in_stock"
    df["pickup_method"] = "buy"
    df["pickup_sla"] = "same day"

    # Akciós dátum formázás
    df["sale_price_effective_date"] = df.apply(
        lambda row: convert_sale_date(row["Akció Kezdet"], row["Akció Lejárat"], row["Akciós Bruttó Ár"]),
        axis=1
    )

    # Töröljük a dátumoszlopokat
    df.drop(columns=["Akció Kezdet", "Akció Lejárat"], inplace=True)

    # Oszlopátnevezés
    df.rename(columns={
        "Cikkszám": "id",
        "Bruttó Ár": "price",
        "Akciós Bruttó Ár": "sale_price",
        "Raktárkészlet": "quantity"
    }, inplace=True)

    # Mentés
    df.to_excel(os.path.join(base_path, "product_database_raw.xlsx"), index=False)
    df.to_csv(os.path.join(base_path, "product_database_raw.txt"), sep="\t", index=False)

    print("Mentve: product_database_raw.xlsx és product_database_raw.txt")

def main():
    token = get_token()
    download_product_db(token)

if __name__ == '__main__':
    main()
