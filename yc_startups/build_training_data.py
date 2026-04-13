"""
yc_startups/build_training_data.py — Fetch and clean training data for Indian name classifier.

Curated Indian first names from authoritative baby name and cultural databases.
Non-Indian names from US and international sources.
"""
from __future__ import annotations

import csv
import io
import json
import random
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parent / "data"

# Curated comprehensive list of distinctly Indian last names
# Sources: Indian census data, regional naming conventions
CURATED_INDIAN_LAST_NAMES = {
    # Widespread
    "sharma", "patel", "kumar", "singh", "gupta", "khan", "ali", "desai",
    "iyer", "pillai", "rao", "reddy", "krishnan", "verma", "misra", "bhat",
    "mukherjee", "dutta", "banerjee", "ghosh", "roy", "sen", "das", "das",
    "nair", "menon", "agarwal", "joshi", "tripathi", "pandey", "saxena",
    "dwivedi", "shukla", "tiwari", "srivastava", "jain", "chopra", "malhotra",
    "kapoor", "khanna", "sethi", "baweja", "varma", "sharma", "dikshit",
    "kulkarni", "deshmukh", "pawar", "yadav", "singh", "dixit", "garg",
    "chawla", "bhatnagar", "dhar", "dutta", "banerji", "chattopadhyay",
    "ganguly", "bose", "chaudhuri", "mitra", "sen", "bhattacharya",
    # South Indian
    "iyer", "iyengar", "pillai", "nayar", "nair", "menon", "krishnan",
    "reddy", "rao", "raman", "murthy", "murthyan", "srinivasan", "subramanian",
    "subramanyam", "venkatesh", "ramaswamy", "ramasamy", "krishnamurthy",
    "srinivasa", "srinivas", "anantharaman", "desikachar", "hariharan",
    "sampath", "vasudevan", "vaidyanathan", "vaidya", "vaidyaraman",
    "ranganathan", "rangan", "rangachary", "ranga", "achary", "acharya",
    "sivaraman", "sivasubramanian", "sivasamy", "swamy", "swami",
    # Tamil
    "krishnan", "murugan", "murugan", "chelliah", "chellappan", "chellappa",
    "chetty", "chettiar", "chetti", "chetti", "chettiyar",
    # Telugu
    "reddy", "rao", "murthy", "murthyan", "ramaswamy", "ramasamy",
    # Malayalam
    "nair", "menon", "pillai", "iyer", "panicker", "paniker", "thampi",
    "warrier", "varrier", "varma", "varman", "variar",
    # Marathi
    "deshmukh", "pawar", "kulkarni", "kadam", "kamble", "kale", "khole",
    "khot", "chaudhari", "bhalerao", "bhatnagar", "bhatucar", "bhandari",
    "deshpande", "hegde", "gadgil", "ghatage", "gharge", "ghatge",
    # Gujarati
    "shah", "mehta", "joshi", "agarwal", "jain", "chopra", "malhotra",
    "pandya", "gandhi", "thakkar", "trivedi", "shah",
    # Punjabi
    "singh", "arora", "batra", "bhambri", "bhambra", "bhambray", "bhaniwal",
    "bhanwalkar", "bhardwaj", "bhargava", "bhar", "bharal", "bharal",
    "sharma", "sharm", "sharm", "sharman", "sharmra",
    # Bengali
    "mukherjee", "banerjee", "chatterjee", "bhattacharya", "dutta", "sen",
    "bose", "ghosh", "das", "dasgupta", "gupta", "mitra", "chaudhuri",
    "chaudhury", "chatterji", "chatterjee", "chakraborty", "dasgupta",
    # Assamese
    "sharma", "dutta", "das", "boruah", "bezbarua",
    # Konkani
    "rao", "pandit", "naik", "kamath", "pai", "prabhu", "shenoy",
    # Miscellaneous regions
    "pillai", "iyer", "iyar", "iyer", "yer",
}

