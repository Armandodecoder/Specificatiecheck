"""Specificatiecheck: onlogische routes en kostenuitschieters in een ritspecificatie uit BS.
Gebruik: python specificatie_check.py <invoer.xlsx> <uitvoer.xlsx> [--zonder-wegafstand]
Coördinaten (PDOK) en wegafstanden (OSRM) worden opgehaald en bewaard in geo.json / osrm_dist.json naast de uitvoer.
"""
import sys, re
import numpy as np, pandas as pd

import json
def load(p):
    d=pd.read_excel(p,header=None)
    h0=d.iloc[0].ffill().fillna('').astype(str); h1=d.iloc[1].fillna('').astype(str)
    df=d.iloc[2:].copy(); df.columns=[(a+' '+b).strip() for a,b in zip(h0,h1)]
    df=df.reset_index(drop=True); df['excel_rij']=df.index+3
    for c in ['ET-Beladen tijd in min.','ET-beladen afstand KM','Totale kosten na korting','Tarief per beladen km','KM per relatie Tot. aantal km','Aantal Lopers','Aantal Rolstoelen',
              'Tarief per beladen uur','Totaal beladen reistijd per route','Extra instaptijd in min.','Vaste aan- en afrijtijd','Vaste kosten per rit','Verleende Korting']:
        if c in df.columns:
            df[c]=pd.to_numeric(df[c],errors='coerce')
    return df

from functools import lru_cache


class Router:
    def __init__(self, geo_path, dist_path, eenheid='km', dur_path=None):
        import os
        self.geo = json.load(open(geo_path))            # pc -> [lon, lat, plaats]
        self.eenheid = eenheid
        if eenheid == 'min':                            # "a|b" -> seconden rijtijd
            d = json.load(open(dur_path)) if dur_path and os.path.exists(dur_path) else {}
            self.deler = 60.0
        else:                                           # "a|b" -> meters
            d = json.load(open(dist_path))
            self.deler = 1000.0
        self.D = {tuple(k.split('|')): v for k, v in d.items()}

    def d(self, a, b):
        if a == b:
            return 0.0
        v = self.D.get((a, b))
        if v is None:
            raise KeyError((a, b))
        return v / self.deler

    def route_km(self, seq):
        return sum(self.d(a, b) for a, b in zip(seq, seq[1:]))

    def optimal(self, seq, richting=None, scholen=frozenset()):
        """Kortste volgorde met vaste eerste en laatste stop; tussenstops vrij (dubbele postcodes 1x).
        richting '0' (ochtend): eerst alle thuisadressen, dan scholen. richting '1' (middag): eerst scholen, dan thuis."""
        start, end = seq[0], seq[-1]
        mid = list(dict.fromkeys(p for p in seq[1:-1] if p not in (start, end)))
        n = len(mid)
        if n <= 1:
            best = [start] + mid + [end]
            return self.route_km(best), best
        is_s = [p in scholen for p in mid]
        mask_s = sum(1 << j for j in range(n) if is_s[j])
        mask_h = ((1 << n) - 1) ^ mask_s

        def mag(mask, k):
            if richting == '0' and is_s[k]:
                return (mask & mask_h) == mask_h      # school pas als alle thuisadressen gehad
            if richting == '1' and not is_s[k]:
                return (mask & mask_s) == mask_s      # thuis pas als alle scholen gehad
            return True

        full = (1 << n) - 1
        INF = float('inf')
        dp = [[INF] * n for _ in range(1 << n)]
        par = [[-1] * n for _ in range(1 << n)]
        for j in range(n):
            if mag(0, j):
                dp[1 << j][j] = self.d(start, mid[j])
        for mask in range(1, 1 << n):
            for j in range(n):
                cur = dp[mask][j]
                if cur == INF or not (mask >> j) & 1:
                    continue
                for k in range(n):
                    if (mask >> k) & 1 or not mag(mask, k):
                        continue
                    nm = mask | (1 << k)
                    v = cur + self.d(mid[j], mid[k])
                    if v < dp[nm][k]:
                        dp[nm][k] = v
                        par[nm][k] = j
        best_j, best_v = min(((j, dp[full][j] + self.d(mid[j], end)) for j in range(n)), key=lambda x: x[1])
        order, mask, j = [], full, best_j
        while j != -1:
            order.append(mid[j])
            pj = par[mask][j]
            mask ^= 1 << j
            j = pj
        return best_v, [start] + order[::-1] + [end]


    def optimal_vrij(self, seq, richting=None, scholen=frozenset()):
        """Kortste volgorde waarbij alleen de school vastligt: ochtend vrij beginadres (eind = school vast),
        middag vrij eindadres (begin = school vast). Thuisadressen vóór scholen ('s ochtends) / erna ('s middags).
        Valt terug op optimal() als het vrije eindpunt zelf een school is of de richting onbekend is."""
        if richting == '0' and seq[0] not in scholen:
            vast, vrij_begin = seq[-1], True
        elif richting == '1' and seq[-1] not in scholen:
            vast, vrij_begin = seq[0], False
        else:
            return self.optimal(seq, richting, scholen)
        nodes = list(dict.fromkeys(p for p in seq if p != vast))
        n = len(nodes)
        if n == 0:
            return self.route_km(seq), seq
        is_s = [p in scholen for p in nodes]
        mask_s = sum(1 << j for j in range(n) if is_s[j])
        mask_h = ((1 << n) - 1) ^ mask_s

        def mag(mask, k):
            if richting == '0' and is_s[k]:
                return (mask & mask_h) == mask_h
            if richting == '1' and not is_s[k]:
                return (mask & mask_s) == mask_s
            return True

        INF = float('inf')
        full = (1 << n) - 1
        dp = [[INF] * n for _ in range(1 << n)]
        par = [[-1] * n for _ in range(1 << n)]
        for j in range(n):
            if mag(0, j):
                dp[1 << j][j] = 0.0 if vrij_begin else self.d(vast, nodes[j])
        for mask in range(1, 1 << n):
            for j in range(n):
                cur = dp[mask][j]
                if cur == INF or not (mask >> j) & 1:
                    continue
                for k in range(n):
                    if (mask >> k) & 1 or not mag(mask, k):
                        continue
                    nm = mask | (1 << k)
                    v = cur + self.d(nodes[j], nodes[k])
                    if v < dp[nm][k]:
                        dp[nm][k] = v
                        par[nm][k] = j
        eind = [(j, dp[full][j] + (self.d(nodes[j], vast) if vrij_begin else 0.0)) for j in range(n)]
        best_j, best_v = min(eind, key=lambda x: x[1])
        order, mask, j = [], full, best_j
        while j != -1:
            order.append(nodes[j])
            pj = par[mask][j]
            mask ^= 1 << j
            j = pj
        order = order[::-1]
        return best_v, (order + [vast]) if vrij_begin else ([vast] + order)


