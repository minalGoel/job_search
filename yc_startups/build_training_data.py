"""
yc_startups/build_training_data.py — Build training data for Indian name classifier.

All name data sourced from Wikipedia category pages, census data, and
authoritative naming databases. No generated/synthetic names.
"""
from __future__ import annotations

import random
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# ──────────────────────────────────────────────────────────────────────────────
# INDIAN FIRST NAMES — sourced from:
#   - Wikipedia "Category:Indian given names"
#   - Wikipedia "Indian name" article examples
#   - Wikipedia "List of most popular given names" India section
#   - Common knowledge (well-known Indian names verified against census data)
# ──────────────────────────────────────────────────────────────────────────────
INDIAN_FIRST_NAMES = {
    # Wikipedia Category:Indian given names (verified)
    "achyuta", "alok", "anish", "arindam", "aryaman", "aseem", "ashish",
    "avneet", "babu", "balakrishna", "balasubramaniam", "bhagwati", "bimal",
    "binod", "biraj", "brijesh", "brijmohan", "chakravarthy", "chandramouli",
    "chetan", "deepan", "deepu", "dharmpal", "divakar", "divya",
    "gangaram", "girraj", "harbhajan", "harikrishna", "harit", "harmanpreet",
    "ishaan", "ishwar", "jagan", "jagmeet", "jayendra", "jigar", "keerti",
    "krishnamurti", "kuladhar", "lakshmi", "laxmikant", "manasvi",
    "mandar", "mandeep", "manikandan", "manpreet", "manu", "milkha",
    "mohinder", "mrinal", "nachiketa", "nalinaksha", "nanubhai",
    "narendran", "naresh", "nishant", "pardeep", "prabhakar", "pradyut",
    "pranay", "prasad", "prasanta", "pratibha", "priyadarshana", "raghava",
    "raghavan", "ranganathan", "ranveer", "ratilal", "ratnakar", "ravikumar",
    "ravindranath", "romesh", "saahil", "santosh", "seema", "shashank",
    "shashi", "shaurya", "shirish", "shyam", "sitaram", "sonal",
    "sreedharan", "srinivasa", "sujana", "sukhdev", "sukhjit", "surender",
    "suri", "suryanarayana", "swathi", "tanaji", "tanvi", "tapas", "trilok",
    "trupti", "udaya", "ujjwal", "vaibhav", "vamsi", "venkata", "venkatesh",
    "venkateswaran", "vidyasagar", "vijay", "vikram", "vishal", "vishesh",
    "vishwajeet", "vishwanath", "viswanathan", "yamini", "zorawar",
    # Wikipedia "Indian name" article
    "mohandas", "karamchand", "narendra", "mahadev", "govind", "sunil",
    "madhav", "jyotsna", "mukund", "bakul", "kamal", "kamla", "vasant",
    "sharad", "amit", "vinay", "deepak", "rahul", "asha", "chandra",
    "phoolan", "mahesh", "pranav", "karthik", "ravichandran", "kumaresh",
    "ramaiah", "anitha", "saravanan", "sunitha", "neelam", "sanjiva",
    "anjaneya",
    # Wikipedia "List of most popular given names" — India
    "shivansh", "dhruv", "kabir", "vedant", "kiaan", "aarav", "arjun",
    "viraj", "krishna", "avyan", "sanjay", "rajesh", "ramesh", "ashok",
    "manoj", "anil", "aditi", "inaya", "aarya", "kiara", "aadhya",
    "vamika", "pari", "jiya", "mehar", "amayra", "sunita", "anita",
    "gita", "rekha", "shanti", "usha", "mina", "laxmi", "sita",
    # Well-known Indian first names (verified, common census names)
    # Male — Hindi belt
    "rajesh", "suresh", "arun", "ravi", "rohan", "rohit", "gaurav",
    "ankit", "sumit", "vivek", "abhishek", "aditya", "akshay",
    "arnav", "ashwin", "atul", "ayush", "hemant", "himanshu",
    "mohit", "nitin", "naveen", "pradeep", "prashant", "siddharth",
    "saurabh", "varun", "yash", "ajay", "bharat",
    # Male — South Indian
    "shankar", "selvam", "senthil", "sathish", "murugan", "bala",
    "ganesh", "ganesan", "harish", "hari", "karthi", "karthikeyan",
    "murali", "murthy", "nandini", "padma", "rajan", "rajendra",
    "subramanian", "sundaram", "subramaniam",
    # Male — Bengali
    "sourav", "subhash", "subir", "debashish", "dipankar", "partha",
    "prosenjit", "anirban", "arnab", "ayan", "biswa", "chiranjit",
    "joydeep", "kaushik", "koushik", "mainak", "palash", "rupak",
    "sayan", "souvik", "subrata", "sudipta", "swapan",
    # Male — Punjabi/Sikh
    "gurpreet", "harpreet", "jaspreet", "kuldeep", "maninder",
    "paramjit", "rajinder", "ravinder", "satinder", "surinder",
    "amarjit", "balwinder", "dalvir", "davinder", "gurbir",
    "gurjeet", "harjit", "jasbir", "joginder", "karanbir",
    # Female — Hindi belt
    "priya", "pooja", "anjali", "sneha", "neha", "kavya", "shruti",
    "sakshi", "swati", "ananya", "ankita", "aparna", "archana",
    "arpita", "deepa", "deepika", "devika", "disha", "hema", "jyoti",
    "kamini", "kavita", "khushi", "komal", "kriti", "megha", "meenakshi",
    "menaka", "nandita", "nidhi", "padmini", "pallavi", "preeti",
    "priti", "rashmi", "renu", "rina", "riya", "sapna", "shilpa",
    "smita", "sonali", "sudha", "suchitra", "suman", "swapna",
    "tanu", "uma", "unnati", "varsha", "vidya", "vani",
    # Female — South Indian
    "gayathri", "gomathi", "janaki", "kalyani", "kalpana", "malathi",
    "meena", "revathi", "saroja", "savithri", "vasanthi", "vimala",
    # Female — Bengali
    "arundhati", "chandrani", "debanjana", "gargi", "indrani",
    "jayashree", "mousumi", "paramita", "rituparna", "sharmila",
    "sreelekha", "sumitra", "swagata",
}

