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


# --------------------------------------------------------------------------- #
# Exclusions
#
# These live here, with the rest of the class taxonomy, because two separate
# stages need them: build_signals decides which clusters are excluded, and
# build_clusters has to avoid LABELLING a cluster with an excluded class when
# it has a better member. They used to live only in build_signals, which is
# stage 4 -- so stage 2 could not see them, and 1,042 clusters ended up wearing
# the name and icon of the one thing in them nobody would travel for.
# --------------------------------------------------------------------------- #

# Classes with no visible surface expression worth travelling for. Derived from
# per-class notability AND photograph lift, both near zero for these.
CLASS_BLACKLIST = {
    "Kolningsanläggning", "Härd", "Fångstgrop", "Fångstgropssystem",
    # The rest of the hunting family, so the family goes rather than half of
    # it. Two of its four classes were already excluded, which left the family
    # at 2 clusters out of a 10,000 export: a filter row that can only ever
    # offer you two pins, next to a glyph for a kind of site that is a shallow
    # depression in a forest floor and invisible without a sign. A family with
    # no members is not emitted at all, so the row goes with them.
    #
    # "Fangstanlaggning ovrig" (571) is the register's catch-all for trapping
    # works, so it is unspecific by definition, and "Fangstgard" (17) is a
    # timber funnel fence of which what survives is a line of postholes.
    "Fångstanläggning övrig", "Fångstgård",
    "Kokgrop", "Boplatsgrop", "Boplats", "Boplatslämning övrig",
    "Boplatsvall", "Skärvstenshög", "Fossil åker",
    "Område med fossil åkermark", "Kemisk industri", "Förvaringsanläggning",
    "Område med skogsbrukslämningar",
    # "Gränsbestämt område" WAS HERE and has moved to CLASS_NOT_A_PLACE: a
    # rescuable prior was the wrong shape for it. See below.
}
# "Fossil åker" above used to read "Fossil åkermark", which is not a class the
# register has: the two real names are "Fossil åker" (8,276 sites) and "Område
# med fossil åkermark" (4,140), and the entry matched neither. So the larger of
# the two was never excluded at all, and the list looked like it covered both.
#
# It cost almost nothing in the end -- the fitted model had already pushed
# Fossil åker down to 4 clusters in a 10,000 export on its own, which is why
# nobody noticed. The danger was the false confidence: a dead entry in a
# hand-curated list reads as a decision that has been made.
# Weak on its own (0.26x photograph lift) but 29.6% of the dataset and it does
# contain good sites. Excluded by default, rescued by any positive evidence.
CLASS_SOFT_BLACKLIST = {"Stensättning"}

# Classes where the ORDINARY RESCUE CONDITIONS MEASURE THE WRONG THING, so the
# only evidence that counts is the register saying something is above ground.
#
# A stadslager is the archaeological deposit under a town: the medieval layer
# beneath a modern street. By the register's own language 55 of the 107 in the
# export are pure excavation report -- "Kulturlager med sot, tegel och keramik
# har paatraeffats, och en kritpipa daterades till 1620-40" -- and 29 more say
# nothing either way. There is, by construction, nothing to walk to.
#
# The reason it needs its own rule rather than CLASS_BLACKLIST is that the
# usual rescues do not mean here what they mean everywhere else:
#
#   has_name  For most classes a folk name is somebody having known and cared
#             about the monument -- Galgbacken, Varggropen, Drakaroer. For a
#             stadslager the named thing is THE TOWN: Trelleborg, Varberg,
#             Landskrona, Askersund, "AEngelholms medeltida stad". All 22 of
#             them, and a town's name says nothing about whether there is
#             anything to see in the ground beneath it.
#   proximity Removed for everybody (see build_scores), and this class is
#             where it was worst: 45% within 500 m of a county board sign
#             against a 5.4% baseline, because a stadslager IS a town centre
#             and a town centre is where the signs are.
#
# `any_visible` is the register's own `placering = 'Synlig ovan mark'`, and it
# answers the actual question. On these 126 clusters it separates them 3 / 123,
# and the three are exactly the destinations: Sala gruvby (a mining village
# with over 200 building remains), Kungahaella/Klosterkullen (whose cluster
# also holds a Kloster and a Stadsvall/stadsmur) and Braette (a deserted
# town). The 22 town names are all not-visible.
#
# So: excluded unless the register says it shows above ground.
CLASS_BURIED = {"Stadslager"}

# Classes that are not monuments at all, excluded with NO rescue.
#
# This is the same kind of judgement as a record the register has struck out
# (see `struck` in build_scores) and not the same as a bad prior: it is not a
# place we expect to be dull, it is not a place. Everything else in this file
# is a prior that site-level evidence can overturn, and the argument for that
# is strong -- a veto never learns it was wrong, because the sites it hides
# never come back to argue. It does not apply here, because there is no
# version of this record that is a destination.
#
# "Gränsbestämt område" is a legal boundary. 118 records whose entire
# description is administrative -- "Gränslinjebestämt område. Ingående RAÄ-nr
# 81 i Fjärås sn." -- and what they delimit is a monument that already has its
# own record and its own pin. At Fjärås the boundary sits 180 m from
# Frodestenen's grave field and describes it in the language of a land survey.
# Measured: 70 of the 71 clusters have another monument within 500 m, so the
# pin is a duplicate of one that already exists. Franco tapped one of them
# expecting Li gravfält.
#
# It was in CLASS_BLACKLIST, and the rescue conditions do not work for it any
# better than they did for a stadslager. `has_name` fires on the name of the
# thing delimited -- "Sala silvergruva", "Nydala Kloster", "Ytterby gruva",
# all of which have their own records -- and `any_visible` is 1 for all 71,
# because what is visible above ground is the monument, not the boundary. So
# both of the conditions that could rescue it are describing something else.
#
# NOT "Gränsmärke" (1,149): a boundary MARKER is a real stone somebody put
# there, and some of them are worth walking to.
CLASS_NOT_A_PLACE = {"Gränsbestämt område"}


def representative_order(alias="s"):
    """The ORDER BY that picks a cluster's representative site, once.

    Returns (sql_fragment, params). Use it after `ORDER BY cluster_id,` and
    take the first row per cluster.

    This rule existed in FOUR places -- build_clusters.py, build_tiles.py,
    build_places.py and write_families() -- and the copies drifted.
    build_places.py had lost the "excluded classes lose first" clause, which
    meant that for 19,881 of 40,656 multi-site clusters `features.raa_url`
    pointed at a different member than the tile did. The visible symptom
    would have been the "Visa i Fornsök" button opening a monument other
    than the one the text describes.

    The three parts, in order:
      1. A blacklisted class loses. A grave field sharing an RAA number with
         two fossil-field records must not be represented by a fossil field
         -- that is how Blomsholms gravfält came to be called "Område med
         fossil åkermark" and got excluded out of existence.
      2. Longest description wins. It is the member somebody actually wrote
         about, so its text and its class agree with each other.
      3. uuid, purely to make the tie deterministic. Without it the same
         build can pick different members on different runs, and half of the
         19,881 divergences above were nothing but this.
    """
    holes = ",".join("?" * len(CLASS_BLACKLIST))
    return (
        f"CASE WHEN {alias}.class_sv IN ({holes}) THEN 1 ELSE 0 END, "
        f"{alias}.description_len DESC, {alias}.uuid",
        tuple(CLASS_BLACKLIST),
    )