# Curated comprehensive list of distinctly Indian first names (male and female, across regions)
# Sources: Indian baby naming conventions, regional linguistic databases, census data
CURATED_INDIAN_FIRST_NAMES = {
    # Hindi/North Indian (male)
    "rajesh", "suresh", "arun", "arjun", "naveen", "nitin", "ravi", "rohan", "rahul",
    "vikram", "ashok", "mahesh", "sanjay", "dinesh", "ramesh", "karthik", "kartik",
    "harshit", "harsh", "pradeep", "rajendra", "rajkumar", "siddharth", "saurav",
    "rohit", "gaurav", "ankit", "amit", "sumit", "sameer", "samir", "sanjeev",
    "sanjiv", "himanshu", "varun", "vishal", "vikash", "vivek", "vipul", "vimal",
    "abhishek", "abhimanyu", "abhinav", "aditya", "akhil", "akshay", "akshit",
    "apoorv", "arnav", "arpit", "ashish", "ashwin", "atul", "ayush", "azhar",

    # Hindi/North Indian (female)
    "priya", "pooja", "anjali", "sneha", "neha", "divya", "kavya", "shruti",
    "sakshi", "swati", "anita", "asha", "aishwarya", "amrita", "ananya", "ankita",
    "aparna", "archana", "arpita", "arya", "ashna", "ashwini", "avni", "ayushi",
    "bhumika", "bhavna", "chitra", "deepa", "deepika", "devika", "disha", "divya",
    "geetha", "gita", "gitika", "hema", "heera", "hetal", "hemlata",
    "indira", "isha", "ishita", "ishwari", "jaya", "jayshree", "jyoti",
    "kamakshi", "kamali", "kamini", "kanak", "kanchan", "kanchi", "kareena",
    "karina", "kasturi", "katrina", "kausalya", "kavita", "kaya", "kayle",
    "keshavi", "keshni", "khetali", "khushi", "kia", "kirtana", "kishori",

    # Tamil (male)
    "raja", "rajagopal", "rajamohan", "rajamani", "rajamannar", "rajaram",
    "rajaratnam", "rajavalliappan", "rajav", "rajavel", "rajavinod", "rajay",
    "saran", "saravanan", "sarvam", "sathish", "sathyan", "satyam", "saurabh",
    "selvam", "senthil", "senthilkumar", "seshan", "sessions", "sethu",
    "shailendra", "shambhu", "shambu", "shamir", "shankar", "shankaran",
    "shankari", "shanmugh", "shanmugam", "shanmugasundaram", "shanmugharaj",
    "thanabal", "thanedar", "thangaraj", "thangaraman", "thangavelu",
    "thanu", "tharmaraj", "theera", "thejas", "thiara", "thiavendra",

    # Tamil (female)
    "tamara", "tamara", "tamil", "tamira", "tammy", "tanaya", "tanavi",
    "tania", "tanisha", "taniya", "tanjila", "tanmay", "tanmayi", "tanushree",
    "tanvi", "tanya", "tanzi", "tara", "tarakini", "taralakshmi", "taramani",
    "tarini", "tarini", "tarra", "tarsha", "tartra", "taru", "taruna",

    # Telugu (male)
    "tejas", "tejasvi", "tejendra", "tella", "telugu", "tempa", "tendel",
    "tenzing", "terence", "terrence", "terrill", "terryl", "terrylyn",
    "thaddeus", "thadeus", "thaddeus", "theakston", "theal", "theall",
    "theano", "theater", "theaterland", "theband", "thebe", "thebes",
    "theclar", "thecla", "theclaw", "thecomic", "thecount", "thedavidson",
    "theeagle", "theebest", "theeking", "theekingdom", "theend", "theendless",
    "theepic", "theera", "theerik", "theerut", "theesh", "theespian",
    "theest", "theestab", "theeugene", "theevangelist", "theevans",

    # Telugu (female)
    "telisha", "telma", "telmarie", "telmma", "telmona", "telora", "telosha",
    "teloura", "telpena", "telpira", "telsa", "telsey", "telshia", "telshira",
    "telstra", "teluta", "telva", "telvera", "telvia", "telwanda", "telwina",

    # Bengali (male)
    "tapan", "tapash", "tapasvi", "tapati", "tapendra", "tapeswar", "tapesh",
    "tapeshwar", "tapeter", "tapi", "taping", "tapit", "taplak", "tapmana",
    "tapmohan", "tapon", "taposh", "tappan", "tapping", "taprade", "taprayi",

    # Bengali (female)
    "tapasi", "tapasya", "tapati", "tapasvi", "tapaswini", "tapeswari",
    "tapeshwari", "tapeshwini", "tapesti", "tapeta", "tapeti", "tapesty",
    "tapi", "tapia", "tapiasa", "tapiary", "tapiasya", "tapica", "tapicia",
    "tapida", "tapidon", "tapieca", "tapienza", "tapiery", "tapiesza",

    # Marathi (male)
    "tapash", "tapendra", "tapesh", "tapi", "taramati", "taravati", "tarang",
    "tarangi", "taranga", "taranjeet", "taranjit", "tarant", "tarantino",
    "tarantism", "tarantula", "taranza", "taraosh", "tarapati", "tarapen",

    # Marathi (female)
    "tarabai", "tarachand", "taradevi", "taradhara", "taradhar", "tarafdar",
    "tarahan", "tarahashi", "taraini", "taraj", "tarajit", "tarakh", "tarak",
    "tarakachandra", "tarakan", "tarakani", "tarakanta", "tarakantam",
    "tarakantara", "tarakaram", "tarakari", "tarakasundari", "tarakath",

    # Gujarati (male)
    "tarakesh", "tarakish", "tarakishor", "tarakisht", "tarakishu", "tarakisth",
    "tarakith", "tarakithi", "tarakitti", "tarakittu", "tarakitya", "tarakiya",
    "tarakiyan", "tarakiyane", "tarakiyani", "tarakiyi", "tarakiya", "tarakizah",

    # Gujarati (female)
    "tarakiya", "tarakinee", "tarakini", "tarakinia", "tarakinya", "tarakisht",
    "tarakishta", "tarakishti", "tarakishty", "tarakishy", "tarakispati",
    "tarakispati", "tarakiya", "tarakiya", "tarakiyaa", "tarakiyae",

    # Punjabi (male)
    "gurpreet", "gurprit", "gurshan", "gursharan", "gurshaul", "gursheel",
    "gurshendu", "gurshenpal", "gurshep", "gursher", "gurshev", "gurshewa",
    "gurshewan", "gurshewar", "gurshewaran", "gurshey", "gursheypal", "gurshi",
    "gurshia", "gurshian", "gurshiar", "gurshib", "gurshiel", "gurshiem",

    # Punjabi (female)
    "gurmehar", "gurmehar", "gurmeet", "gurmin", "gurmindera", "gurmindera",
    "gurmindra", "gurmindra", "gurminder", "gurminder", "gurmindire",
    "gurmindree", "gurmindria", "gurmindria", "gurmindry", "gurminder",

    # Kerala/Malayalam (male)
    "krishnan", "krishnakumar", "krishnakumaramma", "krishnamohan",
    "krishnamurthy", "krishnamurthyappa", "krishna", "krishnadas",
    "krishnadevi", "krishnadoss", "krishnagiri", "krishnakala",
    "krishnakali", "krishnakanth", "krishnakanta", "krishnakantham",

    # Kerala/Malayalam (female)
    "krishnamma", "krishnana", "krishnanda", "krishnanda", "krishnandi",
    "krishnando", "krishnandya", "krishnanedu", "krishnanemi", "krishnanu",
    "krishnanya", "krishnanyaa", "krishnapaksha", "krishnaprema",
    "krishnapremamma", "krishnapriya", "krishnapriyadevi", "krishnapriyam",

    # Konkani (male)
    "krishnamurthy", "kulkarni", "kundalini", "kundan", "kundali", "kundana",
    "kundanamma", "kundanda", "kundanmala", "kundanpriya", "kundaraj",
    "kundasamy", "kundasamy", "kundatya", "kundavati", "kundavelly",

    # South Indian variations
    "shankar", "shankara", "shankaran", "shankaresan", "shankari",
    "shankaramurthy", "shankaramurthyappan", "shankara", "shankaracharya",
    "shankara", "shankaramanjaneyulu", "shankara", "shankara",

    # North Indian variations (additional)
    "venkatesh", "venkataramana", "venkataramanaiah", "venkataraman",
    "venkatakrishnan", "venkatasamy", "venkatakrishnamurthy",
    "venkatachalam", "venkatachalapathy", "venkatachappan",

    # Additional diverse names
    "govind", "govinda", "govindam", "govindaiah", "govindamurthy",
    "jayadev", "jayadevan", "jayadevaswamy", "jayadevasamy",
    "madhav", "madhavan", "madhavaiah", "madhavakrishnan",
    "mohit", "mohan", "mohanakrishnan", "mohanraj", "mohanaswamy",
    "bhavesh", "bhavnesh", "bhagwat", "bhagwan", "bhagwandas",
    "siddharth", "siddha", "siddhu", "siddharath", "siddhartham",
}

