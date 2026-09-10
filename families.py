#!/usr/bin/env python3
"""
Which family each RAA class belongs to.

This table does double duty, and that is the point: it is BOTH the unit the
tile exporter thins by and the unit the frontend filters by. Those two have to
be the same thing.

If they differ, filtering leaves holes. Thinning decides which features reach
a tile at a given zoom; the frontend then hides some of them. If a family was
thinned as one bucket but the filter cuts it in half, the survivors are still
spread over the whole bucket's grid and the map keeps the gaps. Thinned per
family and filtered per family, every selection is a union of independently
well-distributed sets, and MapLibre's collision engine picks the best that fit.

`build_tiles.py` asserts that every class it exports appears here, so adding a
class to the pipeline without giving it a family fails loudly instead of
silently landing in a bucket it does not belong to.
"""

# Family display names used to live here and ship inside the generated
# filterFamilies.ts. They do not any more: the export carries only the id, and
# each frontend owns its own wording (the app in sv.json, the web demo in
# familyLabels.ts). Shipping the string made the pipeline the owner of UI copy
# in a single language, so the app could not be translated without
# regenerating data.

# One icon per family for the filter list, picked from the map set. Chosen for
# legibility at ~22 px rather than for being the most numerous class: `bridge`
# beats `road` because a hollow way is a brown smear that small, and `castle`
# beats `hillfort` because two towers read instantly where a ramparted hill
# does not. Every value must be a glyph name in the icon set.
FAMILY_ICON = {
    "graves": "burial-mound",
    "rockart": "runestone",
    "forts": "castle",
    "religious": "church",
    "settlement": "settlement",
    "farming": "fossil-field",
    "industry": "furnace",
    "transport": "bridge",
    "maritime": "lighthouse",
    "hunting": "pitfall-trap",
    "misc": "unknown",
}

# Display order for the filter list: broadly most-visited first.
FAMILY_ORDER = ['graves', 'rockart', 'forts', 'religious', 'settlement', 'farming', 'industry', 'transport', 'maritime', 'hunting', 'misc']

