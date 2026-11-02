# Specificatiecheck BS

Streamlit-app die de maandelijkse ritspecificatie uit BS controleert op afstandsfouten,
omwegen in de volgorde en dubbel aangedane postcodes, en een Excel met de bevindingen levert.

## Bestanden

| Bestand | Wat |
|---|---|
| `app.py` | de webpagina (upload, tabellen, download) |
| `speccheck.py` | de controles (zelfde regels als `specificatie_check.py`) |
| `geo.json` | coördinaten per postcode (PDOK) |
| `osrm_dist.json` | wegafstanden tussen postcodes (OpenStreetMap) |
| `requirements.txt` | benodigde Python-pakketten |

Nieuwe postcodes worden bij het controleren automatisch opgehaald bij PDOK en OpenStreetMap.
Op Streamlit Cloud blijven die alleen bewaard tot de app herstart; zet ze af en toe terug in de
repository door `geo.json` en `osrm_dist.json` van je eigen pc te uploaden (zie onder).

## Op je eigen pc draaien

```
pip install -r requirements.txt
streamlit run app.py
```

## Online zetten (Streamlit Community Cloud)

1. Maak op github.com een **privé** repository, bijvoorbeeld `specificatiecheck`.
2. Upload alle bestanden uit deze map (ook de map `.streamlit`). Zet er **geen** ritspecificaties in.
3. Ga naar share.streamlit.io, log in met GitHub en kies **Create app** → de repository → `app.py`.
4. Na het starten: **Share** → zet de app op privé en voeg de e-mailadressen van je collega's toe.

Let op: bij Streamlit Cloud wordt het geüploade bestand op hun servers (VS) verwerkt.
Stem dat af met de privacyverantwoordelijke, omdat de specificatie postcodes van leerlingen bevat.
