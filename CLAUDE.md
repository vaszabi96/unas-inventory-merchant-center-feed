# CLAUDE.md – unas-inventory-merchant-center-feed

**Ez PUBLIKUS repó.** Minden, ami ide kerül, bárki számára látható, a git-előzményekben is. Ide soha nem kerül API-kulcs, token, belső hálózati cím, nyers export, árrés vagy vevőadat. A feed csak olyan adatot tartalmazhat, ami a webshopban is nyilvános.

## Mi ez

UNAS webshop → Google Merchant Center helyi készlet feed (`product_database_raw.txt`), GitHub Pages-en publikálva. Eredetileg a `unas_inventory_program.py` állította elő GitHub Actions-ben (`.github/workflows/`). **2026-10-22-től a feedet a webshop-szinkron program publikálja a `gh-pages` ágra**; a Python-szkript és a workflow-k átmeneti állapotát a privát tudástár vezeti (WEB-013-MERCHANT-LIVE). Mielőtt a workflow-khoz vagy a szkripthez nyúlsz, ott ellenőrizd, melyik publikálási út az élő.

## Szabályok

- Feladat, státusz és döntés **nem ebben a repóban** van: a privát Buildox-tudástárban (feladatindex, WEB-013 tételek). Ide nem kerül TODO-, STATUS- vagy tervfájl.
- A feed URL-je a Merchant Centerben van beállítva; az URL vagy a fájlnév változtatása kiadási döntés, csak kifejezett felhasználói utasításra.
- Élő Actions-futtatás vagy a publikált feed módosítása csak kifejezett felhasználói utasításra.
- Commit: beszédes magyar üzenet; push előtt `git pull --rebase`; force push tilos.