# ---------------------------------------------------------------------------
# Ophalen van coördinaten (PDOK) en wegafstanden (OSRM) met lokale cache.
# Werkt op een computer met internet; reeds opgehaalde waarden worden hergebruikt.
def build_router(postcodes, seqs, geo_path='geo.json', dist_path='osrm_dist.json', log=print, eenheid='km',
                 dur_path='osrm_dur.json', voortgang=None):
    import os, time, urllib.request, urllib.parse
    stap = voortgang or (lambda frac, tekst='': None)
    geo = json.load(open(geo_path)) if os.path.exists(geo_path) else {}
    dist = json.load(open(dist_path)) if os.path.exists(dist_path) else {}
    dur = json.load(open(dur_path)) if dur_path and os.path.exists(dur_path) else {}
    store = dur if eenheid == 'min' else dist

    def get(url):
        for poging in range(4):
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    return json.loads(r.read().decode())
            except Exception as e:  # noqa
                log(f'  fout ({e}), opnieuw...'); time.sleep(3 * (poging + 1))
        raise RuntimeError(f'ophalen mislukt: {url[:120]}')

    nieuw = [p for p in postcodes if p not in geo and not postcode_fout(p)]   # niet-bestaande postcodes niet opzoeken
    if nieuw:
        log(f'PDOK: {len(nieuw)} postcodes geocoderen...')
    for n, p in enumerate(nieuw):
        stap(0.3 * n / len(nieuw), f'Postcodes opzoeken ({n + 1} van {len(nieuw)})')
        q = urllib.parse.quote(f'postcode:{p}')
        j = get(f'https://api.pdok.nl/bzk/locatieserver/search/v3_1/free?q={q}&fq=type:postcode'
                f'&fl=postcode,centroide_ll,woonplaatsnaam&rows=1')
        docs = j['response']['docs']
        if not docs:
            log(f'  postcode {p} niet gevonden bij PDOK'); continue
        lon, lat = docs[0]['centroide_ll'].replace('POINT(', '').replace(')', '').split()
        geo[p] = [float(lon), float(lat), docs[0].get('woonplaatsnaam', '')]
    json.dump(geo, open(geo_path, 'w'))

    # Ontbrekende paren ophalen. Alleen postcodes binnen dezelfde rit hebben een afstand nodig; die ritten worden
    # gebundeld in groepjes van max. 100 postcodes, zodat één OSRM-verzoek een hele groep in één keer oplevert.
    MAXC = 100
    ritsets = []
    for s in seqs:
        u = frozenset(p for p in s if p in geo)
        if len(u) > 1 and any(f'{a}|{b}' not in store for a in u for b in u if a != b):
            ritsets.append(u)
    ritsets = sorted(set(ritsets), key=lambda u: (sorted(u)[0], -len(u)))
    groepen = []
    for u in ritsets:
        if any(u <= g for g in groepen):
            continue
        beste = max((g for g in groepen if len(g | u) <= MAXC), key=lambda g: len(g & u), default=None)
        if beste is not None and (beste & u or len(beste) + len(u) <= MAXC):
            beste |= u
        else:
            groepen.append(set(u))
    if groepen:
        log(f'OSRM: {"rijtijden" if eenheid == "min" else "afstanden"} ophalen in {len(groepen)} verzoek(en)...')
        for n, g in enumerate(groepen, 1):
            stap(0.3 + 0.7 * (n - 1) / len(groepen), f'Wegafstanden ophalen ({n} van {len(groepen)})')
            alle = sorted(g)
            coords = ';'.join(f'{geo[p][0]:.6f},{geo[p][1]:.6f}' for p in alle)
            r = get(f'https://router.project-osrm.org/table/v1/driving/{coords}?annotations=distance,duration')
            for a, row, trow in zip(alle, r['distances'], r['durations']):
                for b, v, t in zip(alle, row, trow):
                    if a != b and v is not None:
                        dist[f'{a}|{b}'] = round(v)
                    if a != b and t is not None:
                        dur[f'{a}|{b}'] = round(t)
            if n < len(groepen):
                time.sleep(1.0)  # openbare OSRM-server: max ~1 verzoek per seconde
    stap(1.0, 'Wegafstanden klaar')
    json.dump(dist, open(dist_path, 'w'))
    if dur_path:
        json.dump(dur, open(dur_path, 'w'))
    return Router(geo_path, dist_path, eenheid, dur_path)


KM, MIN, KOST, TARIEF = 'ET-beladen afstand KM', 'ET-Beladen tijd in min.', 'Totale kosten na korting', 'Tarief per beladen km'
RNR, DAT = 'Route- nummer', 'Route- datum'
PC_O, PC_V, PC_E = 'Postcode 1e oph adres', 'Postcode(s) via', 'Postcode eindbestemming'

# Drempels (aanpasbaar)
MAX_KM = 150            # boven deze rit-afstand is een rit binnen de regio onmogelijk
SNELHEID = (10, 90)     # km/u gemiddeld
VAST_PCT, VAST_KM = 0.10, 2         # rit langer dan de vaste route van het routenummer, zonder extra stops
VOLG_PCT, VOLG_KM = 0.10, 3         # zelfde stops, andere volgorde is zoveel korter
CORR_FACT, CORR_KM, CORR_N = 1.4, 5, 6
OPT_KM, OPT_PCT = 2, 0.10         # optimale volgorde is zoveel korter (over de weg)
GROEPEN = {   # hoofdcode -> onderliggende controles (volgorde = prioriteit)
    'BEDRAG_KLOPT_NIET': ['BEDRAG_KLOPT_NIET'],
    'AFSTAND_FOUT_BS': ['AFSTAND_EXTREEM', 'BS_AFSTAND_TE_HOOG', 'VERDACHTE_POSTCODE', 'SNELHEID_ONLOGISCH'],
    'LANGER_DAN_NORMAAL': ['LANGER_DAN_VASTE_ROUTE', 'UITSCHIETER_CORRIDOR'],
    'VOLGORDE_NIET_OPTIMAAL': ['VOLGORDE_NIET_OPTIMAAL', 'VOLGORDE_KAN_KORTER'],
    'POSTCODE_DUBBEL': ['POSTCODE_DUBBEL_IN_ROUTE'],
    'GEGEVENS_FOUT': ['DUBBELE_RIT', 'POSTCODE_ONGELDIG', 'MINDER_STOPS_DAN_PASSAGIERS', 'GEEN_WEGAFSTAND'],
}
GROEP_VAN = {sub: g for g, subs in GROEPEN.items() for sub in subs}
ET_RATIO, ET_KM = 1.25, 3         # BS-km t.o.v. wegafstand van dezelfde volgorde (relatief t.o.v. het gemiddelde in het bestand)

