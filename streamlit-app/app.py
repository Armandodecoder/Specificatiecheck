"""Specificatiecheck BS – Streamlit-app.

Upload de maandspecificatie uit BS; de app controleert elke rit en levert een Excel met de bevindingen.
Starten op je eigen pc:  streamlit run app.py
"""
import hashlib
import io, time
import os

import pandas as pd
import streamlit as st

import speccheck as sc

MAP = os.path.dirname(os.path.abspath(__file__))
GEO = os.path.join(MAP, 'geo.json')
DIST = os.path.join(MAP, 'osrm_dist.json')
DUR = os.path.join(MAP, 'osrm_dur.json')

LOGO = os.path.join(MAP, 'logo.png')

st.set_page_config(page_title='Specificatiecheck BS', page_icon=LOGO if os.path.exists(LOGO) else None, layout='wide')
st.markdown('''
<style>
  /* Witteveen-huisstijl: oranje verloop bovenaan, donkere koppen, oranje accenten */
  [data-testid="stHeader"] { background: linear-gradient(90deg, #f68318, #fbb03b); height: 4px; }
  h1, h2, h3 { color: #15222c; letter-spacing: -0.01em; }
  [data-testid="stMetricValue"] { color: #15222c; font-weight: 700; }
  [data-testid="stMetricLabel"] p { color: #5b6a76; font-size: 0.85rem; text-transform: uppercase; letter-spacing: .05em; }
  .stTabs [aria-selected="true"] { color: #b65407 !important; }
  .stTabs [data-baseweb="tab-highlight"] { background-color: #f68318 !important; }
</style>''', unsafe_allow_html=True)

kop_logo, kop_titel = st.columns([1, 8], vertical_alignment='center')
if os.path.exists(LOGO):
    kop_logo.image(LOGO, width=120)
kop_titel.title('Specificatiecheck BS')
st.caption('Controle per rit op afstandsfouten, omwegen in de volgorde en dubbel aangedane postcodes. '
           'Of een route logisch is (van eerste tot laatste postcode) wordt altijd in km over de weg bekeken, '
           'ook als de specificatie op minuten afrekent. Wegafstanden zijn een indicatie via PDOK en OpenStreetMap.')

bestand = st.file_uploader('Ritspecificatie uit BS (Excel, met twee kopregels)', type=['xlsx', 'xls'])
if not bestand:
    st.info('Kies het Excel-bestand van de maand, bijvoorbeeld "2026-10 LWD-5.xlsx".')
    st.stop()

data = bestand.getvalue()


def analyse(data: bytes, naam: str):
    eenheid = sc.stel_modus(sc.load(io.BytesIO(data)))          # afrekenen op km of op minuten
    seqs = sc.sequenties(io.BytesIO(data))
    pcs = sorted({p for s in seqs for p in s})
    wat = 'wegafstanden'
    balk = st.progress(0.0, text='Starten…')
    t0 = time.time()

    def voortgang(begin, eind):
        def f(frac, tekst=''):
            tot = begin + (eind - begin) * min(max(frac, 0.0), 1.0)
            verstreken = time.time() - t0
            rest = ''
            if tot > 0.05 and verstreken > 2:
                sec = int(verstreken / tot * (1 - tot))
                rest = f' · nog ongeveer {sec // 60} min {sec % 60:02d} s' if sec >= 60 else f' · nog ongeveer {sec} s'
            balk.progress(tot, text=f'{tekst} – {tot:.0%}{rest}')
        return f

    with st.status(f'Postcodes en {wat} controleren…', expanded=False) as status:
        router = sc.build_router(pcs, seqs, GEO, DIST, log=status.write, eenheid='km', dur_path=None,
                                 voortgang=voortgang(0.0, 0.3))
        status.update(label='Ritten controleren…')
        res = sc.main(io.BytesIO(data), None, router, naam=naam,   # Excel pas maken als erom gevraagd wordt
                      voortgang=voortgang(0.3, 1.0))
        status.update(label='Klaar', state='complete')
    balk.empty()
    namen = dict(E=sc.EENHEID, KM=sc.KM, TARIEF=sc.TARIEF, WEG_ACT=sc.WEG_ACT, WEG_OPT=sc.WEG_OPT, BESP=sc.BESP,
                 VERW=sc.VERW, duur=time.time() - t0)
    return res + (namen,)


sleutel = hashlib.sha1(data).hexdigest() + '-v4'   # bij een nieuwe app-versie opnieuw controleren
if st.session_state.get('sleutel') != sleutel:
    try:
        st.session_state['res'] = analyse(data, bestand.name)
        st.session_state['sleutel'] = sleutel
        st.session_state.pop('xlsx', None)
    except Exception as e:  # noqa
        st.error(f'Dit bestand kon niet gecontroleerd worden: {e}')
        st.stop()