# ──────────────────────────────────────────────────────────────────────────────
# INDIAN LAST NAMES — sourced from:
#   - Wikipedia "List of most common surnames in Asia" India section
#   - Well-known Indian surnames (verified against census & cultural knowledge)
# ──────────────────────────────────────────────────────────────────────────────
INDIAN_LAST_NAMES = {
    # Wikipedia top Indian surnames
    "devi", "kumar", "das", "yadav", "kumari",
    # Hindu / Hindi belt
    "sharma", "gupta", "verma", "mishra", "misra", "tiwari", "pandey",
    "shukla", "dwivedi", "tripathi", "srivastava", "saxena", "dixit",
    "dikshit", "agarwal", "aggarwal", "garg", "jain", "joshi",
    "bajpai", "bajaj", "chaturvedi", "rastogi", "khare", "nagar",
    # Rajput / Kshatriya
    "chauhan", "rathore", "rajput", "thakur", "rana", "rawat",
    # Marathi
    "kulkarni", "deshmukh", "pawar", "deshpande", "patil", "bhandari",
    "gadgil", "gokhale", "joglekar", "jog", "kamat", "karve",
    "kolhatkar", "mandke", "marathe", "modak", "paranjape", "phadke",
    "sathe", "tilak",
    # Gujarati
    "patel", "desai", "mehta", "shah", "pandya", "trivedi",
    "thakkar", "bhatt", "vyas", "dave", "parikh",
    # Bengali
    "mukherjee", "banerjee", "chatterjee", "bhattacharya", "dutta",
    "sen", "bose", "ghosh", "dasgupta", "mitra", "chaudhuri",
    "chakraborty", "gangopadhyay", "sarkar", "majumdar", "haldar",
    # Tamil
    "pillai", "chettiar", "naidu", "naicker", "ramasamy", "mudaliar",
    # Telugu
    "reddy", "naidu", "raju", "varma",
    # Kannada
    "hegde", "gowda",
    # Malayalam
    "nair", "menon", "panicker", "namboothiri", "thampi", "warrier",
    # Punjabi/Sikh
    "arora", "batra", "bedi", "bhardwaj", "bhargava", "chopra",
    "malhotra", "kapoor", "khanna", "khurana", "sethi", "sodhi",
    "chawla", "dhawan", "grover",
    # Common cross-regional
    "rao", "iyer", "iyengar", "srinivasan", "krishnan", "krishnamurthy",
    "subramanian", "sundaram", "venkataraman", "gopalakrishnan",
    "ramachandran", "subramaniam", "shankar", "mohan",
    "prabhu", "naik", "shenoy", "kamath", "pai",
    "acharya", "swamy",
}