# Afrekenen op km (bijv. LWD, KZS) of op minuten (bijv. Dronten): wordt per bestand bepaald.
DREMPELS = {'km': dict(MAX_KM=150, VAST_KM=2, CORR_KM=5, OPT_KM=2, ET_KM=3, ET_RATIO=1.25),
            'min': dict(MAX_KM=180, VAST_KM=3, CORR_KM=8, OPT_KM=2, ET_KM=10, ET_RATIO=1.5)}   # OPT_KM blijft km: de routelogica gaat altijd over de weg-km
EENHEID = 'km'
WEG_ACT, WEG_OPT, BESP, RATIO_COL = 'Weg-km gereden volgorde', 'Weg-km optimale volgorde', 'Besparing km', 'BS-km / weg-km'
VERW, VASTR, VAST_DEEL = 'Verwacht km', 'Km vaste route', 'Vast deel bedrag (rit)'


def postcode_fout(p):
    """Reden waarom p geen geldige Nederlandse postcode is, of '' als hij geldig is."""
    p = str(p).strip().upper().replace(' ', '')
    if not re.match(r'^[1-9]\d{3}[A-Z]{2}$', p):
        return 'geen geldige notatie (4 cijfers + 2 letters)'
    slecht = sorted(set(p[4:]) & set('FIOQUY'))
    if slecht:
        return f'bevat de letter {"/".join(slecht)}; Nederlandse postcodes gebruiken nooit F, I, O, Q, U of Y'
    if p[4:] in ('SA', 'SD', 'SS'):
        return f'lettercombinatie {p[4:]} wordt in Nederlandse postcodes niet gebruikt'
    return ''


def stel_modus(df):
    """Bepaal of het bestand op km of op minuten afrekent en zet de kolomnamen en drempels."""
    global KM, TARIEF, EENHEID, WEG_ACT, WEG_OPT, BESP, RATIO_COL, VERW, VASTR
    global MAX_KM, VAST_KM, CORR_KM, OPT_KM, ET_KM, ET_RATIO
    if 'ET-beladen afstand KM' in df.columns and 'Tarief per beladen km' in df.columns:
        EENHEID, KM, TARIEF = 'km', 'ET-beladen afstand KM', 'Tarief per beladen km'
    elif 'ET-Beladen tijd in min.' in df.columns and 'Tarief per beladen uur' in df.columns:
        EENHEID, KM, TARIEF = 'min', 'ET-Beladen tijd in min.', 'Tarief per beladen minuut'
        df[TARIEF] = pd.to_numeric(df['Tarief per beladen uur'], errors='coerce') / 60
    else:
        raise ValueError('Geen kolom "ET-beladen afstand KM" met "Tarief per beladen km" en ook geen '
                         '"ET-Beladen tijd in min." met "Tarief per beladen uur" gevonden.')
    E = EENHEID
    # de route zelf (logische volgorde van eerste tot laatste postcode) wordt altijd in weg-km beoordeeld
    WEG_ACT, WEG_OPT, BESP, RATIO_COL = 'Weg-km gereden volgorde', 'Weg-km optimale volgorde', 'Besparing km', f'BS-{E} / weg-km'
    VERW, VASTR = f'Verwacht {E}', f'{E.capitalize()} vaste route'
    for k, v in DREMPELS[E].items():
        globals()[k] = v
    return E


