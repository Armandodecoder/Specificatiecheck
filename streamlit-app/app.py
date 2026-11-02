"""Specificatiecheck BS – Streamlit-app.

Upload de maandspecificatie uit BS; de app controleert elke rit en levert een Excel met de bevindingen.
Starten op je eigen pc:  streamlit run app.py
"""
import hashlib
import io
import os

import pandas as pd
import streamlit as st

import speccheck as sc

MAP = os.path.dirname(os.path.abspath(__file__))
GEO = os.path.join(MAP, 'geo.json')
DIST = os.path.join(MAP, 'osrm_dist.json')

st.set_page_config(page_title='Specificatiecheck BS', page_icon='🚐', layout='wide')
st.title('Specificatiecheck BS')
st.caption('Controle per rit op afstandsfouten, omwegen in de volgorde en dubbel aangedane postcodes. '
           'De kolom "ET-beladen afstand KM" komt uit BS; wegafstanden zijn een indicatie via PDOK en OpenStreetMap.')

bestand = st.file_uploader('Ritspecificatie uit BS (Excel, met twee kopregels)', type=['xlsx', 'xls'])
if not bestand:
    st.info('Kies het Excel-bestand van de maand, bijvoorbeeld "2026-10 LWD-5.xlsx".')
    st.stop()

data = bestand.getvalue()


def analyse(data: bytes, naam: str):
    seqs = sc.sequenties(io.BytesIO(data))
    pcs = sorted({p for s in seqs for p in s})
    with st.status('Postcodes en wegafstanden controleren…', expanded=False) as status:
        router = sc.build_router(pcs, seqs, GEO, DIST, log=status.write)
        status.update(label='Ritten controleren…')
        uit = io.BytesIO()
        df, fl, overzicht, pcs_tab = sc.main(io.BytesIO(data), uit, router, naam=naam)
        status.update(label='Klaar', state='complete')
    return df, fl, overzicht, pcs_tab, uit.getvalue()


sleutel = hashlib.sha1(data).hexdigest()
if st.session_state.get('sleutel') != sleutel:
    try:
        st.session_state['res'] = analyse(data, bestand.name)
        st.session_state['sleutel'] = sleutel
    except Exception as e:  # noqa
        st.error(f'Dit bestand kon niet gecontroleerd worden: {e}')
        st.stop()
df, fl, overzicht, pcs_tab, xlsx = st.session_state['res']

KM, KOST = sc.KM, sc.KOST
hoog = (df['Ernst'] == 'Hoog').sum()
contr = (df['Ernst'] == 'Controleren').sum()
teveel = (df[KOST] - (df['Verwacht km'] * df[sc.TARIEF]).round(2))[df['Ernst'] != ''].sum(skipna=True)

c = st.columns(5)
c[0].metric('Totaal gefactureerd', f"€ {df[KOST].sum():,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
c[1].metric('Ritten met code', int(hoog + contr))
c[2].metric('Ernst hoog', int(hoog))
c[3].metric('Te controleren', int(contr))
c[4].metric('Mogelijk te veel (schatting)', f"€ {teveel:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))

st.download_button('Download Excel met resultaten', xlsx,
                   file_name=f"Specificatiecheck {os.path.splitext(bestand.name)[0]}.xlsx",
                   mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', type='primary')

geen = df[df['Code'] == 'GEGEVENS_FOUT']
if len(geen):
    st.warning(f'{len(geen)} ritten met een gegevensfout (bijv. postcode niet gevonden). Zie code GEGEVENS_FOUT.')

tab1, tab2, tab3, tab4 = st.tabs(['Gemarkeerde ritten', 'Routeoverzicht', 'Verdachte postcodes', 'Uitleg'])

with tab1:
    codes = [g for g in sc.GROEPEN if (fl['Code'] == g).any()]
    k1, k2, k3 = st.columns([2, 1, 2])
    kies = k1.multiselect('Code', codes, default=codes)
    ernst = k2.selectbox('Ernst', ['Alle', 'Hoog', 'Controleren'])
    zoek = k3.text_input('Zoek op routenummer of postcode')
    v = fl[fl['Code'].isin(kies)]
    if ernst != 'Alle':
        v = v[v['Ernst'] == ernst]
    if zoek:
        z = zoek.replace(' ', '').upper()
        tekst = (v['Routenummer'].astype(str) + v[sc.PC_O].astype(str) + v[sc.PC_V].fillna('').astype(str)
                 + v[sc.PC_E].astype(str)).str.upper()
        v = v[tekst.str.contains(z, regex=False)]
    st.caption(f'{len(v)} ritten')
    st.dataframe(v, use_container_width=True, hide_index=True, height=560,
                 column_config={'Redenen': st.column_config.TextColumn(width='large')})

with tab2:
    mk = fl.groupby('Routenummer').size()
    o = overzicht.copy()
    o['Met code'] = o['Routenummer'].map(mk).fillna(0).astype(int)
    if st.checkbox('Alleen routes met meldingen', value=True):
        o = o[o['Met code'] > 0]
    st.dataframe(o, use_container_width=True, hide_index=True, height=560)

with tab3:
    if len(pcs_tab):
        st.dataframe(pcs_tab, use_container_width=True, hide_index=True)
    else:
        st.write('Geen verdachte postcodes in dit bestand.')

with tab4:
    st.markdown('''
**AFSTAND_FOUT_BS** – de afstand in BS klopt niet: rit > 150 km, BS-km > 1,25 × de wegafstand van exact dezelfde volgorde,
verdachte postcode, kosten ≠ km × tarief of onlogische snelheid.

**LANGER_DAN_NORMAAL** – rit > 2 km én > 10% langer dan een rit van dezelfde route en richting met dezelfde of méér stops.

**VOLGORDE_NIET_OPTIMAAL** – een andere volgorde van dezelfde stops is ≥ 2 km en ≥ 10% korter over de weg
('s ochtends mag elk thuisadres het eerste zijn, 's middags het laatste; school ligt vast).

**POSTCODE_DUBBEL** – dezelfde postcode wordt twee keer aangedaan met een andere stop ertussen.

**GEGEVENS_FOUT** – dubbele rit, ongeldige postcode, minder stops dan passagiers of postcode niet gevonden.

*Routenummer* = route (4 cijfers) + weekdag (1 = ma … 5 = vr) + richting (0 = ochtend, 1 = middag).
Het contract met de gemeente gaat uit van EasyTravel; deze controle vergelijkt BS-km met wegafstanden als onafhankelijke indicatie.
''')
