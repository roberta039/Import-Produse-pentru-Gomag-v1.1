# Gomag Importer (Streamlit + Browser Automation, fara API keys)

Acest proiect:
- citeste un Excel cu link-uri de produse
- extrage automat: titlu, descriere, specificatii, imagini, SKU, pret (cand exista), variante (cand exista)
- afiseaza un **tabel intermediar** in Streamlit pentru verificare/corectare
- genereaza fisier de import Gomag (XLSX)
- optional: ruleaza **browser automation** (Playwright) pentru:
  - login in Gomag Dashboard
  - preluare lista categorii
  - import fisier in Gomag (upload + start import)

> IMPORTANT: UI-ul din Gomag se poate schimba. Selectoarele sunt centralizate in `config.yaml`.

---

## Rulare in Streamlit Cloud (recomandat, fara local dev)

1. Urca repo-ul in GitHub (tot continutul din acest folder).
2. Streamlit Cloud -> New app -> selectezi repo -> `app.py`
3. Streamlit Cloud -> Settings -> Secrets: copiaza continutul din `.streamlit/secrets.toml.example`
   si completeaza credentialele.

### Dependinte Playwright pe Streamlit Cloud
Acest repo include:
- `packages.txt` (pachete apt)
- `postBuild` (instaleaza Chromium pentru Playwright)

---

## Excel input
Ai nevoie de o coloana cu URL-uri. Acceptam automat una dintre:
- `url`, `link`, `product_url` (case-insensitive)

---

## Reguli cerute (implementate)
- Pret final = pret_sursa * 2 (adaugi 100%)
- Daca pret lipsa -> 1 leu
- Stoc = 1
- SKU = din site (cand exista) altfel generat din URL
- Produse active (vizibile) in Gomag: `Activ in Magazin = DA`

---

## Structura
- `app.py` - interfata Streamlit
- `src/` - logica
- `src/scrapers/` - scrapers plugin-based (pe domenii) + fallback
- `config.yaml` - configurari Gomag UI automation

---

## Limitari (reale)
- Unele site-uri pot bloca scraping-ul; fallback Playwright ajuta, dar nu e garantat.
- Traducerea automata completa in RO fara niciun serviciu extern nu este garantata.
  In tabel, randurile pot fi marcate ca `needs_translation`.