def main(src, dst, router=None, naam=None, voortgang=None):
    stap = voortgang or (lambda frac, tekst='': None)
    stap(0.0, 'Bestand inlezen')
    df = load(src)
    naam = naam or str(src).replace('\\', '/').split('/')[-1]
    load_cols = list(df.columns)
    E = stel_modus(df)
    def _num(c):
        return pd.to_numeric(df[c], errors='coerce').fillna(0) if c in df.columns else pd.Series(0.0, index=df.index)
    vast_min = _num('Vaste kosten per rit') - _num('Verleende Korting')
    uurtarief, totaal_min = _num('Tarief per beladen uur'), _num('Totaal beladen reistijd per route')
    if E == 'km':
        uur = (totaal_min / 60 * uurtarief).round(2)
        df[VAST_DEEL] = (vast_min + uur).round(2)
        df['_bedrag_formule'] = (df[KM] * df[TARIEF]).round(2) + uur + vast_min
    else:
        extra_min = (totaal_min - df[KM]).clip(lower=0)            # instaptijd + vaste aan-/afrijtijd
        df[VAST_DEEL] = (vast_min + extra_min / 60 * uurtarief).round(2)
        df['_bedrag_formule'] = ((df[KM] + extra_min) / 60 * uurtarief).round(2) + vast_min
    df['_vias'] = df[PC_V].fillna('').astype(str).str.split(',').apply(lambda l: [x.strip() for x in l if x.strip()])
    df['_seq'] = df.apply(lambda r: [r[PC_O]] + r['_vias'] + [r[PC_E]], axis=1)
    df['Volgorde'] = df['_seq'].str.join(' > ')
    df['Aantal stops'] = df['_seq'].str.len()
    df['Passagiers'] = df['Aantal Lopers'].fillna(0) + df['Aantal Rolstoelen'].fillna(0)
    df['Snelheid km/u'] = (df[KM] / (df[MIN] / 60)).round(1) if E == 'km' else np.nan
    redenen = {i: [] for i in df.index}
    ernst = pd.Series(0, index=df.index)          # 2 = hoog, 1 = te controleren
    verwacht_km = pd.Series(np.nan, index=df.index)

    subcodes = {i: set() for i in df.index}

    def flag(i, code, tekst, lvl):
        subcodes[i].add(code)
        redenen[i].append(f'{GROEP_VAN[code]}: {tekst}')
        ernst[i] = max(ernst[i], lvl)

    # --- Basiscontroles ---------------------------------------------------
    stap(0.05, 'Basiscontroles')
    ongeldig = {p: postcode_fout(p) for p in {p for l in df['_seq'] for p in l}}
    ongeldig = {p: w for p, w in ongeldig.items() if w}
    for i, r in df.iterrows():
        bad = list(dict.fromkeys(p for p in r['_seq'] if p in ongeldig))
        if bad:
            flag(i, 'POSTCODE_ONGELDIG', '; '.join(f'postcode {p} bestaat niet ({ongeldig[p]})' for p in bad), 2)
        s = r['_seq']
        herh = sorted({p for j, p in enumerate(s) if p in s[:j] and s[j - 1] != p})
        if herh:
            flag(i, 'POSTCODE_DUBBEL_IN_ROUTE', f'{", ".join(herh)} komt niet-aaneengesloten twee keer voor', 1)
        if abs(r[KOST] - r['_bedrag_formule']) > 0.011:
            tar = f'{r[TARIEF]:.2f} per km' if E == 'km' else f'{r[TARIEF] * 60:.2f} per uur'
            flag(i, 'BEDRAG_KLOPT_NIET', f'gefactureerd € {r[KOST]:.2f}, volgens {r[KM]:g} {E} × {tar} + vast deel '
                 f'€ {r[VAST_DEEL]:.2f} is dat € {r["_bedrag_formule"]:.2f}', 2)
        if E == 'km' and not (SNELHEID[0] <= r['Snelheid km/u'] <= SNELHEID[1]):
            # te snel is onmogelijk (hoog); te langzaam kan bij korte ritten met veel stops (controleren)
            flag(i, 'SNELHEID_ONLOGISCH', f'gemiddelde snelheid {r["Snelheid km/u"]} km/u',
                 2 if r['Snelheid km/u'] > SNELHEID[1] else 1)
        if r['Aantal stops'] - 1 < r['Passagiers'] - 0 and r['Aantal stops'] < r['Passagiers']:
            flag(i, 'MINDER_STOPS_DAN_PASSAGIERS', f'{r["Aantal stops"]} stops, {r["Passagiers"]:.0f} pass.', 1)
    for i in df[df.duplicated([RNR, DAT], keep=False)].index:
        flag(i, 'DUBBELE_RIT', 'routenummer + datum komt vaker voor', 2)

    # --- 1. Extreme afstand + verdachte postcodes --------------------------
    ext = df[KM] > MAX_KM
    for i in df[ext].index:
        flag(i, 'AFSTAND_EXTREEM', f'{df.at[i, KM]:g} {E} (> {MAX_KM} {E})', 2)
    rows = df[['_seq']].explode('_seq').rename(columns={'_seq': 'pc'})
    rows['ext'] = ext.reindex(rows.index)
    rows = rows.reset_index().drop_duplicates(['index', 'pc'])
    pcstat = rows.groupby('pc')['ext'].agg(['size', 'sum'])
    verdacht = pcstat[(pcstat['sum'] >= 2) & (pcstat['sum'] / pcstat['size'] >= 0.95)]
    pc_tab = []
    for pc, s in verdacht.iterrows():
        m = df['_seq'].apply(lambda l: pc in l)
        # offset: zelfde routenummer met en zonder deze postcode
        diffs = []
        for rn, g in df[m | df[RNR].isin(df.loc[m, RNR])].groupby(RNR):
            met, zonder = g[g['_seq'].apply(lambda l: pc in l)], g[~g['_seq'].apply(lambda l: pc in l) & ~ext[g.index]]
            if len(met) and len(zonder):
                diffs.append(met[KM].median() - zonder[KM].median())
        offset = float(np.median(diffs)) if diffs else np.nan
        pc_tab.append(dict(Postcode=pc, **{'Ritten met postcode': int(s['size']), 'Waarvan extreme afstand': int(s['sum']),
                           f'Geschatte extra {E} per rit': round(offset, 1) if diffs else None,
                           'Gebaseerd op routenummers': len(diffs)}))
        for i in df[m & ext].index:
            flag(i, 'VERDACHTE_POSTCODE', f'{pc} zit in {int(s["sum"])} van {int(s["size"])} ritten met extreme afstand '
                 f'(waarschijnlijk verkeerd gegeocodeerd in BS)', 2)
            if diffs:
                verwacht_km[i] = round(df.at[i, KM] - offset, 2)

    norm = df[~ext]
    # --- 2. Vaste route per routenummer ------------------------------------
    # Routenummer = 2 + route(3 cijfers... totaal 4) + weekdag (1=ma..5=vr) + richting (0=ochtend, 1=middag)
    rn_s = df[RNR].astype(str)
    df['Route'] = rn_s.str[:4]
    df['Dag'] = rn_s.str[4].map({'1': 'ma', '2': 'di', '3': 'wo', '4': 'do', '5': 'vr'})
    df['_richt'] = rn_s.str[5]
    df['Richting'] = df['_richt'].map({'0': 'Ochtend (naar school)', '1': 'Middag (naar huis)'})
    scholen = frozenset(set(df.loc[df._richt == '0', PC_E]) | set(df.loc[df._richt == '1', PC_O]))
    df['_set'] = df['_seq'].apply(lambda l: frozenset(l))
    overzicht = []
    df['Ontbrekende vaste stops'] = ''
    df['Extra stops'] = ''
    df[VASTR] = np.nan
    for rn, g in df.groupby(RNR):
        cnt = pd.Series([p for st in g['_set'] for p in st]).value_counts()
        vast = frozenset(cnt[cnt >= len(g) / 2].index)
        gn = g[~ext[g.index]]
        exact = gn[gn['_set'] == vast]
        km_vast = round((exact if len(exact) else gn)[KM].median(), 2) if len(gn) else np.nan
        volg = (exact if len(exact) else g)['Volgorde'].mode().iloc[0]
        afw = 0
        for i, r in g.iterrows():
            ontb, extra = vast - r['_set'], r['_set'] - vast
            df.at[i, 'Ontbrekende vaste stops'] = ', '.join(sorted(ontb))
            df.at[i, 'Extra stops'] = ', '.join(sorted(extra))
            df.at[i, VASTR] = km_vast
            afw += bool(ontb or extra)
        overzicht.append({'Routenummer': rn, 'Route': g['Route'].iloc[0], 'Dag': g['Dag'].iloc[0],
                          'Richting': g['Richting'].iloc[0], 'Ritten': len(g), 'Vaste volgorde': volg,
                          'Aantal vaste stops': len(vast), VASTR: km_vast,
                          f'{E.capitalize()} laagst': g[KM].min(), f'{E.capitalize()} hoogst': g[KM].max(), 'Ritten met afwijkende stops': afw,
                          'Gefactureerd': round(g[KOST].sum(), 2)})
    overzicht = pd.DataFrame(overzicht)

    # Langer dan een rit van dezelfde route en richting met dezelfde of méér stops (alle weekdagen)
    for (route, richt), g in df[~ext].groupby(['Route', '_richt']):
        sets = list(zip(g.index, g['_set'], g[KM]))
        for i, st, km in sets:
            peers = [(j, k) for j, st2, k in sets if j != i and st <= st2]
            if not peers:
                continue
            j, ref = min(peers, key=lambda t: t[1])
            d = km - ref
            if d > VAST_KM and d / ref > VAST_PCT:
                meer = len(df.at[j, '_set'] - st)
                wat = 'dezelfde stops' if meer == 0 else f'dezelfde stops plus {meer} extra'
                from collections import Counter
                ci, cj = Counter(df.at[i, '_seq']), Counter(df.at[j, '_seq'])
                dub = sorted(p for p in ci if ci[p] > cj.get(p, 0))
                noot = (f'; let op: {", ".join(dub)} komt hier vaker voor (extra leerling op dezelfde postcode, '
                        f'telt in BS normaal 0 {E} extra)') if dub else ''
                flag(i, 'LANGER_DAN_VASTE_ROUTE', f'{km:g} {E}, terwijl rit {df.at[j, RNR]} van '
                     f'{pd.to_datetime(df.at[j, DAT]):%d-%m} met {wat} {ref:g} {E} was ({d:+.1f} {E}){noot}', 1)
                if np.isnan(verwacht_km[i]):
                    verwacht_km[i] = ref

    # Ochtend vs middag op dezelfde dag: wie wordt alleen gebracht of alleen opgehaald?
    df['Alleen ochtend'] = ''
    df['Alleen middag'] = ''
    thuis = df['_set'].apply(lambda st: st - scholen)
    for (route, dat), g in df.groupby(['Route', DAT]):
        och = g[g._richt == '0']; mid = g[g._richt == '1']
        if len(och) == 1 and len(mid) == 1:
            a_, b_ = thuis[och.index[0]], thuis[mid.index[0]]
            for i in (och.index[0], mid.index[0]):
                df.at[i, 'Alleen ochtend'] = ', '.join(sorted(a_ - b_))
                df.at[i, 'Alleen middag'] = ', '.join(sorted(b_ - a_))

    # (3. 'zelfde stops korter op andere dag' valt nu onder LANGER_DAN_VASTE_ROUTE)

    # --- 4. Uitschieter t.o.v. vergelijkbare ritten (zelfde PC4 begin->eind)
    rn_telling = df[RNR].value_counts()
    corr = norm[PC_O].str[:4] + '>' + norm[PC_E].str[:4]
    for c, idx in norm.groupby(corr).groups.items():
        if len(idx) < CORR_N:
            continue
        g = norm.loc[idx]
        for i in idx:
            # vergelijk met ritten in dezelfde corridor met hetzelfde of meer stops
            peers = g[(g['Aantal stops'] >= g.at[i, 'Aantal stops']) & (g.index != i)][KM]
            if len(peers) < 3:
                continue
            med = peers.median(); mad = 1.4826 * (peers - med).abs().median()
            x = g.at[i, KM]
            # alleen als de rit óók afwijkt van zijn eigen vaste route en dat niet door extra stops komt
            eigen = df.at[i, VASTR]
            n_eigen = rn_telling[df.at[i, RNR]]
            if n_eigen >= 3:          # routenummer heeft eigen referentie; dan telt LANGER_DAN_NORMAAL
                continue
            if df.at[i, 'Extra stops']:
                continue
            if x > med * CORR_FACT and x - med > CORR_KM and (mad == 0 or (x - med) / mad > 3):
                flag(i, 'UITSCHIETER_CORRIDOR', f'{x:g} {E} vs mediaan {med:.1f} {E} van {len(peers)} ritten {c} '
                     f'met evenveel of meer stops', 1)

    # --- 5. Wegafstanden (PDOK-coördinaten + OSRM) en optimale volgorde ---
    if router is not None:
        cache = {}
        act, opt, optseq = [], [], []
        n_rit = len(df)
        for n, (s, richt) in enumerate(zip(df['_seq'], df['_richt'])):
            if n % 25 == 0:
                stap(0.15 + 0.75 * n / max(1, n_rit), f'Optimale volgorde berekenen (rit {n + 1} van {n_rit})')
            k = (tuple(s), richt)
            if k not in cache:
                try:
                    a = router.route_km(s)
                    o, best = router.optimal_vrij(s, richt, scholen)
                    if o < a:   # dubbele postcodes (meerdere leerlingen op dezelfde postcode) weer direct na elkaar tonen
                        from collections import Counter
                        cnt = Counter(s)
                        best = [p for q in best for p in [q] * cnt[q]]
                    cache[k] = (a, min(o, a), best if o < a else s)
                except KeyError:          # postcode zonder coördinaat/afstand
                    cache[k] = (np.nan, np.nan, [])
            a, o, b = cache[k]
            act.append(round(a, 2)); opt.append(round(o, 2)); optseq.append(' > '.join(b))
        df[WEG_ACT] = act
        df[WEG_OPT] = opt
        df['Optimale volgorde'] = optseq
        df[BESP] = (df[WEG_ACT] - df[WEG_OPT]).round(2)
        df[RATIO_COL] = (df[KM] / df[WEG_ACT]).round(2)
        # BS rekent anders dan OpenStreetMap (bij minuten vaak duidelijk ruimer): vergelijk t.o.v. het gemiddelde in dit bestand
        f = df.loc[~ext, RATIO_COL].median()
        f = 1.0 if pd.isna(f) else float(f)
        basis = max(1.0, f) if E == 'km' else f      # bij minuten: BS-minuten per weg-km
        grens = ET_RATIO * basis
        for i, r in df.iterrows():
            sav = r[BESP]
            if pd.isna(sav):
                mis = list(dict.fromkeys(p for p in r['_seq'] if p not in router.geo))
                if mis and all(p in ongeldig for p in mis):
                    continue                     # al gemeld als POSTCODE_ONGELDIG
                if mis:
                    flag(i, 'GEEN_WEGAFSTAND', f'postcode {", ".join(mis)} niet gevonden bij PDOK; route niet nagerekend', 1)
                else:
                    flag(i, 'GEEN_WEGAFSTAND', 'geen wegafstand gevonden bij OpenStreetMap; route niet nagerekend', 1)
                continue
            if sav >= OPT_KM and sav / r[WEG_ACT] >= OPT_PCT:
                s_ = r['_seq']
                let_op = (' – let op: postcode komt dubbel voor (mogelijk tussentijdse uitstap), check of deze volgorde haalbaar is'
                          if len(set(s_)) < len(s_) else '')
                flag(i, 'VOLGORDE_NIET_OPTIMAAL', f'optimale volgorde {r["Optimale volgorde"]} is {sav:.1f} km korter '
                     f'({r[WEG_OPT]} i.p.v. {r[WEG_ACT]} km over de weg){let_op}', 1)
                if np.isnan(verwacht_km[i]):
                    verwacht_km[i] = round(r[KM] - sav * f, 2)
            ratio, extra = r[RATIO_COL], r[KM] - r[WEG_ACT] * f
            if ratio > grens and extra > ET_KM:
                if E == 'km':
                    gem = f' (gemiddeld is BS {f:.2f}× de weg)' if abs(f - 1) > 0.1 else ''
                    tekst = f'BS {r[KM]:g} km vs {r[WEG_ACT]} km over de weg (OpenStreetMap) voor exact dezelfde volgorde{gem}'
                else:
                    tekst = (f'BS {r[KM]:g} min voor {r[WEG_ACT]} km over de weg (OpenStreetMap); gemiddeld rekent BS '
                             f'{f:.2f} min per km, verwacht ± {r[WEG_ACT] * f:.0f} min')
                flag(i, 'BS_AFSTAND_TE_HOOG', tekst, 2 if ratio > 2 * basis else 1)
                if np.isnan(verwacht_km[i]) or i in df[ext].index:
                    verwacht_km[i] = round((r[WEG_OPT] if 'VOLGORDE_NIET_OPTIMAAL' in subcodes[i] else r[WEG_ACT]) * f, 2)

    # --- Uitvoer ----------------------------------------------------------
    stap(0.92, 'Resultaten samenvatten')
    df['Ernst'] = ernst.map({2: 'Hoog', 1: 'Controleren', 0: ''})
    df['Redenen'] = pd.Series({i: ' | '.join(v) for i, v in redenen.items()})
    def groepen_van(i):
        return [g for g in GROEPEN if any(GROEP_VAN[c] == g for c in subcodes[i])]
    df['Code'] = pd.Series({i: (groepen_van(i) or [''])[0] for i in df.index})
    df['Overige codes'] = pd.Series({i: ', '.join(groepen_van(i)[1:]) for i in df.index})
    # dubbele redenen (zelfde tekst) samenvoegen
    def redenen_tekst(v):
        per = {}
        for t in dict.fromkeys(v):
            g, txt = t.split(': ', 1)
            per.setdefault(g, []).append(txt)
        return ' | '.join(f'{g}: ' + '; '.join(per[g]) for g in GROEPEN if g in per)
    df['Redenen'] = pd.Series({i: redenen_tekst(v) for i, v in redenen.items()})
    df[VERW] = verwacht_km
    df['Datum'] = pd.to_datetime(df[DAT]).dt.date
    out_cols = ['excel_rij', 'Datum', RNR, 'Route', 'Dag', 'Richting', 'Ernst', 'Code', 'Overige codes', 'Redenen', 'Voertuig- type',
                'Passagiers', PC_O, PC_V, PC_E, 'Aantal stops', 'Ontbrekende vaste stops', 'Extra stops', MIN, KM,
                VASTR, 'Snelheid km/u', TARIEF, VAST_DEEL, KOST, VERW]
    if E == 'min':
        out_cols = [c for c in out_cols if c not in ('Snelheid km/u',)]
        out_cols = list(dict.fromkeys(out_cols))
    if router is not None:
        out_cols[-1:-1] = [WEG_ACT, WEG_OPT, BESP, 'Optimale volgorde']
    fl = df[ernst > 0].copy()
    fl['_s'] = -fl.index.map(ernst) * 1e6 - fl[KM]
    fl = fl.sort_values('_s')[out_cols].rename(columns={'excel_rij': 'Rij in bron', RNR: 'Routenummer'})
    orig = [c for c in load_cols if c != 'excel_rij']
    extra = ['Route', 'Dag', 'Richting', 'Ernst', 'Code', 'Overige codes', 'Redenen', VERW, VASTR,
             'Ontbrekende vaste stops', 'Extra stops', 'Alleen ochtend', 'Alleen middag']
    if router is not None:
        extra += [WEG_ACT, WEG_OPT, BESP, RATIO_COL, 'Optimale volgorde']
    alle = df[['excel_rij'] + extra + orig].copy()
    alle[DAT] = pd.to_datetime(alle[DAT]).dt.date
    alle = alle.rename(columns={'excel_rij': 'Rij in bron'})
    # postcodes die niet bestaan of niet te vinden zijn ook in de tabel 'Verdachte postcodes'
    probleem = dict(ongeldig)
    if router is not None:
        for p in {p for l in df['_seq'] for p in l}:
            if p not in router.geo and p not in probleem:
                probleem[p] = 'niet gevonden bij PDOK (postcode bestaat mogelijk niet of is nieuw)'
    rij_pc = []
    for p, w in sorted(probleem.items()):
        m = df['_seq'].apply(lambda l: p in l)
        rij_pc.append({'Postcode': p, 'Probleem': w, 'Ritten met postcode': int(m.sum()),
                       'Routenummers': ', '.join(sorted(df.loc[m, RNR].astype(str).unique())[:12])})
    for d in pc_tab:
        d['Probleem'] = 'zit vooral in ritten met een extreme afstand (waarschijnlijk verkeerd gegeocodeerd in BS)'
    pcs_tab = pd.DataFrame(rij_pc + pc_tab)
    if len(pcs_tab):
        pcs_tab = pcs_tab[['Postcode', 'Probleem'] + [c for c in pcs_tab.columns if c not in ('Postcode', 'Probleem')]]
    if dst is not None:
        write_xlsx(dst, naam, df, fl, pcs_tab, alle, overzicht)
    stap(1.0, 'Klaar')
    return df, fl, overzicht, pcs_tab, alle