df, fl, overzicht, pcs_tab, alle, N = st.session_state['res']
E = N['E']
_d = int(round(N.get('duur', 0)))
_t = f"{_d // 60} min {_d % 60:02d} s" if _d >= 60 else f"{max(_d, 1)} s"
st.success(f"✅ **{bestand.name}** gecontroleerd in **{_t}**")

KM, KOST = N['KM'], sc.KOST
hoog = (df['Ernst'] == 'Hoog').sum()
contr = (df['Ernst'] == 'Controleren').sum()
teveel = (df[KOST] - ((df[N['VERW']] * df[N['TARIEF']]).round(2) + df[sc.VAST_DEEL]))[df['Ernst'] != ''].sum(skipna=True)

def eur(x):
    return f"€ {x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


c = st.columns(6)
c[0].metric('Totaal ritten', f"{len(df):,}".replace(',', '.'))
c[1].metric('Totaal gefactureerd', eur(df[KOST].sum()))
c[2].metric('Ritten met code', int(hoog + contr), f"{(hoog + contr) / len(df):.1%} van alle ritten".replace('.', ','),
            delta_color='off')
c[3].metric('Ernst hoog', int(hoog))
c[4].metric('Te controleren', int(contr))
c[5].metric('Mogelijk te veel (schatting)', eur(teveel))

# ritten per code
te_veel_rit = (df[KOST] - ((df[N['VERW']] * df[N['TARIEF']]).round(2) + df[sc.VAST_DEEL]))
rijen = []
for code in sc.GROEPEN:
    hoofd = df['Code'] == code
    ook = df['Overige codes'].fillna('').str.contains(code, regex=False)
    alle_c = hoofd | ook
    if not alle_c.any():
        continue
    rijen.append({'Code': code, 'Ritten (hoofdcode)': int(hoofd.sum()), 'Ritten totaal': int(alle_c.sum()),
                  '% van alle ritten': alle_c.sum() / len(df) * 100,
                  'Routes': int(df.loc[alle_c, sc.RNR].astype(str).str[:4].nunique()),
                  'Gefactureerd bij deze ritten': df.loc[hoofd, KOST].sum(),
                  'Mogelijk te veel': te_veel_rit[hoofd].sum(skipna=True)})
if rijen:
    st.dataframe(pd.DataFrame(rijen), hide_index=True, width='stretch',
                 column_config={'% van alle ritten': st.column_config.NumberColumn(format='%.1f%%'),
                                'Gefactureerd bij deze ritten': st.column_config.NumberColumn(format='€ %.2f'),
                                'Mogelijk te veel': st.column_config.NumberColumn(format='€ %.2f')})
    st.caption('Ritten (hoofdcode): elke rit telt één keer, bij zijn belangrijkste code. '
               'Ritten totaal: ook ritten waar de code als tweede bevinding voorkomt. Gefactureerd bedrag en "mogelijk te veel" per hoofdcode.')

naam_uit = f"Specificatiecheck {os.path.splitext(bestand.name)[0]}.xlsx"
if 'xlsx' not in st.session_state:
    if st.button('Maak Excel met resultaten', type='primary'):
        with st.spinner('Excel maken…'):
            buf = io.BytesIO()
            sc.write_xlsx(buf, bestand.name, df, fl, pcs_tab, alle, overzicht)
            st.session_state['xlsx'] = buf.getvalue()
        st.rerun()