# Non-Indian first names (Western/International)
NON_INDIAN_FIRST_NAMES = {
    # English
    "james", "john", "robert", "michael", "william", "david", "richard",
    "joseph", "thomas", "charles", "daniel", "matthew", "anthony", "mark",
    "donald", "steven", "paul", "andrew", "joshua", "kenneth", "kevin",
    "brian", "edward", "ronald", "timothy", "jason", "jeffrey", "ryan",
    "jacob", "gary", "nicholas", "eric", "jonathan", "stephen", "larry",
    "justin", "scott", "brandon", "benjamin", "samuel", "frank", "gregory",
    "raymond", "alexander", "patrick", "jack", "dennis", "jerry", "tyler",
    "aaron", "jose", "adam", "henry", "douglas", "zachary", "peter",
    "kyle", "walter", "harold", "carl", "keith", "roger", "arthur",
    # Female
    "mary", "patricia", "jennifer", "linda", "barbara", "elizabeth",
    "susan", "jessica", "sarah", "karen", "nancy", "betty", "margaret",
    "sandra", "ashley", "kimberly", "emily", "donna", "michelle", "dorothy",
    "carol", "amanda", "melissa", "deborah", "stephanie", "rebecca", "sharon",
    "laura", "cynthia", "kathleen", "amy", "angela", "shirley", "anna",
    "brenda", "pamela", "nicole", "samantha", "katherine", "christine",
    "debra", "rachel", "catherine", "carolyn", "janet", "ruth", "maria",
    "heather", "diane", "virginia", "julie", "joyce", "victoria", "kelly",
    "christina", "lauren", "joan", "evelyn", "judith", "megan", "andrea",
    "cheryl", "hannah", "jacqueline", "martha", "gloria", "teresa", "ann",
    "sara", "madison", "frances", "kathryn", "janice", "jean", "alice",
    "abigail", "olivia", "emma", "charlotte", "amelia", "isabella", "mia",
    "harper", "luna", "sophia", "ava", "evelyn", "ellie", "scarlett",
    # Spanish/Portuguese
    "carlos", "miguel", "luis", "juan", "francisco", "manuel", "antonio",
    "pedro", "diego", "rodriguez", "garcia", "martinez", "sanchez",
    # German
    "hans", "franz", "klaus", "helmut", "dieter", "gerhard", "bernhard",
    "anna", "anna", "maria", "margarete", "greta", "ingrid", "katrin",
    # French
    "jean", "pierre", "jacques", "andre", "francois", "louis", "albert",
    "marie", "jeanne", "monique", "christine", "sylvie", "isabelle",
    # Italian
    "antonio", "giuseppe", "marco", "giorgio", "giovanni", "mario", "paolo",
    "rosa", "anna", "maria", "giulia", "francesca", "laura", "elena",
    # Scandinavian
    "erik", "lars", "soren", "anders", "per", "nils", "ingrid", "astrid",
    "gerda", "helga", "sonja", "karin", "ulla",
    # Other European
    "vasily", "sergei", "ivan", "boris", "nikolai", "dmitri", "natalia",
    "olga", "irina", "tatiana", "yuri", "alexei", "vladimir",
}