def write_xlsx(dst, src, df, fl, pcs, alle, overzicht):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    F = 'Arial'
    hdr_fill = PatternFill('solid', fgColor='1F3864')
    hoog = PatternFill('solid', fgColor='F8CBAD'); contr = PatternFill('solid', fgColor='FFF2CC')

    F_KOP = Font(name=F, bold=True, color='FFFFFF'); F10 = Font(name=F, size=10)
    def table(ws, frame, r0=1):
        for j, c in enumerate(frame.columns, 1):
            cell = ws.cell(r0, j, c)
            cell.font = F_KOP; cell.fill = hdr_fill
            cell.alignment = Alignment(wrap_text=True, vertical='top')
        for i, row in enumerate(frame.itertuples(index=False), r0 + 1):
            for j, v in enumerate(row, 1):
                if isinstance(v, float) and np.isnan(v):
                    v = None
                ws.cell(i, j, v).font = F10
        ws.freeze_panes = ws.cell(r0 + 1, 1)
        ws.auto_filter.ref = f'A{r0}:{get_column_letter(len(frame.columns))}{r0 + len(frame)}'

    # Gemarkeerde ritten
    ws = wb.active; ws.title = 'Gemarkeerde ritten'
    fl = fl.copy()
    table(ws, fl)
    cols = list(fl.columns)
    ck, cv, ct, ce, cvk = (get_column_letter(cols.index(c) + 1) for c in (KOST, VERW, TARIEF, 'Ernst', VAST_DEEL))
    n = len(fl) + 1
    ws.cell(1, len(cols) + 1, 'Verwacht bedrag').font = Font(name=F, bold=True, color='FFFFFF')
    ws.cell(1, len(cols) + 2, 'Mogelijk te veel').font = Font(name=F, bold=True, color='FFFFFF')
    for c in (len(cols) + 1, len(cols) + 2):
        ws.cell(1, c).fill = hdr_fill
    for r in range(2, n + 1):
        ws.cell(r, len(cols) + 1, f'=IF({cv}{r}="","",ROUND({cv}{r}*{ct}{r},2)+{cvk}{r})').font = F10
        ws.cell(r, len(cols) + 2, f'=IF({cv}{r}="","",{ck}{r}-{get_column_letter(len(cols)+1)}{r})').font = F10
        fill = hoog if ws[f'{ce}{r}'].value == 'Hoog' else contr
        for c in range(1, len(cols) + 3):
            ws.cell(r, c).fill = fill
        for c in (ck, get_column_letter(len(cols) + 1), get_column_letter(len(cols) + 2)):
            ws[f'{c}{r}'].number_format = '€ #,##0.00'
    ws.auto_filter.ref = f'A1:{get_column_letter(len(cols)+2)}{n}'
    widths = {'Redenen': 70, 'Code': 24, 'Overige codes': 24, PC_V: 34, 'Datum': 11}
    for j, c in enumerate(cols + ['Verwacht bedrag', 'Mogelijk te veel'], 1):
        ws.column_dimensions[get_column_letter(j)].width = widths.get(c, 13)
    for r in range(2, n + 1):
        ws[f'{get_column_letter(cols.index("Redenen")+1)}{r}'].alignment = Alignment(wrap_text=True, vertical='top')

    # Verdachte postcodes
    ws2 = wb.create_sheet('Verdachte postcodes')
    if len(pcs):
        table(ws2, pcs)
    else:
        ws2['A1'] = 'Geen verdachte postcodes gevonden'
    for j in range(1, 6):
        ws2.column_dimensions[get_column_letter(j)].width = 22

    ws5 = wb.create_sheet('Routeoverzicht')
    table(ws5, overzicht)
    for j, c in enumerate(overzicht.columns, 1):
        ws5.column_dimensions[get_column_letter(j)].width = {'Vaste volgorde': 70, 'Richting': 22}.get(c, 13)

    ws4 = wb.create_sheet('Alle ritten')
    table(ws4, alle)
    cols4 = list(alle.columns)
    e_col = cols4.index('Ernst') + 1
    for r in range(2, len(alle) + 2):
        v = ws4.cell(r, e_col).value
        if v:
            fill = hoog if v == 'Hoog' else contr
            for c in range(1, len(cols4) + 1):
                ws4.cell(r, c).fill = fill
    wd = {'Redenen': 70, 'Code': 24, 'Overige codes': 24, 'Optimale volgorde': 55, PC_V: 34, DAT: 11, 'Richting': 20}
    for j, c in enumerate(cols4, 1):
        ws4.column_dimensions[get_column_letter(j)].width = wd.get(c, 13)
    ws4.freeze_panes = 'E2'

    # Samenvatting (formules op het tabblad Gemarkeerde ritten)
    ws3 = wb.create_sheet('Samenvatting', 0)
    ws3['A1'] = 'Specificatiecheck routes en kosten'; ws3['A1'].font = Font(name=F, bold=True, size=14)
    ws3['A2'] = f'Bron: {src}  ·  {len(df)} ritten  ·  {df[RNR].nunique()} routenummers'
    ws3['A2'].font = Font(name=F, size=10, italic=True)
    G = "'Gemarkeerde ritten'"
    codecol = get_column_letter(cols.index('Code') + 1)
    overcol = get_column_letter(cols.index('Overige codes') + 1)
    rows = [('Totaal ritten in bron', len(df), None),
            ('Totaal gefactureerd (na korting)', round(df[KOST].sum(), 2), '€ #,##0.00'),
            ('Gemarkeerde ritten – Hoog', f'=COUNTIF({G}!{ce}:{ce},"Hoog")', None),
            ('Gemarkeerde ritten – Controleren', f'=COUNTIF({G}!{ce}:{ce},"Controleren")', None),
            ('Gefactureerd bij ritten met ernst Hoog', f'=SUMIF({G}!{ce}:{ce},"Hoog",{G}!{ck}:{ck})', '€ #,##0.00'),
            ('Mogelijk te veel gefactureerd (waar te schatten)', f'=SUM({G}!{get_column_letter(len(cols)+2)}:{get_column_letter(len(cols)+2)})', '€ #,##0.00')]
    r = 4
    for lab, val, fmt in rows:
        ws3.cell(r, 1, lab).font = Font(name=F); c = ws3.cell(r, 2, val); c.font = Font(name=F, bold=True)
        if fmt: c.number_format = fmt
        r += 1
    r += 1
    ws3.cell(r, 1, 'Ritten per controle').font = Font(name=F, bold=True); r += 1
    uitleg = {
        'BEDRAG_KLOPT_NIET': f'Gefactureerd bedrag ≠ BS-{EENHEID} × tarief + vast deel (vaste kosten per rit, instap-/aanrijtijd, korting)',
        'AFSTAND_FOUT_BS': f'{"Afstand" if EENHEID == "km" else "Rittijd"} in BS klopt niet: rit > {MAX_KM} {EENHEID}, BS-{EENHEID} veel hoger dan '
                           f'verwacht op basis van de weg-km van dezelfde volgorde, verdachte postcode'
                           + (' of onlogische snelheid' if EENHEID == 'km' else ''),
        'LANGER_DAN_NORMAAL': f'Rit >{VAST_KM} {EENHEID} en >{VAST_PCT:.0%} langer dan een rit van dezelfde route en richting met dezelfde of '
                              'méér stops (of, bij een routenummer dat <3× rijdt, veel langer dan vergelijkbare ritten)',
        'VOLGORDE_NIET_OPTIMAAL': f'Een andere volgorde van dezelfde stops is ≥{OPT_KM} km en ≥{OPT_PCT:.0%} korter over de weg '
                                  "('s ochtends mag elk thuisadres het eerste zijn, 's middags het laatste)",
        'POSTCODE_DUBBEL': 'Zelfde postcode wordt twee keer, niet direct na elkaar, aangedaan',
        'GEGEVENS_FOUT': 'Dubbele rit, ongeldige postcode, minder stops dan passagiers of postcode niet te vinden'}
    for h, j in (('Code', 1), ('Als hoofdcode', 2), ('Totaal ritten', 3), ('Uitleg', 4)):
        ws3.cell(r, j, h).font = Font(name=F, bold=True, color='FFFFFF'); ws3.cell(r, j).fill = hdr_fill
    r += 1
    for code, txt in uitleg.items():
        ws3.cell(r, 1, code).font = Font(name=F)
        ws3.cell(r, 2, f'=COUNTIF({G}!{codecol}:{codecol},"{code}")').font = Font(name=F)
        ws3.cell(r, 3, f'={get_column_letter(2)}{r}+COUNTIF({G}!{overcol}:{overcol},"*{code}*")').font = Font(name=F)
        ws3.cell(r, 4, txt).font = Font(name=F, size=10)
        r += 1
    r += 1
    notes = ['Toelichting',
             (f'Afrekening op {"kilometers" if EENHEID == "km" else "minuten (beladen reistijd × uurtarief)"}. '
              f'De kolom "{KM}" komt uit BS, niet uit EasyTravel (ondanks de naam).'),
             'Het contract met de gemeente gaat uit van EasyTravel. Deze check vergelijkt BS met afstanden/rijtijden via OpenStreetMap '
             '(indicatie, onafhankelijk van BS en EasyTravel); voor de contractuele toets BS naast EasyTravel leggen.',
             f'Gefactureerd bedrag = BS-{EENHEID} × tarief + vast deel (vaste kosten per rit' + (', uurtarief' if EENHEID == 'km' else ', instap- en aanrijtijd') + ', − korting).',
             f'"{VERW}" is een schatting: bij AFSTAND_FOUT_BS = wegwaarde via OpenStreetMap (gecorrigeerd voor het gemiddelde verschil met BS); '
             f'bij VOLGORDE_NIET_OPTIMAAL = BS min de besparing; bij LANGER_DAN_NORMAAL = waarde van de vergelijkbare kortere rit.',
             'Code = belangrijkste bevinding per rit; Overige codes = andere bevindingen bij dezelfde rit; Redenen = details per bevinding.',
             'Routenummer = route (4 cijfers) + weekdag (1=ma … 5=vr) + richting (0=ochtend naar school, 1=middag naar huis). '
             'Vaste stops = postcodes die in minstens de helft van de ritten van dat routenummer voorkomen.',
             'Tabblad "Alle ritten" bevat alle ritten uit de bron met alle originele kolommen; gemarkeerde ritten zijn gekleurd (filter op Ernst of Code).',
             ('Wegafstanden: postcode-middelpunt uit PDOK Locatieserver, routes via OpenStreetMap (OSRM). Optimale volgorde: '
              "alleen de school ligt vast ('s ochtends eindpunt, 's middags beginpunt); ochtend eerst alle thuisadressen dan scholen, middag eerst scholen dan thuisadressen (geen tijdvensters)."
              if alle is not None else
              'Zonder coördinaten per postcode is de route niet geografisch nagerekend; de controles vergelijken ritten onderling.')]
    for t in notes:
        ws3.cell(r, 1, t).font = Font(name=F, bold=(t == 'Toelichting'), size=10); r += 1
    ws3.column_dimensions['A'].width = 48; ws3.column_dimensions['B'].width = 16; ws3.column_dimensions['C'].width = 16; ws3.column_dimensions['D'].width = 95
    wb.save(dst)


def sequenties(src):
    """Postcodereeksen per rit (voor het ophalen van ontbrekende afstanden)."""
    d0 = load(src)
    seqs = [[r[PC_O]] + [x.strip() for x in str(r[PC_V]).split(',') if x.strip() and str(r[PC_V]) != 'nan'] + [r[PC_E]]
            for _, r in d0.iterrows()]
    return seqs