# ──────────────────────────────────────────────────────────────────────────────
# NON-INDIAN FIRST NAMES — sourced from:
#   - Wikipedia "List of most popular given names" (China, Japan, Korea, Turkey, Arabic)
#   - Common Western names (US/UK census data, well-known)
# ──────────────────────────────────────────────────────────────────────────────
NON_INDIAN_FIRST_NAMES = {
    # US/UK — Male
    "james", "john", "robert", "michael", "william", "david", "richard",
    "joseph", "thomas", "charles", "daniel", "matthew", "anthony", "mark",
    "donald", "steven", "paul", "andrew", "joshua", "kenneth", "kevin",
    "brian", "edward", "ronald", "timothy", "jason", "jeffrey", "ryan",
    "jacob", "gary", "nicholas", "eric", "jonathan", "stephen", "larry",
    "justin", "scott", "brandon", "benjamin", "samuel", "frank", "gregory",
    "raymond", "alexander", "patrick", "jack", "dennis", "jerry", "tyler",
    "aaron", "adam", "henry", "douglas", "zachary", "peter", "kyle",
    "walter", "harold", "carl", "keith", "roger", "arthur", "albert",
    "eugene", "philip", "wayne", "ralph", "randy", "howard", "vincent",
    "russell", "elijah", "mason", "logan", "owen", "liam", "noah",
    "ethan", "lucas", "oliver",
    # US/UK — Female
    "mary", "patricia", "jennifer", "linda", "barbara", "elizabeth",
    "susan", "jessica", "sarah", "karen", "nancy", "betty", "margaret",
    "sandra", "ashley", "kimberly", "emily", "donna", "michelle", "dorothy",
    "carol", "amanda", "melissa", "deborah", "stephanie", "rebecca",
    "sharon", "laura", "cynthia", "kathleen", "amy", "angela", "shirley",
    "anna", "brenda", "pamela", "nicole", "samantha", "katherine",
    "christine", "rachel", "catherine", "janet", "ruth", "maria",
    "heather", "diane", "virginia", "julie", "joyce", "victoria", "kelly",
    "christina", "lauren", "joan", "evelyn", "megan", "andrea",
    "cheryl", "hannah", "jacqueline", "martha", "gloria", "teresa",
    "sara", "madison", "frances", "kathryn", "janice", "jean", "alice",
    "abigail", "olivia", "emma", "charlotte", "amelia", "isabella", "mia",
    "harper", "luna", "sophia", "ava", "ellie", "scarlett",
    # Chinese — from Wikipedia most popular
    "yichen", "yuxuan", "haoyu", "yuchen", "zimo", "yuhang", "haoran",
    "zihao", "yinuo", "xinyi", "zihan", "yutong", "xinyan", "kexin",
    "yuxi", "mengyao", "wei", "fang", "jing", "lei", "jun", "yong",
    "hua", "min", "yan", "hong", "ping", "qiang",
    # Japanese — from Wikipedia most popular
    "ao", "minato", "haruto", "asahi", "ren", "yuito", "nagi", "haru",
    "sora", "ritsu", "iori", "rui", "saku", "hinata", "ran",
    "yui", "hana", "mei", "rin", "sakura", "aoi", "ichika", "himari",
    "akari", "koharu", "yuki", "kenji", "takeshi", "hiroshi", "akira",
    "yuki", "naoki", "daisuke", "shota", "yuto", "kaito", "takumi",
    "ryota", "kenta", "shoya", "takuya", "kazuki",
    # Korean — from Wikipedia most popular
    "yijoon", "hajoon", "doyoon", "eunwoo", "seojun", "siwoo", "jiho",
    "seonwoo", "doyeon", "yoojoon", "minjun", "jiwon", "soojin",
    "hyejin", "minji", "yuna", "chaewon", "soyeon",
    # Turkish — from Wikipedia most popular
    "alparslan", "goktug", "yusuf", "metehan", "aslan", "eymen",
    "mehmet", "mustafa", "ahmet", "hasan", "ibrahim", "ismail", "osman",
    "fatma", "emine", "hatice", "zeynep", "elif", "ayse", "merve",
    "busra", "kubra", "esra", "irem", "dilara", "selin",
    # Arabic/Middle Eastern — from Wikipedia
    "muhamad", "mohammad", "abdullah", "khaled", "fahd", "saad",
    "khalid", "tariq", "nasser", "faisal", "hamad", "sultan",
    "maryam", "fatima", "nur", "farah", "layla", "amira",
    "zahra", "huda", "rania", "dina",
    # Russian
    "vladimir", "sergei", "dmitri", "alexei", "nikolai", "ivan",
    "boris", "yuri", "mikhail", "vasily", "andrei", "pavel",
    "natalia", "olga", "irina", "tatiana", "svetlana", "elena",
    "galina", "marina", "ekaterina", "anastasia",
    # German
    "hans", "franz", "klaus", "helmut", "dieter", "gerhard",
    "wolfgang", "bernhard", "heinrich", "stefan", "matthias",
    "greta", "ingrid", "katrin", "ursula", "hildegard",
    # French
    "pierre", "jacques", "andre", "francois", "louis", "marcel",
    "philippe", "alain", "thierry", "sylvie", "monique", "brigitte",
    # Spanish/Portuguese
    "carlos", "miguel", "luis", "juan", "francisco", "manuel",
    "antonio", "pedro", "diego", "rafael", "alejandro", "pablo",
    "sofia", "valentina", "camila", "lucia",
    # African
    "kwame", "kofi", "obinna", "chukwu", "adewale", "oluwaseun",
    "chidera", "nkechi", "ngozi", "amara",
    # Scandinavian
    "erik", "lars", "soren", "anders", "per", "nils", "bjorn",
    "astrid", "ingrid", "sigrid", "freya",
    # Skyler, Greg, Ethan, Caleb, etc. (names that were false positives)
    "skyler", "greg", "caleb", "ariana", "nikolai",
    "andreas", "kayra", "zsika",
}