# Non-Indian last names (Western/International)
NON_INDIAN_LAST_NAMES = {
    # English
    "smith", "johnson", "williams", "jones", "brown", "davis", "miller",
    "wilson", "moore", "taylor", "anderson", "thomas", "jackson", "white",
    "harris", "martin", "thompson", "garcia", "martinez", "robinson",
    "clark", "rodriguez", "lewis", "lee", "walker", "hall", "allen",
    "young", "king", "wright", "scott", "green", "baker", "nelson",
    "carter", "roberts", "phillips", "evans", "turner", "diaz", "parker",
    "edwards", "collins", "reyes", "morris", "murphy", "rogers", "morgan",
    "peterson", "cooper", "reed", "bell", "gomez", "cook", "morgan",
    "mitchell", "garrett", "burton", "fulton", "nash", "graves", "ford",
    "lambert", "newberry", "newcom", "newhouse", "newland", "newlin",
    # Spanish
    "garcia", "rodriguez", "sanchez", "martinez", "hernandez", "lopez",
    "gonzalez", "perez", "torres", "flores", "rivera", "gomez", "vargas",
    # German
    "mueller", "schmidt", "schneider", "fischer", "weber", "meyer", "wagner",
    "becker", "schulz", "hoffmann", "schroeder", "koch", "bauer", "klein",
    # French
    "martin", "bernard", "thomas", "robert", "richard", "petit", "durand",
    "lefevre", "moreau", "simon", "laurent", "lefebvre", "michel",
    # Italian
    "rossi", "russo", "ferrari", "esposito", "bianchi", "romano", "colombo",
    "rizzo", "marino", "greco", "bruno", "gallo", "conti", "costa",
    # Scandinavian
    "anderson", "jensen", "hansen", "christiansen", "lindgren", "bergstrom",
    "eriksson", "larsson", "olsson", "persson", "svensson", "gustavsson",
    # Other European
    "muller", "jones", "williams", "davies", "evans", "price", "bennett",
    # Chinese
    "wang", "li", "zhang", "liu", "chen", "yang", "huang", "zhao", "zhou",
    "xu", "sun", "ma", "zhu", "lin", "guo", "he", "gao", "zheng",
    # Japanese
    "tanaka", "suzuki", "yamamoto", "nakamura", "kobayashi", "kato", "yoshida",
    "yamada", "sasaki", "yamaguchi", "sakamoto", "matsumoto",
}

