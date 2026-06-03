# UNAS Inventory → Google Merchant Center feed

Ez a repository egy automatikus termék- és készletfeed-generátort tartalmaz.

A folyamat lényege:

```text
UNAS webshop API
   ↓
Python script GitHub Actions-ben
   ↓
product_database_raw.txt
   ↓
GitHub Pages publikus URL
   ↓
Google Merchant Center
```

A megoldáshoz nem kell NAS, Vercel, Supabase vagy Google Drive. A GitHub tárolja a kódot, a GitHub Actions futtatja a scriptet, a GitHub Pages pedig publikálja a Merchant Center által letölthető TXT fájlt.

---

## Fájlok

```text
unas_inventory_program.py
requirements.txt
README.md
.github/workflows/update-feed.yml
```

### `unas_inventory_program.py`

A fő Python script. Feladatai:

1. bejelentkezik az UNAS API-ba;
2. lekéri az UNAS termékadatbázist XLSX formátumban;
3. Pandas-szal feldolgozza az adatokat;
4. kiszűri az inaktív termékeket és az `off` készletű sorokat;
5. előállítja a Google Merchant Centerhez használt TXT feedet;
6. elmenti a fájlt a `public/product_database_raw.txt` útvonalra.

### `requirements.txt`

Szükséges Python csomagok:

```txt
requests
pandas
openpyxl
```

### `.github/workflows/update-feed.yml`

A GitHub Actions workflow. Ez futtatja időzítve a Python scriptet, majd publikálja a `public` mappa tartalmát GitHub Pages-re.

---

## Kimeneti fájl

A fő kimenet:

```text
product_database_raw.txt
```

A fájl tabulátorral tagolt TXT/TSV formátumú.

Alapértelmezett publikus URL:

```text
https://vaszabi96.github.io/unas-inventory-merchant-center-feed/product_database_raw.txt
```

Ezt az URL-t kell megadni a Google Merchant Centerben ütemezett fájllekéréshez.

---

## Kimeneti oszlopok

A script jelenleg ezeket az oszlopokat generálja:

| Oszlop | Jelentés |
|---|---|
| `id` | UNAS cikkszám |
| `price` | bruttó ár |
| `sale_price` | akciós bruttó ár, ha van |
| `quantity` | készlet |
| `store_code` | Google üzletazonosító |
| `availability` | jelenleg fixen `in_stock` |
| `pickup_method` | jelenleg fixen `buy` |
| `pickup_sla` | jelenleg fixen `same day` |
| `sale_price_effective_date` | akciós ár érvényességi időszaka |

Az `availability`, `pickup_method` és `pickup_sla` értékek szándékosan fixek, mert a jelenlegi üzleti logika szerint minden exportált terméket ilyen módon kell átadni a Merchant Centernek.

---

## GitHub Secret beállítása

Az UNAS API kulcsot nem szabad a kódba írni.

GitHubon ezt kell beállítani:

```text
Repository → Settings → Secrets and variables → Actions → New repository secret
```

Secret neve:

```text
UNAS_API_KEY
```

Secret értéke:

```text
az UNAS API kulcs
```

Ha az API kulcs korábban szerepelt kódban vagy publikus helyen, célszerű új UNAS API kulcsot generálni.

---

## Opcionális környezeti változók

| Név | Alapértelmezés | Jelentés |
|---|---:|---|
| `OUTPUT_DIR` | `public` | ide menti a kimeneti fájlt |
| `GOOGLE_STORE_CODE` | `03343192712828716513` | Google üzletazonosító |
| `MULTIPLY_BY_MIN_QTY` | `0` | ha `1`, az árakat felszorozza a minimum mennyiséggel |
| `WRITE_DEBUG_XLSX` | `0` | ha `1`, TXT mellett XLSX debug fájlt is ment |

A normál működéshez csak az `UNAS_API_KEY` kötelező.

---

## GitHub Pages beállítása

A repositoryban:

```text
Settings → Pages
```

A `Build and deployment` résznél:

```text
Source → GitHub Actions
```

Nem branchből kell deployolni, hanem GitHub Actionsből.

---

## Kézi futtatás

GitHubon:

```text
Actions → Generate UNAS Merchant Feed → Run workflow
```

Branch maradhat:

```text
main
```

Sikeres futás után a TXT feed elérhető lesz a GitHub Pages URL-en.

---

## Google Merchant Center beállítása

Merchant Centerben a fájlos adatforrásnál ezt kell használni:

```text
Enter a link to your file
```

URL:

```text
https://vaszabi96.github.io/unas-inventory-merchant-center-feed/product_database_raw.txt
```

A Merchant Centernek közvetlenül a TXT fájl URL-jét kell megadni, nem a repository oldalát és nem az `index.html` oldalt.

---

## Fontos működési logika

A script csak azokat a termékeket tartja meg, amelyeknél:

```text
Státusz = 1
Raktárkészlet != off
```

A készletet számmá alakítja, negatív készlet esetén 0-ra vágja, majd egész számra kerekíti.

Az árakat szintén számmá alakítja és egészre kerekíti.

Ha nincs akciós ár, a `sale_price` és a `sale_price_effective_date` üres marad.

---

## Hibakeresés

### `Hiányzik az UNAS_API_KEY környezeti változó.`

Nincs beállítva a GitHub Secret.

Ellenőrizd:

```text
Settings → Secrets and variables → Actions
```

A secret neve pontosan ez legyen:

```text
UNAS_API_KEY
```

### `Hiányzó oszlopok az UNAS exportból`

Az UNAS export formátuma megváltozott, vagy más néven érkezik valamelyik oszlop.

A script ezeket várja:

```text
Cikkszám
Státusz
Raktárkészlet
Min. Menny.
Bruttó Ár
Akciós Bruttó Ár
Akció Kezdet
Akció Lejárat
```

### `UNAS login: HTTP hiba`

Általában hibás API kulcs, jogosultsági probléma vagy átmeneti UNAS API hiba.

### `UNAS XLSX letöltése: üres fájlt kaptunk.`

Az UNAS adott letöltési URL-t, de a letöltött fájl üres volt.

---

## Lokális futtatás teszteléshez

Terminálban:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export UNAS_API_KEY="ide_jön_az_unas_api_kulcs"
python unas_inventory_program.py
```

Windows PowerShellben:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:UNAS_API_KEY="ide_jön_az_unas_api_kulcs"
python unas_inventory_program.py
```

A kimenet alapértelmezetten itt jön létre:

```text
public/product_database_raw.txt
```

---

## Biztonság

API kulcsot nem szabad commitolni.

Ne legyen ilyen a kódban:

```python
API_KEY = "konkrét_api_kulcs"
```

Helyette mindig környezeti változóból kell olvasni:

```python
UNAS_API_KEY
```