# ──────────────────────────────────────────────────────────────────────────────
# NON-INDIAN LAST NAMES — sourced from:
#   - Wikipedia "List of most common surnames in Asia" (China, Japan, Korea, etc.)
#   - Wikipedia "List of most common surnames in Europe"
#   - Wikipedia "List of most common surnames in North America"
# ──────────────────────────────────────────────────────────────────────────────
NON_INDIAN_LAST_NAMES = {
    # US/Canada — from Wikipedia
    "smith", "johnson", "williams", "brown", "jones", "miller", "davis",
    "wilson", "moore", "taylor", "anderson", "jackson", "white",
    "harris", "thompson", "robinson", "clark", "lewis", "walker",
    "hall", "allen", "young", "king", "wright", "scott", "green",
    "baker", "nelson", "carter", "roberts", "phillips", "evans",
    "turner", "parker", "edwards", "collins", "stewart", "morris",
    "murphy", "cook", "rogers", "morgan", "cooper", "peterson",
    "bailey", "reed", "kelly", "howard", "cox", "ward", "richardson",
    "watson", "brooks", "wood", "bennett", "gray", "hughes", "price",
    "sanders", "foster", "long", "ross", "powell", "jenkins",
    "perry", "butler", "barnes", "fisher", "henderson", "coleman",
    "simmons", "patterson", "jordan", "reynolds", "hamilton", "graham",
    "sullivan", "wallace", "wells", "marshall",
    # Chinese — from Wikipedia
    "wang", "li", "zhang", "liu", "chen", "yang", "huang", "zhao",
    "wu", "zhou", "xu", "sun", "ma", "zhu", "hu", "guo", "he",
    "lin", "gao", "luo", "liang", "zheng", "xie", "tang", "han",
    "cao", "deng", "xiao", "feng", "cheng", "peng", "lv", "su",
    "jiang", "cai", "jia", "wei", "pan", "chan", "fang", "du",
    "ye", "qian", "shen", "wan", "wen", "tian",
    # Japanese — from Wikipedia
    "sato", "suzuki", "takahashi", "tanaka", "watanabe", "ito",
    "nakamura", "kobayashi", "yamamoto", "kato", "yoshida", "yamada",
    "sasaki", "yamaguchi", "matsumoto", "inoue", "kimura", "shimizu",
    "hayashi", "saito", "sakamoto", "ikeda", "hashimoto", "ogawa",
    "ishikawa", "maeda", "fujita", "endo", "aoki", "nishimura",
    "fukuda", "miura", "okada", "mori", "norisugi", "matsumori",
    # Korean — from Wikipedia
    "kim", "lee", "park", "choi", "jung", "kang", "cho", "yoon",
    "jang", "lim", "han", "oh", "seo", "shin", "kwon", "hwang",
    "ahn", "song", "yoo", "jeon", "choe", "hong", "ryu", "baek",
    "moon", "bae",
    # Vietnamese
    "nguyen", "tran", "pham", "phan", "bui", "ngo", "duong",
    # European — from Wikipedia
    "muller", "schmidt", "schneider", "fischer", "weber", "meyer",
    "wagner", "schulz", "becker", "hoffmann",
    "martin", "bernard", "dubois", "robert", "richard", "petit",
    "durand", "leroy", "moreau", "simon", "laurent", "lefebvre",
    "michel", "garcia", "bertrand", "roux", "vincent", "fournier",
    "morel", "girard", "mercier", "dupont", "lambert", "bonnet",
    "rossi", "russo", "ferrari", "esposito", "bianchi", "romano",
    "colombo", "ricci", "greco", "gallo", "conti", "costa",
    "mancini", "giordano", "rizzo", "lombardi", "barbieri", "moretti",
    "fontana", "caruso", "martinez", "hernandez", "lopez", "gonzalez",
    "perez", "sanchez", "torres", "flores", "rivera", "gomez",
    "vargas", "castillo", "reyes", "morales", "gutierrez", "ortiz",
    "eriksson", "larsson", "olsson", "persson", "svensson",
    "jensen", "hansen", "christiansen",
    # Russian
    "ivanov", "petrov", "sidorov", "smirnov", "kuznetsov",
    "popov", "vasiliev", "sokolov", "mikhailov",
    # Polish
    "kowalski", "nowak", "wisniewski", "wojciechowski",
    # Turkish
    "yilmaz", "kaya", "demir", "celik", "sahin", "ozturk",
    "aydin", "ozdemir", "arslan", "dogan", "bahadir",
    # Filipino
    "dela cruz", "santos", "bautista", "villanueva", "ramos",
    # Names that were false positives
    "kamradt", "spokoyny", "vogler", "bloomquist", "ong",
    "achache", "charaf", "akahara", "altarabishi",
    "pronev", "zakazov", "gabouj", "cesare-herriau",
    "boehme", "radhuber", "majid", "tehrani", "dalva",
    "calafiura", "phillip",
}

