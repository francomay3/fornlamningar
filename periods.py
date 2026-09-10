#!/usr/bin/env python3
"""
Typological dating by class. NEEDS REVIEW -- see the warning below.

K-samsok's lamning records carry no dating field at all. I dumped every key in
`@graph` across 300 responses: there is no `datering`, no period, no fromTime.
And the free text mentions a period in fewer than 4% of entries:

    medeltid    975    jarnalder   738    forhistorisk  532
    bronsalder  343    vikingatid  277    stenalder     246

    ~3,700 of 103,977 eligible places.

So age cannot be derived from the register. But the class implies it: a
ganggrift is Neolithic, a rose is Bronze Age, a fornborg is Iron Age. That is
ordinary typological dating, and putting it in a table makes it reviewable,
citable and identical for every place of the same kind -- none of which is
true if a language model infers it per place. This is the one part of a pin
that does NOT come from the register, so it is the one part that must not be
guessed at generation time.

FRANCO: check these. They are standard Swedish archaeological ranges as I
understand them, but I am not an archaeologist and roughly 80 classes is a lot
of surface area to be wrong on. Anything you are unsure of, delete the row --
a place with no period shown is fine, a place with a wrong one is not.

Classes are deliberately ABSENT where the honest answer spans everything.
"Fardvag" covers cart tracks from the Bronze Age to the 1900s; printing
"prehistoric to modern" costs a line of the popup and tells a reader nothing.
Silence is the better default.

`basis` distinguishes what we know from what we infer, so the frontend can
word it differently: "usually Iron Age" for typology, and the period as stated
when the register actually says it.
"""