else:
    st.download_button('Download Excel met resultaten', st.session_state['xlsx'], file_name=naam_uit,
                       mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', type='primary')

geen = df[df['Code'] == 'GEGEVENS_FOUT']
if len(geen):
    _pcs = ', '.join(pcs_tab.loc[~pcs_tab['Probleem'].str.startswith('zit vooral'), 'Postcode']) if len(pcs_tab) else ''
    st.warning(f'{len(geen)} ritten met een gegevensfout (code GEGEVENS_FOUT).'
               + (f' Postcode(s) die niet bestaan of niet gevonden worden: **{_pcs}** – zie tabblad "Verdachte postcodes".' if _pcs else ''))

tab1, tab2, tab3, tab4 = st.tabs(['Gemarkeerde ritten', 'Routeoverzicht', 'Verdachte postcodes', 'Uitleg'])

with tab1:
    codes = [g for g in sc.GROEPEN if (alle['Code'] == g).any()]
    k1, k2, k3 = st.columns([2, 1, 2])
    kies = k1.multiselect('Code', codes, default=codes)
    ernst = k2.selectbox('Ernst', ['Alle', 'Hoog', 'Controleren'])
    zoek = k3.text_input('Zoek op routenummer of postcode')
    k4, k5 = st.columns([3, 2])
    besp = N['BESP']
    max_extra = float(max(1.0, alle[besp].max(skipna=True) or 1.0)) if besp in alle else 1.0
    min_extra = k4.slider('Minimaal aantal km meer dan de kortste volgorde (over de weg)', 0.0, float(round(max_extra + 0.5)),
                          0.0, 0.5)
    zonder_code = k5.checkbox('Ook ritten zonder code', value=False)

    v = alle.copy()
    if not zonder_code:
        v = v[v['Ernst'] != '']
        v = v[v['Code'].isin(kies)]
    if ernst != 'Alle':
        v = v[v['Ernst'] == ernst]
    if min_extra > 0:
        v = v[v[besp].fillna(0) >= min_extra]
    if zoek:
        z = zoek.replace(' ', '').upper()
        tekst = (v[sc.RNR].astype(str) + v[sc.PC_O].astype(str) + v[sc.PC_V].fillna('').astype(str)
                 + v[sc.PC_E].astype(str)).str.upper()
        v = v[tekst.str.contains(z, regex=False)]

    MEER = 'Meer km dan kortste'
    v = v.rename(columns={besp: MEER, N['WEG_ACT']: 'Weg-km gereden', N['WEG_OPT']: 'Weg-km kortste',
                          KM: f'BS-{E}', sc.RNR: 'Routenummer'})
    v['Datum'] = pd.to_datetime(v[sc.DAT]).dt.date
    v['Gereden volgorde'] = (v[sc.PC_O].astype(str) + ' > ' + v[sc.PC_V].fillna('').astype(str).str.replace(',', ' > ')
                             + ' > ' + v[sc.PC_E].astype(str)).str.replace(' >  > ', ' > ')
    toon = ['Rij in bron', 'Datum', 'Routenummer', 'Dag', 'Richting', 'Ernst', 'Code', 'Overige codes',
            f'BS-{E}', 'Weg-km gereden', 'Weg-km kortste', MEER, 'Gereden volgorde', 'Optimale volgorde',
            N['VERW'], KOST, 'Redenen']
    v = v[[c for c in toon if c in v.columns]]
    if min_extra > 0:
        v = v.sort_values(MEER, ascending=False)
    st.caption(f"{len(v)} ritten · samen {v[MEER].sum() if MEER in v else 0:,.1f} km meer dan de kortste volgorde"
               .replace(',', 'X').replace('.', ',').replace('X', '.'))
    st.dataframe(v, width='stretch', hide_index=True, height=560,
                 column_config={'Redenen': st.column_config.TextColumn(width='large'),
                                MEER: st.column_config.NumberColumn(format='%.2f km'),
                                KOST: st.column_config.NumberColumn('Gefactureerd', format='€ %.2f')})

with tab2:
    mk = fl.groupby('Routenummer').size()
    o = overzicht.copy()
    o['Met code'] = o['Routenummer'].map(mk).fillna(0).astype(int)
    if st.checkbox('Alleen routes met meldingen', value=True):
        o = o[o['Met code'] > 0]
    st.dataframe(o, width='stretch', hide_index=True, height=560)

with tab3:
    if len(pcs_tab):
        st.dataframe(pcs_tab, width='stretch', hide_index=True)
    else:
        st.write('Geen verdachte of onbekende postcodes in dit bestand.')

with tab4:
    st.markdown('''
**BEDRAG_KLOPT_NIET** – het gefactureerde bedrag is niet gelijk aan km (of minuten) × tarief + vast deel
(vaste kosten per rit, bij minuten ook instap- en aanrijtijd, min korting).

**AFSTAND_FOUT_BS** – de afstand of rittijd in BS klopt niet: rit > 150 km (of > 180 min), BS veel hoger dan verwacht op basis van de km over de weg
voor exact dezelfde volgorde (gecorrigeerd voor het gemiddelde verschil in het bestand), verdachte postcode of onlogische snelheid.

**LANGER_DAN_NORMAAL** – rit > 2 km (3 min) én > 10% langer dan een rit van dezelfde route en richting met dezelfde of méér stops.

**VOLGORDE_NIET_OPTIMAAL** – een andere volgorde van dezelfde stops is ≥ 2 km en ≥ 10% korter over de weg
('s ochtends mag elk thuisadres het eerste zijn, 's middags het laatste; school ligt vast).

**POSTCODE_DUBBEL** – dezelfde postcode wordt twee keer aangedaan met een andere stop ertussen.

**GEGEVENS_FOUT** – dubbele rit, ongeldige postcode, minder stops dan passagiers of postcode niet gevonden.

*Routenummer* = route (4 cijfers) + weekdag (1 = ma … 5 = vr) + richting (0 = ochtend, 1 = middag).
De app herkent zelf of een specificatie op km (LWD, KZS) of op minuten (Dronten) afrekent; dat bepaalt alleen de bedragcontrole. Of de route logisch is, wordt altijd in km over de weg bekeken.
Het contract met de gemeente gaat uit van EasyTravel; deze controle vergelijkt BS met OpenStreetMap als onafhankelijke indicatie.
''')