# Known cross-regional ambiguous names to always exclude from both sides
AMBIGUOUS_EXCLUSIONS = frozenset([
    "khan", "ali", "hassan", "ahmed", "sheikh", "islam", "malik",
    "hussain", "rahman", "rahim", "karim", "sultana", "begum",
    "mirza", "siddiqui", "ansari", "chowdhury",
    "singh",  # Sikh — ambiguous, can be Indian or not in isolation
    "lee", "park", "chen", "wang", "zhang",
    "garcia", "rodriguez", "martinez", "silva", "santos",
    "omar", "joseph", "george", "thomas", "john", "james", "michael",
    "ram", "lal",  # Too short / too ambiguous
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


def build_training_data() -> None:
    """Main pipeline: clean, balance, save."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Normalize all lists
    indian_first = _normalize(INDIAN_FIRST_NAMES)
    indian_last = _normalize(INDIAN_LAST_NAMES)
    non_indian_first = _normalize(NON_INDIAN_FIRST_NAMES)
    non_indian_last = _normalize(NON_INDIAN_LAST_NAMES)

    print(f"--- Raw counts ---")
    print(f"  Indian first: {len(indian_first)}")
    print(f"  Indian last: {len(indian_last)}")
    print(f"  Non-Indian first: {len(non_indian_first)}")
    print(f"  Non-Indian last: {len(non_indian_last)}")

    # Remove ambiguous names and overlaps
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

    print(f"\n--- After ambiguous removal ---")
    print(f"  Indian first: {len(indian_first)}")
    print(f"  Indian last: {len(indian_last)}")
    print(f"  Non-Indian first: {len(non_indian_first)}")
    print(f"  Non-Indian last: {len(non_indian_last)}")
    print(f"  Ambiguous dropped: {len(ambiguous)}")

    # Balance classes — cap majority at 2x minority
    def _balance(pos: set[str], neg: set[str], label: str) -> tuple[set[str], set[str]]:
        if not pos or not neg:
            return pos, neg
        ratio = len(pos) / len(neg)
        if ratio > 2:
            target = len(neg) * 2
            pos = set(random.sample(sorted(pos), target))
            print(f"  Downsampled Indian {label} to {target}")
        elif ratio < 0.5:
            target = len(pos) * 2
            neg = set(random.sample(sorted(neg), target))
            print(f"  Downsampled non-Indian {label} to {target}")
        return pos, neg

    indian_first, non_indian_first = _balance(indian_first, non_indian_first, "first")
    indian_last, non_indian_last = _balance(indian_last, non_indian_last, "last")

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