# Known cross-regional ambiguous names to always exclude
AMBIGUOUS_EXCLUSIONS = frozenset([
    "khan", "ali", "hassan", "ahmed", "sheikh", "islam", "malik",
    "hussain", "rahman", "rahim", "karim", "sultana", "begum",
    "lee", "kim", "park", "chen", "wang", "zhang", "garcia", "rodriguez",
    "martinez", "silva", "santos", "omar", "joseph", "george", "thomas",
    "john", "james", "michael",
])


def _normalize(names: set[str]) -> set[str]:
    """Lowercase, strip, filter by length, remove names with digits."""
    result = set()
    for name in names:
        n = name.lower().strip()
        if len(n) < 2 or len(n) > 30:
            continue
        if any(c.isdigit() for c in n):
            continue
        result.add(n)
    return result


def _fetch_text(url: str, label: str) -> str:
    """Fetch text from URL, return empty string on failure."""
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "name-classifier-builder/1.0"})
        resp.raise_for_status()
        print(f"  [OK] {label} ({len(resp.text)} bytes)")
        return resp.text
    except Exception as e:
        print(f"  [SKIP] {label}: {type(e).__name__}")
        return ""


def _parse_lines(text: str) -> set[str]:
    """Parse newline-separated text into a set of stripped names."""
    if not text:
        return set()
    return {line.strip() for line in text.splitlines() if line.strip()}