# class -> (swedish label, english label)
PERIOD = {
    # graves -- the best-dated group
    "Hög": ("vanligen järnålder", "usually Iron Age"),
    "Gravfält": ("vanligen järnålder", "usually Iron Age"),
    "Röse": ("vanligen bronsålder", "usually Bronze Age"),
    "Skärvstenshög": ("bronsålder", "Bronze Age"),
    "Stensättning": ("bronsålder eller järnålder", "Bronze or Iron Age"),
    "Grav markerad av sten/block": ("bronsålder eller järnålder",
                                    "Bronze or Iron Age"),
    "Flatmarksgrav": ("järnålder", "Iron Age"),
    "Stenkammargrav": ("stenålder", "Stone Age"),
    "Stenkistgrav": ("stenålder eller bronsålder", "Stone or Bronze Age"),
    "Järnåldersdös": ("järnålder", "Iron Age"),
    "Gravklot": ("järnålder", "Iron Age"),
    "Stenkrets/stenrad": ("järnålder", "Iron Age"),
    "Stenring": ("järnålder", "Iron Age"),
    "Grav- och boplatsområde": ("bronsålder eller järnålder",
                                "Bronze or Iron Age"),

    # rock art and runes
    "Hällristning": ("bronsålder", "Bronze Age"),
    "Bildristning": ("bronsålder", "Bronze Age"),
    "Hällmålning": ("stenålder eller bronsålder", "Stone or Bronze Age"),
    "Runristning": ("vikingatid eller tidig medeltid",
                    "Viking Age or early Middle Ages"),
    "Ristning, medeltid/historisk tid": ("medeltid eller senare",
                                         "medieval or later"),

    # fortifications
    "Fornborg": ("vanligen järnålder", "usually Iron Age"),
    "Borg": ("medeltid", "Middle Ages"),
    "Slott/herresäte": ("medeltid eller senare", "medieval or later"),
    "Fästning/skans": ("medeltid eller senare", "medieval or later"),
    "Stadsbefästning": ("medeltid eller senare", "medieval or later"),
    "Stadsvall/stadsmur": ("medeltid eller senare", "medieval or later"),
    "Stadslager": ("medeltid eller senare", "medieval or later"),

    # religious and commemorative
    "Kyrka/kapell": ("medeltid eller senare", "medieval or later"),
    "Kloster": ("medeltid", "Middle Ages"),
    "Begravningsplats": ("historisk tid", "historic period"),
    "Begravningsplats enstaka": ("historisk tid", "historic period"),
    "Minnesmärke": ("nyare tid", "modern period"),
    "Labyrint": ("historisk tid", "historic period"),
    "Avrättningsplats": ("historisk tid", "historic period"),

    # settlement
    "Boplats": ("stenålder till järnålder", "Stone Age to Iron Age"),
    "Boplatsområde": ("stenålder till järnålder", "Stone Age to Iron Age"),
    "Boplatsgrop": ("stenålder till järnålder", "Stone Age to Iron Age"),
    "Härd": ("förhistorisk", "prehistoric"),
    "Kokgrop": ("förhistorisk", "prehistoric"),
    "Husgrund, förhistorisk/medeltida": ("förhistorisk eller medeltid",
                                         "prehistoric or medieval"),
    "Husgrund, historisk tid": ("historisk tid", "historic period"),
    "Lägenhetsbebyggelse": ("järnålder", "Iron Age"),
    "Bytomt/gårdstomt": ("medeltid eller senare", "medieval or later"),
    "Kyrkstad": ("historisk tid", "historic period"),
    "Fäbod": ("historisk tid", "historic period"),
    "Tomtning": ("medeltid eller senare", "medieval or later"),

    # iron, mining, industry
    "Blästplats": ("järnålder eller medeltid", "Iron Age or Middle Ages"),
    "Blästbrukslämning": ("järnålder eller medeltid",
                          "Iron Age or Middle Ages"),
    "Hyttområde": ("medeltid eller senare", "medieval or later"),
    "Hyttlämning": ("medeltid eller senare", "medieval or later"),
    "Hytt- och hammarområde": ("medeltid eller senare", "medieval or later"),
    "Metallindustri/järnbruk": ("historisk tid", "historic period"),
    "Hammare/smedja": ("historisk tid", "historic period"),
    "Hammarområde": ("historisk tid", "historic period"),
    "Kolningsanläggning": ("historisk tid", "historic period"),
    "Kalkugn": ("historisk tid", "historic period"),
    "Tegelindustri": ("historisk tid", "historic period"),
    "Glasindustri": ("historisk tid", "historic period"),
    "Pappersindustri": ("nyare tid", "modern period"),
    "Livsmedelsindustri": ("nyare tid", "modern period"),
    "Textilindustri": ("nyare tid", "modern period"),
    "Kvarn": ("historisk tid", "historic period"),

    # maritime and navigation
    "Fyr": ("nyare tid", "modern period"),
    "Vårdkase": ("historisk tid", "historic period"),
    "Fiskeläge": ("historisk tid", "historic period"),

    # farming
    "Fossil åker": ("bronsålder till historisk tid",
                    "Bronze Age to historic period"),
    "Område med fossil åkermark": ("bronsålder till historisk tid",
                                   "Bronze Age to historic period"),
    "Röjningsröse": ("järnålder eller senare", "Iron Age or later"),
    "Terrassering": ("järnålder eller senare", "Iron Age or later"),

    # deliberately omitted, because the honest range is "anything":
    #   Färdväg, Färdvägssystem, Bro, Vad, Kanal, Vägmärke, Gränsmärke,
    #   Fångstgrop, Fångstgropssystem, Hägnad, Dike/ränna, Dammvall,
    #   Naturföremål..., Källa med tradition, Plats med tradition, Övrigt,
    #   Fornlämningsliknande*, Fyndplats, and the Sami classes, whose dating
    #   is genuinely contested and not something to assert in a popup.
}

# Period words as they appear in the register's own free text. When the entry
# states a period, that beats the typology -- it is evidence about THIS place
# rather than about its class.
STATED = [
    ("romersk järnålder", "romersk järnålder", "Roman Iron Age"),
    ("folkvandringstid", "folkvandringstid", "Migration Period"),
    ("vendeltid", "vendeltid", "Vendel Period"),
    ("vikingatid", "vikingatid", "Viking Age"),
    ("bronsålder", "bronsålder", "Bronze Age"),
    ("stenålder", "stenålder", "Stone Age"),
    ("järnålder", "järnålder", "Iron Age"),
    ("medeltid", "medeltid", "Middle Ages"),
    ("nyare tid", "nyare tid", "modern period"),
    ("förhistorisk", "förhistorisk tid", "prehistoric"),
]


def period_for(class_sv, description):
    """(swedish, english, basis) or None.

    basis is 'stated' when the register's own text names a period and
    'typology' when it comes from the class alone. The frontend should word
    those differently; conflating them would present an inference as a
    finding.
    """
    text = (description or "").lower()
    for needle, sv, en in STATED:
        if needle in text:
            return sv, en, "stated"
    got = PERIOD.get(class_sv)
    if got:
        return got[0], got[1], "typology"
    return None
