"""Curated IP blocklist data. Ported from FactoryHQ/tools/blocklist.py.

Expand over time as we see real rejections from Etsy / Printify / TM hits.
This is the cheap first-pass — catches obvious named characters, brands,
celebrities, and lyric fragments before paying for a USPTO round-trip.
"""

CHARACTERS_BRANDS: set[str] = {
    # Disney / Pixar
    "mickey", "minnie", "donald duck", "goofy", "elsa", "anna", "olaf",
    "stitch", "lilo", "moana", "ariel", "belle", "rapunzel", "buzz lightyear",
    "woody", "nemo", "dory", "wall-e", "bambi", "simba", "mufasa",
    # Sanrio
    "hello kitty", "kuromi", "my melody", "cinnamoroll", "pompompurin",
    # Nintendo / Pokemon
    "mario", "luigi", "yoshi", "bowser", "princess peach", "zelda", "link",
    "pikachu", "charizard", "eevee", "pokemon", "pokeball",
    # Marvel / DC
    "spider-man", "spiderman", "iron man", "captain america", "thor",
    "hulk", "black widow", "deadpool", "wolverine", "batman", "superman",
    "wonder woman", "joker", "harley quinn",
    # Star Wars
    "darth vader", "yoda", "baby yoda", "grogu", "mandalorian", "stormtrooper",
    "skywalker", "jedi", "sith",
    # Harry Potter
    "harry potter", "hogwarts", "gryffindor", "slytherin", "hufflepuff",
    "ravenclaw", "voldemort", "hermione", "dumbledore",
    # Other franchises
    "bluey", "bingo", "peppa pig", "paw patrol", "sesame street", "elmo",
    "minion", "minions", "shrek", "frozen",
    # Sports leagues / teams (any league name = strike risk)
    "nfl", "nba", "mlb", "nhl", "ncaa", "fifa", "olympics",
    # Generic brand traps
    "nike", "adidas", "supreme", "gucci", "louis vuitton", "chanel",
    "stanley cup", "yeti", "starbucks", "coca-cola", "pepsi",
}

PUBLIC_FIGURES: set[str] = {
    "taylor swift", "swiftie", "beyonce", "rihanna", "kanye", "drake",
    "trump", "biden", "obama", "elon musk", "kardashian",
    "michael jackson", "elvis", "prince",  # estates are aggressive
    "audrey hepburn", "marilyn monroe", "frida kahlo",
    "mlk", "martin luther king",
}

# Soft signal — flag for human review even though TM check won't catch lyrics
LYRIC_FRAGMENTS: set[str] = {
    "shake it off", "bad blood", "anti-hero",
    "single ladies", "drivers license",
}

# N-gram + fuzzy match tunables (TM check, not blocklist)
NGRAM_MIN_WORDS = 3
NGRAM_MAX_WORDS = 6
NGRAM_MIN_CHARS = 8
FUZZY_THRESHOLD = 92  # 0-100, rapidfuzz ratio

# Stopwords that should never trigger a TM hit by themselves
STOPWORDS: set[str] = {
    "the", "and", "for", "you", "are", "but", "not", "with", "from", "they",
    "this", "that", "have", "has", "had", "was", "were", "been", "being",
    "all", "any", "some", "what", "when", "where", "which", "who", "why",
    "how", "your", "our", "their", "his", "her", "its", "them", "him",
    "she", "we", "us", "i", "me", "my", "mine", "myself",
    "ive", "youre", "youve", "dont", "wont", "cant", "isnt", "aint",
    "will", "would", "should", "could", "can", "may", "might", "must",
    "do", "does", "did", "is", "am", "be", "to", "of", "in", "on", "at",
    "by", "as", "an", "a", "or", "if", "so", "no", "yes", "up", "out",
    "off", "now", "then", "than", "too", "very", "just", "only", "more",
    "less", "most", "least", "much", "many", "few", "lot", "lots",
}