FAMILY = {
    # Graves & burial grounds
    'Begravningsplats': 'graves',
    'Begravningsplats enstaka': 'graves',
    'Flatmarksgrav': 'graves',
    'Grav - uppgift om typ saknas': 'graves',
    'Grav markerad av sten/block': 'graves',
    'Grav övrig': 'graves',
    'Grav- och boplatsområde': 'graves',
    'Gravfält': 'graves',
    'Gravhägnad': 'graves',
    'Gravklot': 'graves',
    'Gravvård': 'graves',
    'Hög': 'graves',
    'Järnåldersdös': 'graves',
    'Labyrint': 'graves',
    'Minnesmärke': 'graves',
    'Röse': 'graves',
    'Skärvstenshög': 'graves',
    'Stenkammargrav': 'graves',
    'Stenkistgrav': 'graves',
    'Stenkrets/stenrad': 'graves',
    'Stenring': 'graves',
    'Stensättning': 'graves',

    # Rune stones & rock art
    'Bildristning': 'rockart',
    'Hällmålning': 'rockart',
    'Hällristning': 'rockart',
    'Kompassros/väderstreckspil': 'rockart',
    'Ristning, medeltid/historisk tid': 'rockart',
    'Runristning': 'rockart',

    # Forts & castles
    'Borg': 'forts',
    'Fornborg': 'forts',
    'Fästning/skans': 'forts',
    'Luftfarkost': 'forts',
    'Militär anläggning övrig': 'forts',
    'Militär mötesplats': 'forts',
    'Område med militära anläggningar': 'forts',
    'Slagfält': 'forts',
    'Slott/herresäte': 'forts',
    'Spärranordning': 'forts',
    'Stadsbefästning': 'forts',
    'Stadsvall/stadsmur': 'forts',
    'Stridsvärn': 'forts',
    'Vallanläggning': 'forts',

    # Churches & sacred places
    'Avrättningsplats': 'religious',
    'Brunn/kallkälla': 'religious',
    'Kloster': 'religious',
    'Kyrka/kapell': 'religious',
    'Källa med tradition': 'religious',
    'Naturföremål/-bildning med bruk, tradition eller namn': 'religious',
    'Offerkast': 'religious',
    'Offerplats': 'religious',
    'Plats med tradition': 'religious',
    'Samlingsplats': 'religious',

    # Settlements & dwellings
    'Bengömma': 'settlement',
    'Boplats': 'settlement',
    'Boplatsgrop': 'settlement',
    'Boplatslämning övrig': 'settlement',
    'Boplatsområde': 'settlement',
    'Boplatsvall': 'settlement',
    'Bytomt/gårdstomt': 'settlement',
    'Fäbod': 'settlement',
    'Förvaringsanläggning': 'settlement',
    'Gistgård': 'settlement',
    'Husgrund, förhistorisk/medeltida': 'settlement',
    'Husgrund, historisk tid': 'settlement',
    'Hägnad': 'settlement',
    'Hägnadssystem': 'settlement',
    'Härd': 'settlement',
    'Kokgrop': 'settlement',
    'Kyrkstad': 'settlement',
    'Kåta': 'settlement',
    'Lägenhetsbebyggelse': 'settlement',
    'Park-/trädgårdsanläggning': 'settlement',
    'Rengärda': 'settlement',
    'Renvall': 'settlement',
    'Skåre/jaktvärn': 'settlement',
    'Stadslager': 'settlement',
    'Stalotomt': 'settlement',
    'Tomtning': 'settlement',
    'Viste': 'settlement',

    # Farming & earthworks
    'Dammvall': 'farming',
    'Dike/ränna': 'farming',
    'Fossil åker': 'farming',
    'Område med fossil åkermark': 'farming',
    'Område med skogsbrukslämningar': 'farming',
    'Röjningsröse': 'farming',
    'Stenröjd yta': 'farming',
    'Terrassering': 'farming',

    # Mining, iron & industry
    'Bergshistorisk lämning övrig': 'industry',
    'Blästbrukslämning': 'industry',
    'Blästplats': 'industry',
    'Brott/täkt': 'industry',
    'Brytningsyta': 'industry',
    'Flintgruva': 'industry',
    'Flottningsanläggning': 'industry',
    'Gjuteri': 'industry',
    'Glasindustri': 'industry',
    'Gruvhål': 'industry',
    'Gruvområde': 'industry',
    'Hammare/smedja': 'industry',
    'Hammarområde': 'industry',
    'Hytt- och hammarområde': 'industry',
    'Hyttlämning': 'industry',
    'Hyttområde': 'industry',
    'Industri övrig': 'industry',
    'Kalkugn': 'industry',
    'Kemisk industri': 'industry',
    'Kolningsanläggning': 'industry',
    'Kvarn': 'industry',
    'Livsmedelsindustri': 'industry',
    'Metallindustri/järnbruk': 'industry',
    'Område med flottningsanläggningar': 'industry',
    'Pappersindustri': 'industry',
    'Smideslämning': 'industry',
    'Smidesområde': 'industry',
    'Småindustriområde': 'industry',
    'Stenindustri': 'industry',
    'Stenugn': 'industry',
    'Tegelindustri': 'industry',
    'Textilindustri': 'industry',
    'Träindustri': 'industry',
    'Uppfordringsanläggning': 'industry',

    # Roads, bridges & boundaries
    'Bro': 'transport',
    'Färdväg': 'transport',
    'Färdvägssystem': 'transport',
    'Gränsbestämt område': 'transport',
    'Gränsmärke': 'transport',
    'Kanal': 'transport',
    'Rösning': 'transport',
    'Vad': 'transport',
    'Vägmärke': 'transport',

    # Coast & seafaring
    'Ballastplats': 'maritime',
    'Båtlänning': 'maritime',
    'Drag': 'maritime',
    'Fartygs-/båtlämning': 'maritime',
    'Fiskeläge': 'maritime',
    'Fyr': 'maritime',
    'Förtöjningsanordning': 'maritime',
    'Hamnanläggning': 'maritime',
    'Hamnområde': 'maritime',
    'Kanalmärke': 'maritime',
    'Område med fartygslämningar': 'maritime',
    'Sjömärke': 'maritime',
    'Varv/slip': 'maritime',
    'Vårdkase': 'maritime',

    # Hunting traps
    'Fångstanläggning övrig': 'hunting',
    'Fångstgrop': 'hunting',
    'Fångstgropssystem': 'hunting',
    'Fångstgård': 'hunting',

    # Other & uncertain
    'Fornlämningsliknande bildning': 'misc',
    'Fornlämningsliknande lämning': 'misc',
    'Fyndplats': 'misc',
    'Hornsamling': 'misc',
    'Övrigt': 'misc',
}