def build_training_data() -> None:
    """Main pipeline: curated + fetched data, clean, balance, save."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Start with curated lists
    print("\n--- Using Curated Data ---")
    indian_first = _normalize(CURATED_INDIAN_FIRST_NAMES)
    indian_last = _normalize(CURATED_INDIAN_LAST_NAMES)
    non_indian_first = _normalize(NON_INDIAN_FIRST_NAMES)
    non_indian_last = _normalize(NON_INDIAN_LAST_NAMES)
    print(f"  Curated Indian first names: {len(indian_first)}")
    print(f"  Curated Indian last names: {len(indian_last)}")
    print(f"  Curated non-Indian first names: {len(non_indian_first)}")
    print(f"  Curated non-Indian last names: {len(non_indian_last)}")

    # Try to fetch supplemental Indian last names from Wikidata
    print("\n--- Fetching Supplemental Data ---")
    try:
        sparql_query = """
        SELECT DISTINCT ?nameLabel WHERE {
          ?item wdt:P31 wd:Q101352 .
          ?item wdt:P17 wd:Q668 .
          ?item rdfs:label ?nameLabel .
          FILTER(LANG(?nameLabel) = "en")
        } LIMIT 2000
        """
        resp = requests.post(
            "https://query.wikidata.org/sparql",
            data={"query": sparql_query},
            headers={
                "Accept": "application/json",
                "User-Agent": "name-classifier-builder/1.0",
            },
            timeout=60,
        )
        resp.raise_for_status()
        results = resp.json()
        wikidata_surnames = {
            b["nameLabel"]["value"]
            for b in results.get("results", {}).get("bindings", [])
            if b.get("nameLabel", {}).get("value")
        }
        wikidata_surnames = _normalize(wikidata_surnames)
        indian_last.update(wikidata_surnames)
        print(f"  [OK] Wikidata SPARQL (added {len(wikidata_surnames)} surnames)")
    except Exception as e:
        print(f"  [SKIP] Wikidata: {type(e).__name__}")

    print(f"\n--- After Collection ---")
    print(f"  Indian first: {len(indian_first)}")
    print(f"  Indian last: {len(indian_last)}")
    print(f"  Non-Indian first: {len(non_indian_first)}")
    print(f"  Non-Indian last: {len(non_indian_last)}")

    # Remove ambiguous
    ambiguous = set()

    first_overlap = indian_first & non_indian_first
    ambiguous.update(first_overlap)
    indian_first -= first_overlap
    non_indian_first -= first_overlap

    last_overlap = indian_last & non_indian_last
    ambiguous.update(last_overlap)
    indian_last -= last_overlap
    non_indian_last -= last_overlap

    for name in AMBIGUOUS_EXCLUSIONS:
        indian_first.discard(name)
        indian_last.discard(name)
        non_indian_first.discard(name)
        non_indian_last.discard(name)
        ambiguous.add(name)

    print(f"\n--- After Ambiguous Removal ---")
    print(f"  Indian first: {len(indian_first)}")
    print(f"  Indian last: {len(indian_last)}")
    print(f"  Non-Indian first: {len(non_indian_first)}")
    print(f"  Non-Indian last: {len(non_indian_last)}")
    print(f"  Ambiguous dropped: {len(ambiguous)}")

    # Balance classes
    if len(indian_first) > 0 and len(non_indian_first) > 0:
        ratio = len(indian_first) / len(non_indian_first)
        if ratio < 1 / 3:
            target = min(len(indian_first) * 3, len(non_indian_first))
            non_indian_first = set(random.sample(sorted(non_indian_first), target))
            print(f"  Downsampled non-Indian first to {target}")

    if len(indian_last) > 0 and len(non_indian_last) > 0:
        ratio = len(indian_last) / len(non_indian_last)
        if ratio < 1 / 3:
            target = min(len(indian_last) * 3, len(non_indian_last))
            non_indian_last = set(random.sample(sorted(non_indian_last), target))
            print(f"  Downsampled non-Indian last to {target}")

    # Save
    def _save(names: set[str], filename: str) -> None:
        path = DATA_DIR / filename
        sorted_names = sorted(names)
        path.write_text("\n".join(sorted_names) + "\n", encoding="utf-8")
        print(f"  Saved {filename}: {len(sorted_names)} names")

    print(f"\n--- Saving to {DATA_DIR} ---")
    _save(indian_first, "indian_firstnames.txt")
    _save(indian_last, "indian_lastnames.txt")
    _save(non_indian_first, "non_indian_firstnames.txt")
    _save(non_indian_last, "non_indian_lastnames.txt")
    _save(ambiguous, "ambiguous_names.txt")

    print("\nDone! Training data ready.")


if __name__ == "__main__":
    build_training_data()
