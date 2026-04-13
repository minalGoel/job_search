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
    # Male — Hindi belt (additional missing names)
    "nikhil", "akhil", "shrey", "chirag", "atharva", "aman", "chetan",
    "nalin", "nisarg", "chinmay", "shloke", "gunin", "monik",
    "aniket", "kartikay", "kushal", "lakshay", "lavish", "manan",
    "nayan", "parth", "pratik", "puneet", "rachit", "samarth",
    "shivam", "sparsh", "tanmay", "tushar", "utkarsh", "vipul",
    "yuvraj", "zeeshan",
    # Male — South Indian
    "shankar", "selvam", "senthil", "sathish", "murugan", "bala",
    "ganesh", "ganesan", "harish", "hari", "karthi", "karthikeyan",
    "murali", "murthy", "nandini", "padma", "rajan", "rajendra",
    "subramanian", "sundaram", "subramaniam",
    # Male — South Indian (additional)
    "ananth", "aravind", "arun", "balakumar", "chandru", "dinesh",
    "govindaraj", "jaganathan", "jagath", "kesav", "kumaran",
    "lokesh", "madhan", "manikandan", "muthukumar", "nithyanand",
    "palani", "prabakaran", "ramkumar", "saravana", "selvakumar",
    "sureshkumar", "thirumal", "vignesh", "vijayakumar",
    # Male — Bengali (additional)
    "sourav", "subhash", "subir", "debashish", "dipankar", "partha",
    "prosenjit", "anirban", "arnab", "ayan", "biswa", "chiranjit",
    "joydeep", "kaushik", "koushik", "mainak", "palash", "rupak",
    "sayan", "souvik", "subrata", "sudipta", "swapan",
    "abhijit", "amitava", "aniruddha", "arijit", "biswajit",
    "debabrata", "joydip", "nilanjana", "rajib", "santanu",
    "satyajit", "soumya", "soumyajit", "sudip", "suman",
    "supratim", "tanmoy", "turja", "tridib",
    # Male — Punjabi/Sikh
    "gurpreet", "harpreet", "jaspreet", "kuldeep", "maninder",
    "paramjit", "rajinder", "ravinder", "satinder", "surinder",
    "amarjit", "balwinder", "dalvir", "davinder", "gurbir",
    "gurjeet", "harjit", "jasbir", "joginder", "karanbir",
    "amandeep", "bikramjit", "gurdeep", "harmeet", "inderjit",
    "lakhwinder", "navdeep", "navjot", "pawandeep", "simarjit",
    # Female — Hindi belt
    "priya", "pooja", "anjali", "sneha", "neha", "kavya", "shruti",
    "sakshi", "swati", "ananya", "ankita", "aparna", "archana",
    "arpita", "deepa", "deepika", "devika", "disha", "hema", "jyoti",
    "kamini", "kavita", "khushi", "komal", "kriti", "megha", "meenakshi",
    "menaka", "nandita", "nidhi", "padmini", "pallavi", "preeti",
    "priti", "rashmi", "renu", "rina", "riya", "sapna", "shilpa",
    "smita", "sonali", "sudha", "suchitra", "suman", "swapna",
    "tanu", "uma", "unnati", "varsha", "vidya", "vani",
    # Female — Hindi belt (additional)
    "aastha", "akansha", "akanksha", "akriti", "alka", "amrita",
    "avni", "bhavna", "chaitali", "ekta", "garima", "gunjan",
    "isha", "ishita", "kanika", "kiran", "lavanya", "madhuri",
    "mahima", "manisha", "meenal", "namrata", "natasha",
    "neerja", "payal", "poonam", "prachi", "pragati", "priyanshi",
    "radhika", "ruchika", "sandhya", "shraddha", "shreya",
    "shweta", "sipra", "surbhi", "swati", "trisha", "vaishnavi",
    "yukti",
    # Female — South Indian
    "gayathri", "gomathi", "janaki", "kalyani", "kalpana", "malathi",
    "meena", "revathi", "saroja", "savithri", "vasanthi", "vimala",
    # Female — South Indian (additional)
    "abinaya", "akshaya", "ammu", "ananya", "deepa", "divyabharathi",
    "ezhilarasi", "geetha", "hema", "ilamathy", "iswarya",
    "jayalakshmi", "jothika", "karthika", "kaveri", "kokila",
    "kumari", "latha", "madhumitha", "mahalakshmi", "mala",
    "nithya", "parvathy", "ponmalar", "priyadarshini", "radha",
    "ramya", "ranjani", "selvamani", "shanthi", "shruthi",
    "sivaranjani", "srividhya", "subhasri", "sudha", "suganya",
    "suhasini", "supriya", "tamilarasi", "thenmozhi", "vijaya",
    "vijayalakshmi", "yasodha",
    # Female — Bengali
    "arundhati", "chandrani", "debanjana", "gargi", "indrani",
    "jayashree", "mousumi", "paramita", "rituparna", "sharmila",
    "sreelekha", "sumitra", "swagata",
    # Female — Bengali (additional)
    "aparajita", "baisakhi", "barnali", "chandrima", "debjani",
    "debolina", "ishani", "jayeeta", "jharna", "kakoli", "keya",
    "krishna", "laboni", "lipika", "lopamudra", "madhumita",
    "mandira", "mita", "mitali", "moumita", "nabanita", "nilanjana",
    "papiya", "piyali", "pompa", "pritha", "priyanka", "purba",
    "raka", "rimi", "rupa", "rupali", "saheli", "sangita",
    "sarbani", "semanti", "shreemoyee", "sohini", "sreyashi",
    "subhamita", "susmita", "tithi", "trisha", "upasana",
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
    # Bengali — major surnames NOT previously included
    "roy", "biswas", "mondal", "saha", "nandi", "pal", "kundu",
    "basak", "hazra", "sarker", "ghoshal", "chanda", "mandal",
    "basu", "lahiri", "deb", "adhikari", "bhadra", "dey",
    "ganguly", "mukherjee", "poddar", "samanta", "sanyal",
    "seal", "sinha",
    # Punjabi/Sikh — major surnames NOT previously included
    "gill", "grewal", "dhaliwal", "sidhu", "sandhu", "dhillon",
    "virk", "sekhon", "mangat", "brar", "cheema", "bajwa",
    "randhawa", "sohi", "toor", "deol", "hundal",
    # Marathi — additional common surnames
    "shinde", "jadhav", "mhatre", "bhosale", "kale", "lokhande",
    "nimkar", "more", "gaikwad", "salvi", "wagh", "kamble",
    "thakre", "chougule", "dalvi",
    # Gujarati — major surnames NOT previously included
    "modi", "kothari", "sanghvi", "lakhani", "khatri", "vora",
    "doshi", "dalal", "jhaveri", "majithia", "rupani",
    "gandhi", "parekh",
    # UP/Bihar — additional common surnames
    "dubey", "pathak", "upadhyay", "chaudhary", "maurya",
    "kushwaha", "prajapati", "soni", "kesarwani", "tomar",
    "lodhi", "kurmi",
    # Rajput / Kshatriya — additional
    "shekhawat", "tanwar", "panwar", "rathod", "jhala", "solanki",
    "sisodiya", "bhati", "hada",
    # South Indian Tamil — additional
    "swaminathan", "chandrasekaran", "krishnaswamy", "venkatesan",
    "annamalai", "parthasarathy", "ayyappan", "seshadri",
    "vaidyanathan", "balasubramanian", "subramanyan", "ramasubramanian",
    "krishnaswami", "palaniswamy", "arunachalam", "natarajan",
    "manickam", "arumugam", "tamilarasan", "thirumurthy",
    # South Indian Telugu — additional
    "chowdary", "rayudu", "kommuri", "anumolu", "siripurapu",
    "lingam", "tatikonda", "vuppala", "yerramilli",
    # South Indian Kannada — additional
    "nagaraj", "nagaraju", "badami", "bhat", "manjunath",
    "upadhyaya", "belur", "haveri", "kodagu", "kudligi",
    # South Indian Malayalam — additional
    "nambiar", "velayudhan", "chandy", "kurian", "mathew",
    "varghese", "cherian", "philip", "oommen",
    # Odia
    "misra", "patnaik", "mohapatra", "das", "panda", "rath",
    "nanda", "sahoo", "behera", "biswal", "pradhan",
    # Assamese
    "gogoi", "phukan", "bora", "deka", "hazarika", "baruah",
    "kalita", "nath", "das",
    # Sindhi
    "advani", "kirpalani", "lalwani", "mirchandani", "ramnani",
    "rohra", "thadani", "wadhwani",
    # Indian Christian
    "d'souza", "fernandes", "furtado", "gomes", "lobo",
    "mascarenhas", "monteiro", "pinto", "rodrigues", "sequeira",
    # Additional cross-regional
    "anand", "balan", "babu", "chowdhury", "kapila", "nag",
    "narayanan", "prasad", "rajan", "raman",
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
    # Confirmed false positives from borderline audit (scored >0.70 on first model
    # but are non-Indian — Western, Middle Eastern, East Asian, African)
    "shaun", "grant", "swan", "mitch", "hamish", "axel",
    "papa",           # West African given name (Senegalese, Ghanaian)
    "niosha",         # Persian/Iranian
    "rabii",          # Arabic
    "shehbaz",        # Pakistani Punjabi
    "sohrab",         # Persian
    "deniz",          # Turkish
    "artem",          # Ukrainian/Russian
    "vincent",        # French (was triggering both-model threshold)
    "bilal",          # Arabic (Muslim, not Indian-origin)
    "azmat",          # Pakistani
    "sabih",          # Pakistani/Arabic
    "eliot",          # Western (was triggering via last-name model)
    "hamad",          # Arabic (already in Arabic section, make explicit)
    "kofi",           # Ghanaian (Akan)
    "kwame",          # Ghanaian (Akan)
    # Additional Persian/Iranian first names — to reduce n-gram overlap with Indian
    # "ni-", "ra-", "sha-" patterns in Persian names were causing false positives
    "shirin", "mitra", "narges", "nasrin", "leila", "parisa", "negar",
    "nikoo", "niloofar", "yasaman", "setareh", "shabnam", "soraya",
    "reza", "sina", "dariush", "kayhan", "kambiz", "shahriar",
    "nader", "nima", "navid", "nooshin", "roya", "roshan",
    # Additional Arabic first names — to reduce "ra-", "ab-", "rabi-" overlap
    "rashid", "rafiq", "rami", "nabil", "naim", "sabri", "farid",
    "tarek", "amr", "bassem", "wael", "walid", "mazen", "ramzi",
    "rabab", "rabi",  # Arabic given names with "rab-" prefix
    # Additional Turkish first names
    "burak", "cenk", "emre", "ercan", "ferhat", "kutay", "onur",
    "umut", "volkan", "berk", "caner", "enes", "eray", "furkan",
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
    # Names that were false positives (previous)
    "kamradt", "spokoyny", "vogler", "bloomquist", "ong",
    "achache", "charaf", "akahara", "altarabishi",
    "pronev", "zakazov", "gabouj", "cesare-herriau",
    "boehme", "radhuber", "majid", "tehrani", "dalva",
    "calafiura", "phillip",
    # Confirmed false positives from borderline audit (last-name model scored
    # 0.72-0.75 on these non-Indian surnames due to n-gram overlap)
    "farina",       # Italian
    "damm",         # German/Danish
    "krause",       # German
    "jarvie",       # Scottish
    "paarup",       # Danish/Scandinavian
    "shahar",       # Israeli/Hebrew
    "garrigues",    # French/Occitan
    "rabie",        # Arabic
    "samadi",       # Persian/Iranian
    "ayrton",       # English
    "riley",        # Irish/English
    "khachi",       # Middle Eastern
    "asmatullah",   # Pakistani
    "habibullah",   # Pakistani
    "haghighat",    # Persian
    "bugara",       # Ukrainian/Eastern European
    "wele",         # West African
    "kuri",         # Latin American
    # "jolly" removed — added to AMBIGUOUS_EXCLUSIONS instead
    "oladipo",      # Nigerian Yoruba
    "mckenzie",     # Scottish
    "lafontaine",   # French
    "ackerman",     # German/Jewish
    "beaujard",     # French
    "parga",        # Spanish
    "ramos",        # Spanish/Filipino
    # Additional Persian/Iranian last names — to teach model that "-adi", "-ani",
    # "-ami", "-avi", "-ami" endings are NOT exclusively Indian
    "hosseini", "sadeghi", "mousavi", "kiani", "razavi", "karimi",
    "shirazi", "ahmadi", "najafi", "eskandari", "tabatabaei",
    "salahi", "nazari", "safari", "bahrami", "hashemi", "rashidi",
    "moradi", "mohammadi", "ebrahimi", "ghorbani", "ghafari",
    # Additional Arabic last names
    "haddad", "mansour", "khalidi", "masri", "shalabi", "nasrallah",
    "salim", "hamdan", "abboud", "khoury", "nasr", "barakat",
    # Israeli/Hebrew surnames — extra "sha-" entries to counterbalance Indian
    # sha- surnames (sharma, shah, shakya, shaw, shinde bias toward Indian)
    "cohen", "levy", "goldberg", "friedman", "katz", "shapiro",
    "mizrahi", "ben-david", "levi",
    "shahar", "shaked", "shalit", "sharon", "shavit", "shapira",
    "shechter", "shenkar", "shilo",
    # English "sha-" surnames
    "sharp", "shannon",
}



# ──────────────────────────────────────────────────────────────────────────────
# CSV-SOURCED INDIAN NAMES — unique values from names.csv (9,320 Indian names)
# First names: 3,168 unique entries. Last names: 413 unique entries (>=2 occurrences).
# These supplement the hand-curated sets above.
# ──────────────────────────────────────────────────────────────────────────────
CSV_INDIAN_FIRST_NAMES = {
    "aaan", "aabha", "aabid", "aadam", "aadarsh", "aadesh", "aadhar", "aadi",
    "aadil", "aadinath", "aadish", "aadit", "aaditya", "aadrit", "aadya", "aafreen",
    "aafsar", "aaftab", "aagya", "aahan", "aakanksha", "aakansh", "aakansha", "aakarsh",
    "aakarsha", "aakash", "aakriti", "aalhad", "aamash", "aameer", "aamir", "aamr",
    "aanandh", "aanchal", "aankit", "aanya", "aaqib", "aaradhya", "aaratrika", "aarchi",
    "aareti", "aarif", "aarish", "aarjav", "aarsh", "aarti", "aarushe", "aarushi",
    "aaryaman", "aaryan", "aas", "aasha", "aashay", "aasheesh", "aashi", "aashika",
    "aashique", "aashish", "aashishkumar", "aashmani", "aashmita", "aashna", "aashrika", "aashrita",
    "aashutosh", "aasif", "aatish", "aaveg", "aavej", "aayaam", "aayush", "aayushi",
    "aayushmaan", "aazad", "abbel", "abburi", "abdallah", "abdesh", "abdhesh", "abdu",
    "abdul", "abdulrehman", "abdultawwab", "abdur", "abha", "abhaas", "abhay", "abhijeet",
    "abhijith", "abhik", "abhilash", "abhimanu", "abhimanyu", "abhinav", "abhirup", "abhishak",
    "abi", "abid", "abishek", "abu", "achchhe", "adarsh", "adarsha", "adharsh",
    "adhyan", "adil", "adith", "adithya", "adla", "adnan", "adrija", "adx",
    "afnaan", "ahmad", "aikansh", "aiman", "aishwarya", "aiswarya", "aja", "ajeet",
    "ajeethkumar", "ajit", "ajith", "ajrudeen", "akash", "akbar", "akhand", "akheel",
    "akhilesh", "akilan", "akilesh", "akmal", "akshai", "akshant", "akshat", "akshita",
    "akshyath", "ala", "alan", "albinder", "alcee", "alex", "alfaz", "allrin",
    "alphones", "altab", "aluri", "amanpreet", "amar", "amaresh", "amartya", "ambadas",
    "ambarish", "ambika", "ambrish", "ameed", "ameensha", "ameer", "ameeth", "amey",
    "ameya", "amirishetti", "amirtha", "amirul", "amisha", "amitabh", "amitesh", "amitkumar",
    "amlaan", "amlan", "amol", "amrit", "amritesh", "amritpal", "amudhan", "anamika",
    "ananda", "anandamalraj", "anandharaj", "anandhini", "ananthakrishnan", "anantharaj", "ananthu", "anas",
    "anbarasu", "anchal", "angad", "animesh", "anirudh", "anjalina", "anjana", "anjit",
    "anjitha", "ankaj", "ankur", "ankush", "anmol", "annisa", "anoop", "ansh",
    "anshad", "anshika", "anshita", "anshu", "anshul", "anu", "anubhav", "anubhavdatt",
    "anuj", "anup", "anupam", "anupriya", "anuradha", "anurag", "anuraj", "anusha",
    "anushka", "anuvrat", "apoorva", "apratim", "apurav", "aradhya", "aravanan", "aravinda",
    "aravindan", "aravindh", "aravindhan", "arbaz", "arfaj", "arif", "arihant", "aritra",
    "arivazhagan", "arivind", "arkaprava", "armugam", "arockia", "arockiaraj", "arpit", "arsalan",
    "arshad", "arshala", "arshan", "arshia", "arti", "arulraj", "arumugapandi", "aruneshwaran",
    "arunkumar", "arushima", "arv", "arvind", "arvinder", "aryan", "asheesh", "ashi",
    "ashik", "ashique", "ashishkumar", "ashoka", "ashokkumar", "ashu", "ashutosh", "ashvani",
    "ashwani", "ashwanth", "ashwini", "asif", "asmita", "asmitha", "assets", "astha",
    "aswin", "ateeq", "atharv", "athira", "atikurraheman", "atish", "atmakuri", "augustine",
    "austin", "avanish", "avantika", "avijit", "avinash", "avinasha", "aviraj", "avnish",
    "avula", "ayaan", "ayman", "ayushi", "azad", "azeem", "azhar", "baba",
    "babendra", "babita", "babla", "bablesh", "bableshwar", "babloo", "bablu", "baboo",
    "babru", "babul", "backup", "badal", "badari", "baddur", "badiginchula", "badisa",
    "badri", "badrinath", "bagoji", "bagul", "bahaar", "bahadur", "baibhav", "baibhawi",
    "baikadi", "bainagari", "bairam", "baji", "bajirao", "bajjuru", "bajrang", "bakre",
    "bal", "balaaditya", "balaaji", "balachandran", "balagouni", "balaji", "balamurugan", "balaraman",
    "balasubramaniyam", "balasudharshan", "balbeer", "balendra", "baljeet", "baljinder", "balkrishna", "balmiki",
    "baloch", "balraj", "balu", "baluguri", "balusupati", "balvinder", "balwant", "bambam",
    "bammidi", "bamne", "banasi", "banavathu", "bandan", "bandari", "bande", "bandela",
    "bandi", "bandreddy", "banee", "bani", "banish", "banjit", "banothu", "bansode",
    "banti", "bantu", "banu", "banwari", "bapatu", "bappa", "bapuji", "bapurao",
    "barad", "baranukula", "barbi", "bariki", "barkatullah", "barugula", "barun", "basant",
    "basavachetan", "basavaraj", "basawraj", "basheerahamed", "bashir", "basil", "basireddy", "basit",
    "basudev", "bathini", "bathula", "battepati", "battini", "battipally", "battu", "battula",
    "bavini", "bayyapu", "beant", "bedabrata", "bedadha", "beduduri", "beena", "beeplov",
    "beer", "beerbahadur", "begari", "bela", "belani", "bellana", "belsare", "ben",
    "bendalam", "bendi", "benson", "besta", "bevin", "bhabendra", "bhadane", "bhadhrachalam",
    "bhadramraju", "bhadresh", "bhagavatula", "bhagawan", "bhagchand", "bhageerath", "bhagendra", "bhagvan",
    "bhagvat", "bhagwan", "bhagwat", "bhagya", "bhagyashree", "bhagyashri", "bhai", "bhairab",
    "bhairale", "bhairav", "bhajan", "bhakta", "bhakthasarangan", "bhakti", "bhanu", "bhanuprasad",
    "bharanidharan", "bharanish", "bharath", "bharathesh", "bharathidasan", "bharati", "bhargav", "bhargavan",
    "bhargavi", "bharkhada", "bharm", "bhartendu", "bharti", "bhaskar", "bhaskarjya", "bhaskarjyoti",
    "bhathena", "bhausaheb", "bhavana", "bhavaneeswar", "bhavani", "bhavay", "bhavesh", "bhaveshkumar",
    "bhavi", "bhavia", "bhavik", "bhavika", "bhavikkumar", "bhavin", "bhavini", "bhavish",
    "bhavisha", "bhavishya", "bhavjeet", "bhavneet", "bhavya", "bhavyansh", "bhawana", "bhawani",
    "bhawesh", "bhawna", "bheem", "bhim", "bhogadi", "bhola", "bholanath", "bhomik",
    "bhoomi", "bhoomika", "bhoopendra", "bhramori", "bhrigu", "bhukya", "bhumi", "bhumika",
    "bhumit", "bhupender", "bhupendra", "bhuvaneshwaran", "bhuvnesh", "bibinu", "bibishan", "bijender",
    "bikash", "bikrant", "bilalmon", "bintu", "bipin", "bivin", "blinkit", "bobby",
    "boby", "burhanuddin", "caliph", "calvin", "caroline", "catch", "cecil", "celestial",
    "cep", "chaarvi", "chachang", "chahat", "chaitanaya", "chaitanaye", "chaitanya", "chaithanya",
    "chaithra", "chaitra", "chakala", "chakali", "chakkarabani", "chakshu", "chalma", "chalvaraju",
    "chamakura", "chaman", "chamatkar", "champa", "champak", "chanchal", "chandan", "chandana",
    "chandani", "chander", "chandera", "chandershekhar", "chandhan", "chandini", "chandni", "chandrabalan",
    "chandrabhan", "chandrabhushan", "chandrakant", "chandramani", "chandraprakash", "chandrapuram", "chandrasekar", "chandrashekar",
    "chandrashekara", "chandrashekhar", "chandresh", "chandu", "chandukumar", "changappa", "chanky", "chanti",
    "chappala", "charan", "charanjeet", "charithra", "charmala", "charu", "charul", "charusuryan",
    "charvi", "chavi", "chaya", "chayan", "cheekutla", "cheguri", "chekuri", "chellamani",
    "chellapuram", "chendurthi", "cheneerkuppam", "chepyala", "cherala", "cheranjeev", "cheruku", "cherukuri",
    "cheshta", "cheshtha", "chethan", "chethana", "chethri", "chetna", "chetram", "chetti",
    "chettiyamannil", "chhavi", "chidananda", "chikkudu", "chikkula", "chiku", "chilamakuri", "chilla",
    "chilumula", "chimaladinne", "chimbili", "chinmaya", "chinmoy", "chinna", "chinnam", "chinnathambi",
    "chinni", "chinnolla", "chinraj", "chinta", "chintada", "chintalapudi", "chintan", "chintapalli",
    "chintareddy", "chinthagunta", "chinthakayala", "chintu", "chinu", "chiragkumar", "chiranjeev", "chiranjib",
    "chiranth", "chirasani", "chirukuri", "chitra", "chitraksh", "chitransh", "chitrapu", "chittumotu",
    "chityala", "chlapati", "choiden", "cholemarri", "choudam", "chowdawaram", "chowla", "christopher",
    "chukabotla", "cibi", "cibithan", "cigrofers", "claude", "cleanson", "clement", "confirmations",
    "cos", "cruyff", "crystel", "cyprian", "cyril", "cyrill", "dabal", "dabberu",
    "dabhi", "dabholkar", "dadi", "daisy", "daitary", "daivik", "dakarapu", "dakeshwar",
    "daksh", "dakshata", "dakshyani", "dal", "dalbir", "dalip", "daljit", "dalve",
    "damara", "daminee", "damini", "dammavalam", "damodar", "damodhar", "damodhara", "dampi",
    "danapuram", "dandapati", "dandu", "danesh", "dangari", "danish", "danthuluri", "daraji",
    "daravath", "darkstore", "darla", "darpan", "darrel", "darsan", "darshak", "darshan",
    "darshankumar", "darshika", "darshil", "darshit", "darshna", "darvesh", "darwin", "daryl",
    "dasari", "dasharath", "dashrath", "dasmeet", "dasna", "dasthagir", "dattatray", "dattatrey",
    "dattatry", "datti", "dattti", "daud", "davu", "dawood", "dayal", "dayanand",
    "dayananda", "dayim", "debajit", "debangshi", "debanjan", "debanshu", "debarshi", "debartha",
    "debashis", "debasis", "debasish", "debayan", "debdoot", "debjit", "debraj", "debu",
    "deeksha", "deena", "deenesh", "deep", "deepakjoshi", "deepakkumar", "deepakshi", "deepali",
    "deepam", "deepanjali", "deepanjan", "deepank", "deepankar", "deepansh", "deepanshi", "deepanshu",
    "deepanwita", "deepchand", "deepchandra", "deepender", "deependra", "deepesh", "deepinder", "deepjyoti",
    "denisha", "dependra", "designer", "deva", "devanand", "devansh", "devashik", "devender",
    "devendra", "devesh", "devinder", "deviram", "devmurari", "dhananjay", "dhananjayan", "dhanashri",
    "dhann", "dhanselvi", "dhanush", "dhanushikaa", "dhanuskaran", "dharaneeswaran", "dharanesh", "dharmaveeran",
    "dharmender", "dharmendra", "dharna", "dhaval", "dheeraj", "dhevendiran", "dhilipan", "dhilshifa",
    "dhinesh", "dhiraj", "dhirendra", "dhivya", "dhivyabalan", "dhruvesh", "dhwnit", "dianambika",
    "digvijay", "diksha", "dikshitha", "dileep", "dilip", "dilipkumar", "dilkhush", "dilli",
    "dillibabu", "dillisekar", "dilpreet", "dimple", "dineshkumar", "dinkar", "dipak", "dipen",
    "dipti", "dishali", "district", "dithishree", "divanshi", "divesh", "divyam", "divyansh",
    "divyanshi", "divyanshu", "divyesh", "diya", "drishti", "durga", "durgappa", "durgesh",
    "ebabu", "ebadu", "ebin", "edukondalu", "eediga", "eedigae", "eedugola", "eesarla",
    "ehsaan", "ehtesham", "eisht", "ejaz", "ejjagani", "ekaansh", "ekansh", "ekeshwar",
    "ekjot", "ekkamjeet", "eklavya", "eknath", "elabelli", "elakiya", "elavarasan", "elayaraja",
    "eldho", "eleven", "elithoti", "elumalai", "emanueal", "emdapuram", "emidisetti", "emmanuel",
    "eppa", "eppanapalli", "erika", "erraboina", "erragunta", "esha", "eshaan", "eshan",
    "eshav", "esheta", "eshita", "eshwar", "eshwarappa", "esop", "essa", "etendar",
    "eternal", "etukala", "eva", "ezumalai", "faaz", "faeza", "fahad", "fahim",
    "fahima", "faijan", "faiyazuddin", "faiz", "faizal", "faizan", "faizanuddin", "faizulla",
    "faizy", "falak", "faleshwar", "falgun", "falguni", "fanish", "faraaz", "faraz",
    "farazahmed", "fardad", "fardin", "fareed", "farhaan", "farhan", "farheen", "fariz",
    "farman", "farook", "farooque", "farsin", "farzan", "farzana", "fateh", "fathima",
    "fawwaz", "fazil", "fehmi", "femish", "ference", "feroze", "fesal", "figma",
    "finto", "firdous", "firoj", "firoz", "franklin", "frappe", "furqan", "gabbar",
    "gabrial", "gabriel", "gadamalla", "gaddam", "gadhavi", "gadhe", "gadi", "gadila",
    "gaffur", "gagan", "gagandeep", "gaganjeet", "gagarin", "gaini", "gajanan", "gajender",
    "gajendra", "gajula", "gajwel", "galav", "galipothula", "gandepalli", "gandhar", "gandla",
    "ganesha", "ganeshkumar", "gangadhara", "gangaraja", "gangavaram", "gangishetty", "ganivada", "ganji",
    "ganta", "gantada", "ganti", "ganusala", "garbhana", "garemella", "garla", "garlapati",
    "garudadhwaja", "garv", "garvit", "gatik", "gattu", "gaun", "gaur", "gaurab",
    "gauri", "gaurish", "gaurvi", "gautam", "gautamkumar", "gautham", "gavin", "gavvala",
    "gawin", "gayatri", "gazal", "gazanfar", "gedala", "gedipudi", "geeta", "geetanjali",
    "geetansh", "geeth", "geetika", "geetima", "geetinder", "geo", "georgie", "gera",
    "get", "ghanashyam", "ghanshani", "ghanshyam", "ghriti", "ghulam", "gia", "gian",
    "giddla", "gilbert", "gireesh", "gireesha", "girish", "girisha", "github", "gnanapriya",
    "gokavarapu", "gokul", "gokula", "gokulraj", "golu", "google", "gopal", "gopalakrishna",
    "gopinath", "gopukrishnan", "gorav", "gourav", "goutam", "goutham", "govid", "govindaraju",
    "gowtham", "gowthama", "grasim", "guhan", "gulab", "gulamsamdhani", "gulshan", "gunasekar",
    "gunasekaran", "gunturu", "gurmeet", "guru", "gurudath", "gurumoorthi", "guruprasad", "gururaj",
    "gurushekar", "gurvinder", "gyanendra", "haaika", "haardik", "habib", "habibali", "habibujama",
    "hadiya", "hafsa", "haider", "hajare", "hakim", "hala", "hameer", "hamid",
    "hamim", "hamza", "hamzah", "hanamakonda", "hanamantarao", "haneen", "hanish", "hanisha",
    "hanmant", "hanpreet", "hansa", "hansie", "hansika", "hanslal", "hansraj", "hanumantha",
    "hanumat", "hapi", "happy", "har", "haradeep", "hardeep", "hardik", "hare",
    "hareesh", "harendra", "hareram", "haresh", "haridas", "hariharan", "hariharaputhran", "harikant",
    "harikrishan", "harikrishnan", "harinanda", "harindar", "harini", "hariom", "hariprasad", "hariprasath",
    "haripriya", "harisankar", "harisha", "harishankar", "harjeet", "harjinder", "harjot", "harkaran",
    "harkesh", "harkirat", "harman", "harmandeep", "harmanjot", "harmehak", "harmender", "harminder",
    "harnek", "harnoor", "haroon", "harpal", "harphool", "harprasan", "harry", "harsh",
    "harsha", "harshad", "harshada", "harshakumar", "harshal", "harshan", "harsharanpreet", "harshavardan",
    "harshavarthine", "harshdeep", "harshi", "harshika", "harshil", "harshini", "harshit", "harshita",
    "harshith", "harshmeet", "harshpreet", "harshvardhan", "harshwardhan", "harsimeran", "harsimran", "harvinder",
    "harwinder", "haseeb", "haseen", "hashika", "hasmeet", "hasmukh", "hasnain", "hasti",
    "hatim", "hawa", "heeket", "heeraram", "heet", "heinz", "helal", "helpdesk",
    "hem", "hemalatha", "hemang", "hemanta", "hemanth", "hemantha", "hemonta", "hemraj",
    "hirthik", "hitendra", "hitesh", "honest", "honey", "hrithik", "humer", "hunny",
    "husain", "idindla", "ifrah", "iftekar", "iftekhar", "ikroop", "ikshita", "iliyas",
    "illaka", "ilyas", "imaad", "imad", "imam", "imran", "imrankhan", "imthiyas",
    "imtiaz", "inayat", "inbaraj", "inchara", "increment", "ind", "inder", "inderdeep",
    "inderjeet", "inderpreet", "indhu", "indra", "indrajeet", "indrajit", "indraneel", "indranil",
    "indrayani", "indresh", "indu", "infra", "inika", "injamul", "injmamul", "insha",
    "internal", "intezar", "inti", "ipsa", "ipshit", "ipshita", "ipsita", "iqbal",
    "ira", "irabasappa", "irfan", "iris", "irphan", "irsalagandi", "irshad", "isaac",
    "ish", "ishan", "ishana", "ishank", "ishant", "ishika", "ishit", "ishu",
    "ishudeep", "ishvarbhai", "islahuddin", "israr", "israrul", "itchapuram", "ithi", "itishree",
    "itul", "iyaj", "iyappan", "izazuddin", "jaanvi", "jadav", "jaddu", "jadeja",
    "jadob", "jafer", "jaffar", "jaffer", "jag", "jagadeep", "jagadeesan", "jagadeesh",
    "jagadish", "jagannath", "jagdeep", "jagdish", "jagdishwar", "jagir", "jagjot", "jagrit",
    "jagriti", "jagseer", "jagtar", "jagvir", "jagwant", "jahangeer", "jahangir", "jahanvi",
    "jahnavi", "jahnvi", "jai", "jaid", "jaideep", "jaiditya", "jaigourang", "jaimin",
    "jainam", "jainender", "jainesh", "jainul", "jaipal", "jaiprakash", "jaipratap", "jaishankar",
    "jaivarat", "jaiveer", "jaivir", "jaivrath", "jalaj", "jalal", "jalindar", "jamal",
    "jambucha", "jamee", "jami", "jammi", "jampa", "jampana", "jamsher", "janagam",
    "janak", "janani", "janardan", "janardhan", "janarthanan", "janesh", "janhavi", "janhvi",
    "janikbasha", "janith", "janmeet", "janmejar", "janmejay", "jannat", "janvi", "japna",
    "jarnendu", "jashandeep", "jashith", "jashveen", "jaskaran", "jaskeerat", "jaskiran", "jaskirat",
    "jasleen", "jasmeet", "jasmer", "jasmine", "jasmita", "jasmitha", "jasprit", "jasreen",
    "jassimran", "jasveer", "jasvinder", "jaswant", "jaswinder", "jatavath", "jateen", "jatin",
    "jatinder", "javed", "javeed", "javeeth", "javeth", "javid", "javvaji", "jawahar",
    "jay", "jaya", "jayaditya", "jayakumar", "jayansh", "jayant", "jayanta", "jayanth",
    "jayaprakash", "jayaseelan", "jayashankar", "jayasurya", "jaybeer", "jaydeep", "jaydev", "jaydip",
    "jayesh", "jaykumar", "jaynil", "jaypal", "jaypalbhai", "jayprasad", "jayswal", "jayus",
    "jayveer", "jaza", "jecky", "jeeshan", "jeeson", "jeet", "jeetendra", "jeetu",
    "jeeva", "jeevan", "jeevanandham", "jeferson", "jegathesan", "jekkala", "jemima", "jenefer",
    "jenifer", "jeniferlouis", "jenish", "jenson", "jerif", "jerin", "jeripothula", "jerish",
    "jeroen", "jeshwanth", "jessie", "jestin", "jesu", "jeswin", "jeyantha", "jhalak",
    "jhansi", "jhantu", "jhareswar", "jiben", "jibin", "jidnesh", "jignesh", "jiken",
    "jiksha", "jimit", "jinendra", "jinet", "jinisha", "jino", "jinosh", "jinson",
    "jishnu", "jishu", "jit", "jiten", "jitender", "jitendra", "jithin", "jitin",
    "jivitesh", "jobin", "jony", "joshwa", "jotinkumar", "juhee", "juned", "jyotheeshwar",
    "jyothi", "jyothy", "kabil", "kabilan", "kailash", "kaja", "kalai", "kalaiselvan",
    "kalaiyarasan", "kalan", "kalmesh", "kalpesh", "kalyan", "kamalakannan", "kamalanathan", "kamaldip",
    "kamalnath", "kanak", "kanav", "kanchan", "kanhaiya", "kanhiya", "kannadasan", "kannan",
    "kapil", "karam", "karambir", "karamvir", "karan", "karandeep", "karishma", "karkki",
    "karmanya", "karn", "karnesh", "karrothu", "kartheeswaran", "karthick", "karthikkeyan", "kartik",
    "kartika", "kartikey", "kashish", "kasinath", "kasmeer", "katari", "kathan", "kathiravan",
    "kaustoobh", "kavan", "kavi", "kavin", "kavinkumar", "kavinraj", "kaviyarasan", "kaviyarasu",
    "keerthana", "keerthiraj", "kempanna", "keshav", "ketan", "khajaadnanuddin", "khatib", "khushboo",
    "khushbu", "khushhal", "kirubakaran", "kisa", "kishor", "kishore", "kola", "koles",
    "komala", "kompalmohindra", "kotteeswaran", "kotteswaran", "kowshik", "krishan", "krishnakumar", "krishnamoorthi",
    "krishnamoorthy", "krishnanunni", "krishnmohan", "kritika", "kruty", "kubendra", "kuldip", "kumanan",
    "kumaraharish", "kumarasamy", "kumkum", "kunal", "kundan", "kunika", "kurban", "kushagra",
    "kyatham", "lachireddi", "laddaf", "laddagiri", "lagudu", "lahari", "laiba", "laila",
    "lakeshwar", "lakhan", "lakkineni", "lakshit", "lakshita", "lakshith", "lakshman", "lakshy",
    "lakshya", "lakshyaaditya", "lakum", "lala", "lalam", "lalan", "lalaram", "lalit",
    "lalita", "lalith", "lalmuni", "laltu", "lamiya", "lasya", "latesh", "latif",
    "lattupalli", "lav", "lava", "lavam", "lavdya", "laveena", "laveesha", "lavesh",
    "laveti", "lavina", "lavkesh", "lavlesh", "lavuri", "lavya", "lawrance", "lawrence",
    "laxman", "leela", "leesha", "legal", "lehar", "lekha", "lekhraj", "lellala",
    "likesh", "likhith", "likhitha", "likith", "likitha", "likithgowda", "lingala", "lingamolla",
    "lingampally", "lingamurthy", "lingesh", "linisha", "linkan", "lipak", "lisha", "livesh",
    "liyan", "liyana", "liza", "lizah", "lnv", "lochan", "lodha", "loganathan",
    "lohit", "lohith", "lokendra", "loknath", "lotus", "loukya", "love", "lovejot",
    "lovekush", "lovely", "lovepreet", "lovey", "lovish", "lovkesh", "lovneet", "lubhani",
    "lucky", "luv", "luvish", "lydia", "lynal", "maachagouni", "maahin", "maaz",
    "madala", "madan", "madanpal", "madanraj", "madapathi", "madar", "madasu", "maddala",
    "maddamsetti", "madduluri", "madduri", "madhab", "madhanraj", "madhavan", "madhavendra", "madhavi",
    "madhu", "madhukar", "madhulika", "madhur", "madhurakavi", "madhurima", "madhurjya", "madhushankara",
    "madhusudan", "madhuvanthi", "madikonda", "madunuri", "maganti", "magesh", "magizh", "mahadeep",
    "mahadeva", "mahadik", "mahajan", "mahak", "mahalingeshwar", "mahammad", "mahant", "mahantayya",
    "mahantesh", "mahanthesh", "maharshi", "mahasweta", "mahavir", "mahefujali", "mahek", "mahendaran",
    "mahender", "mahendra", "mahendrasingh", "maheshkrishnan", "maheshkumar", "mahika", "mallesh", "mallesha",
    "mallikarjun", "mallikbharath", "malsawmkimi", "malvika", "maneesh", "mangal", "mangaldeep", "mani",
    "manigandan", "manikandhan", "manikanta", "manikantha", "manirathinam", "manish", "manivasagam", "maniyarasan",
    "manjanaik", "manjeet", "manjit", "manju", "manjula", "manjunatha", "manmohan", "manohar",
    "manohara", "manoja", "manojkumar", "manoranjan", "manshree", "mansi", "mansoor", "manvi",
    "manvir", "manya", "margam", "mathan", "mathankumar", "mathanraj", "mathavan", "mathesh",
    "mayank", "mayur", "mcmillon", "meeneshkumar", "meghansh", "meghraj", "mehak", "meheboob",
    "mehrien", "melanie", "meraj", "merajuddin", "merchant", "metali", "milan", "minakshi",
    "minal", "mir", "mithilesh", "mithun", "mohamad", "mohamed", "mohamedyasin", "mohammd",
    "mohammed", "mohanraj", "mohd", "mohhamad", "moish", "momim", "monika", "monish",
    "monu", "moorthy", "mortha", "mounesh", "moupriya", "mouseem", "mridul", "mridula",
    "mubarak", "mudita", "mueen", "mugesh", "muhammed", "muhundhan", "mujeeb", "mujeebur",
    "mukesh", "mukim", "mukul", "muniraju", "muralidhasan", "muralitharan", "murari", "murugesh",
    "muskaan", "muskan", "muthu", "muthukumaraswamy", "myandraguthi", "naadir", "naaz", "nabal",
    "nabeel", "nabiha", "nachiket", "nadeem", "nadendla", "nadish", "naeem", "nafilah",
    "naga", "nagabhushnam", "nagaleela", "naganath", "nagapatla", "nagarjun", "nagarjuna", "nagendra",
    "nagesh", "nageshwar", "nagmani", "nagnath", "nagulapalli", "nahak", "naimisha", "naina",
    "nainesh", "naini", "nainika", "naitik", "najarmani", "najeb", "najim", "najir",
    "nakul", "nakush", "nalap", "nalapagari", "nalgonda", "nalidevareddigari", "nalini", "nalla",
    "nallaballi", "nallabothula", "nallamuthukumar", "nalmala", "nama", "naman", "namanpreet", "namanreet",
    "namburi", "namdev", "nameera", "namira", "namita", "namrta", "namya", "nana",
    "nand", "nandakumar", "nandan", "nandani", "nandeesha", "nandeeshkumar", "nandhakumar", "nandhini",
    "nandhu", "nandika", "nandish", "nandiwada", "nandni", "nandu", "nanga", "nangedda",
    "nangunuri", "nanigalla", "nanigopal", "nanika", "nannam", "nanneboina", "naomi", "naragoni",
    "narala", "naramala", "narasimha", "narasimhaswamy", "narayan", "narayanamoorthy", "narayankumar", "narender",
    "narendrasingh", "nareshkumar", "narinder", "narla", "narpal", "narri", "narshimha", "narshinh",
    "narsimha", "naseeb", "naseem", "nashiya", "nasim", "naskanti", "natesh", "nathan",
    "nathi", "natraj", "naushad", "navab", "navaneeth", "navapet", "navas", "navaz",
    "naved", "naveed", "naveendevan", "naveenkumar", "naveenraj", "naveer", "naveesh", "navik",
    "naville", "navin", "navjyot", "navneet", "navya", "nayantara", "nazil", "neelu",
    "neeraj", "neerudu", "neredimilliramesh", "nethaji", "nethra", "ngilyang", "nihad", "nihal",
    "niharika", "nijamudin", "nikhar", "nikita", "nikkita", "nilesh", "nimmagadda", "ningraj",
    "niraj", "niranjan", "niresh", "nirlep", "nirmal", "niruban", "nisha", "nishanth",
    "nishtha", "nishu", "nitai", "nitesh", "nithin", "nithis", "nithisha", "nitish",
    "nivedhitha", "nivedita", "nivetha", "nuthankumar", "odapalli", "oday", "offroll", "ojas",
    "ojasvee", "omika", "omkar", "ommen", "omnarayan", "omran", "oncall", "onkar",
    "ops", "order", "osama", "osamah", "oshin", "ovais", "oviya", "owais",
    "paari", "paarth", "pabbathi", "pabitra", "padala", "padam", "padamata", "padarthi",
    "padhiyar", "pagadala", "pahulpreet", "paidi", "pairvi", "pakija", "palak", "palakollu",
    "palakurthi", "palavesamoorthy", "palepally", "paleti", "pallab", "pallabothu", "pallani", "pallapu",
    "pallav", "palle", "pallvi", "palpesh", "paltu", "palvinder", "pamarthi", "pamu",
    "panchal", "panchami", "panchanan", "panchiri", "pandurang", "panjala", "pankaj", "pankesh",
    "pankhuri", "panneer", "pantadi", "panyala", "papai", "papan", "papolla", "pappu",
    "pappula", "papu", "parag", "parakh", "param", "paramesh", "paramjeet", "paramveer",
    "paranjit", "paranna", "parapati", "paras", "parashiv", "pareekshit", "paresh", "paridhi",
    "parihar", "parikshith", "parineeka", "parinita", "parish", "parisha", "paritosh", "parkash",
    "parlay", "parmar", "parmeet", "parmeeta", "parmesh", "parmeshvar", "parmeshwar", "parmeswar",
    "parminder", "parmjit", "parmod", "parnajit", "parosh", "parshant", "parshuram", "parthiban",
    "parthipan", "partyex", "parul", "parus", "parveen", "parvej", "parvesh", "pasalu",
    "pasupathi", "pathan", "pavan", "pavithra", "pavitra", "pawan", "pawnraj", "pedapudi",
    "pele", "people", "pettlu", "piyush", "ponvannan", "poorva", "porchelamban", "prabhakaran",
    "prabhat", "prabu", "pradhap", "pradip", "pradyuman", "pragadeeswaran", "pragnya", "pragyaratan",
    "prahlad", "prajakta", "prajot", "prajwal", "prakash", "prakhar", "prakriti", "pramod",
    "pranjal", "prasanna", "prasanth", "prashanth", "pratap", "prateek", "prathamesh", "prathap",
    "prathapa", "prathip", "prathvi", "pratima", "pratyaksh", "pratyush", "praveen", "praveena",
    "praveenkumar", "pravesh", "preetam", "preetha", "prem", "prema", "premaraju", "prerna",
    "prince", "prisha", "prithivi", "priyadarshni", "priyam", "priyansh", "priyanshu", "pruthvi",
    "pugalenthan", "pulkit", "punam", "pune", "puneeth", "punit", "punith", "purushotham",
    "pushpanathan", "pushparaj", "qasim", "qazi", "quazi", "qumruddin", "rabari", "rabbani",
    "rabin", "rabindra", "rabindranath", "rabish", "rabita", "rabiul", "rachael", "rachakonda",
    "rachamalla", "racharla", "rachna", "rachuri", "radhakrishna", "radheshyam", "rafik", "rafique",
    "ragani", "ragavan", "ragavendran", "raghav", "raghavendra", "raghavi", "raghu", "raghul",
    "raghunandan", "raghurukula", "raghuvamshi", "raghuveer", "raghuvindra", "raghvendra", "ragini", "ragul",
    "rahaman", "rahbar", "rahisuddin", "raj", "raja", "rajadurai", "rajaganapathy", "rajaguru",
    "rajasimman", "rajat", "rajbala", "rajbeer", "rajbir", "rajeev", "rajendiran", "rajesha",
    "rajeshkannan", "rajeshpandi", "rajkumar", "rajnesh", "rajnish", "rajveer", "rakesh", "rakibul",
    "rakshath", "rakshit", "rakshita", "rakshith", "rakshitha", "ramadasu", "ramalingam", "ramanan",
    "ramanand", "ramanjani", "ramaprakaash", "ramapriyan", "ramavtar", "rameshwar", "ramkrishnaiah", "ramu",
    "randeep", "raneda", "ranganath", "ranganatha", "ranjan", "ranjith", "rasmi", "ratan",
    "rathish", "ratnesh", "ratnim", "raushan", "raveendra", "ravikiran", "ravinandan", "ravindra",
    "raviraj", "ravisankar", "raviuddin", "ravneet", "rayna", "realestate", "rebanta", "regulatory",
    "remon", "rengaraja", "renugopal", "richa", "riddhi", "rihan", "rijvan", "rimsiya",
    "rinku", "rishabh", "rishath", "rishav", "rishi", "ritesh", "rithesh", "rithika",
    "rithish", "ritick", "ritik", "ritish", "rituraj", "ritweek", "riyaaz", "rohitash",
    "rohith", "roma", "roshani", "roshini", "roushan", "rovin", "ruby", "rudraprasad",
    "rudresh", "ruhi", "rukmini", "rupesh", "rushikesh", "rutuja", "rutvij", "saba",
    "sabapathy", "sabarish", "sachin", "sadakant", "sadakhat", "sadhana", "sagar", "sahana",
    "sahashpal", "saheem", "sahibjeet", "sahil", "sahithi", "sai", "saif", "saiful",
    "saikumar", "saiyad", "sajal", "sajay", "sajid", "sajjan", "sakeel", "sakhtivel",
    "saksham", "sakthipriya", "sakthivel", "salil", "salman", "saloni", "samantak", "samarjeet",
    "samarpita", "samastha", "samay", "sameen", "sameer", "samiulhaq", "sampath", "sampreeth",
    "samruddhi", "samson", "samyuktha", "sana", "sanal", "sandeep", "sandeepa", "sandesh",
    "sandesha", "sandip", "sangam", "sangamesha", "sangameshwar", "sangeeta", "sangeeth", "sangram",
    "sanjeet", "sanjeeth", "sanjeev", "sanjeevkumaran", "sanju", "sankar", "sanket", "sannia",
    "sanoop", "santhosh", "sanya", "sapana", "sapphire", "saransh", "saranya", "sarath",
    "sarathkumar", "sarathy", "sarfaraj", "sarita", "saruchi", "sarvendu", "sarwagya", "sasi",
    "sasikumar", "sasiraman", "satbirsingh", "satheesha", "sathishkumar", "sathya", "sathyakumar", "sathyaraj",
    "satish", "satishkumar", "satpal", "sattham", "satvinder", "satya", "satyabrat", "satyam",
    "satyaprakash", "satyaraj", "satyawan", "satyveer", "sauduzzaman", "saumya", "saurav", "saurbh",
    "savad", "sawlat", "sayal", "sayed", "sayeda", "seikar", "sekh", "selva",
    "selvamathan", "shahbaz", "shahid", "shahrukh", "shaik", "shaikh", "shailendra", "shakir",
    "shambhavi", "shankara", "shantanu", "sharanabasava", "sharath", "shashidhara", "shashikant", "shashikumar",
    "shashivarun", "sheik", "shekhar", "sheldon", "shendge", "shibin", "shimab", "shiv",
    "shiva", "shivakumar", "shivangi", "shivani", "shivaraju", "shivbrat", "shiwank", "shmad",
    "shobhit", "shonima", "shrawani", "shreedhar", "shreyansh", "shreyas", "shridhara", "shrinatha",
    "shrishti", "shrutig", "shubh", "shubham", "shubhangi", "shubhi", "shuvam", "sidaq",
    "siddaraju", "siddesh", "siddhant", "siddhartha", "simran", "sinchana", "sindhu", "siva",
    "sivakumar", "sivamalan", "sivaraman", "sivasakthi", "sivasankar", "sivasrilatha", "smiti", "smrithi",
    "snehitha", "sneya", "soban", "somashekhar", "somiya", "somnath", "sonam", "sonu",
    "sooraj", "sourabh", "spandan", "sravan", "sri", "sridevi", "sridhar", "sridharan",
    "sriganesh", "srikanth", "srikrishnan", "srilakshmi", "srinivas", "srinivasulu", "sriram", "sriranjani",
    "srishti", "srivalli", "srivatchav", "subash", "subinraj", "subodh", "subramani", "sudarshan",
    "sudeep", "sudhakar", "sudhakara", "sudhanshu", "sudhir", "sugapriya", "suhail", "suhas",
    "sujay", "sukriti", "sumankumar", "sumanth", "sumith", "sundar", "sundarapandiayn", "sunny",
    "suraj", "surbhit", "surendar", "surendhar", "surendra", "surentharan", "suresha", "sureshbabu",
    "suriyaprakash", "surya", "suryakant", "suryaprasath", "suseela", "sushant", "sushil", "sushma",
    "sushmitha", "suvangi", "suyog", "swagath", "swapnil", "swasthi", "syed", "syeda",
    "tabish", "tabita", "tabrez", "tadikamalla", "tadivalasa", "taduri", "tahera", "taj",
    "tajuddina", "tajul", "talha", "talukdar", "tamada", "tamal", "tamana", "tamanna",
    "tameem", "tamilmani", "tamilselvan", "tamizharasan", "tammina", "tammiri", "tamoghna", "tanay",
    "tanaya", "tangudu", "tania", "taniksha", "tanish", "tanisha", "tanishk", "tanishka",
    "tanishq", "taniya", "tanmaya", "tanniur", "tannu", "tanoy", "tanuj", "tanuka",
    "tanuku", "tanupriya", "tanush", "tanushpreet", "tanushree", "tanushri", "tanveer", "tanvir",
    "tanya", "tapan", "tapash", "tapasvi", "tapender", "tapeshwer", "tapodhan", "taprala",
    "tarachand", "taran", "tarana", "taranjeet", "taranpreet", "taranum", "tarasha", "tarendra",
    "tarini", "tarique", "tarjan", "tarminder", "tarneet", "taroun", "taru", "tarumuru",
    "tarun", "taruni", "tarunya", "tarushi", "tasmiya", "tasneem", "tatavrishi", "tathagat",
    "tathagata", "tatini", "tatiparthi", "tatipudi", "tatparya", "tatva", "taufik", "tauqeer",
    "tavish", "tavishi", "tayade", "tazeem", "tech", "technology", "teekam", "teerth",
    "teetoo", "tegpreet", "tej", "tejal", "tejas", "tejaskumar", "tejasvi", "tejaswani",
    "tejaswini", "tejendra", "tejesh", "tejinder", "tejpal", "tejveer", "tekumal", "temp",
    "test", "thadesar", "thadisina", "thagaram", "thalakayala", "thalari", "thamizhiniyan", "thamizhselvan",
    "thamodharan", "thangabalu", "thangaraj", "thangarasu", "thanish", "thanneru", "thanuj", "thanveer",
    "thanzoor", "tharun", "thati", "thatta", "thedla", "theerdhani", "thejas", "thejashree",
    "thennarasan", "thesiya", "thichana", "thikkavarapu", "thillari", "thiragabathina", "thiramdasu", "thirtha",
    "thirthraj", "thirumalai", "thirumalaivasan", "thirumalesha", "thirumurugan", "thirunavukarasu", "thiruvenkadasamy", "thiyagarajan",
    "thogata", "thokala", "thotakuri", "thoti", "thousif", "thulasiram", "thummala", "thunga",
    "thyagaraj", "thyagaraju", "tiara", "tiasha", "tijo", "tinagar", "tinku", "tippesh",
    "tippu", "tipu", "tirth", "tirthankar", "tirupathi", "tiruvedula", "tishya", "titan",
    "titendra", "titu", "tius", "tiya", "toheed", "tohid", "tokala", "tonmoy",
    "tony", "tosha", "tosif", "totan", "toushif", "trasha", "travel", "trayambaka",
    "treasury", "treena", "treessa", "trevor", "tribhuwan", "trilochan", "tripti", "trishita",
    "tristan", "trivendram", "truptesh", "trushant", "tuddu", "tufan", "ubais", "udai",
    "udaivir", "udashey", "uday", "udayagiri", "udayakumar", "udayan", "udaybhan", "udaykumar",
    "udayvir", "udbhav", "uddesh", "uddeshya", "uddhava", "uddish", "udesh", "udham",
    "udhay", "udhaya", "udhayam", "udhayanithi", "udhayaprakash", "udhayasankar", "udipta", "udit",
    "udita", "uditanshu", "uggina", "ujjal", "ujjawal", "ujjwala", "ujwal", "umadiya",
    "umair", "umakant", "umamaheswaran", "umang", "umapathi", "umapathy", "umar", "umashankar",
    "umeed", "umesh", "umeshbhai", "umit", "ummarasab", "unais", "unez", "unnatharaj",
    "upasna", "upender", "upendra", "upinder", "upneet", "uppala", "urja", "urmila",
    "urooz", "urshila", "urvashi", "urvi", "ushabh", "usham", "ushanshi", "ushrita",
    "usman", "uthandamani", "utkal", "utkarsha", "utpal", "utsab", "utsav", "uttam",
    "uttkarsh", "uzair", "vaani", "vachaspati", "vadakattu", "vaddeboina", "vaddi", "vaddiraju",
    "vadla", "vadlam", "vadlamudi", "vagarth", "vaghela", "vaibhavi", "vaibhaw", "vaidehi",
    "vaidhika", "vaidhya", "vaidika", "vaidya", "vairal", "vaisakhan", "vaishakh", "vaishali",
    "vaishanavi", "vaishnav", "vaishnu", "vajid", "vakkareni", "vakul", "vala", "valand",
    "vallabha", "vallapu", "valle", "vamshi", "vamsidhar", "vamsiprasad", "vanagarouthu", "vanapalli",
    "vanarigari", "vandana", "vandanapu", "vandit", "vandita", "vandrasi", "vanessa", "vanga",
    "vanik", "vanisha", "vankar", "vanposh", "vansh", "vanshaj", "vanshika", "vanshikha",
    "vanshita", "vanteddu", "vanya", "varad", "varadarajan", "varadha", "varasala", "vardhan",
    "varenya", "varija", "varinder", "varleen", "varna", "varnit", "varshaa", "varshitha",
    "vartika", "varul", "varuna", "varunan", "vasantha", "vasanthakumar", "vashishtha", "vashu",
    "vasi", "vasu", "vasudevan", "ved", "vedansh", "veena", "veeramanikandan", "veerareddy",
    "veeresh", "vellarasu", "velpula", "venkataramana", "venkatesulu", "venu", "venugopal", "venukumarsahu",
    "vettrivel", "vickky", "vicky", "victor", "vidushi", "vigneshwaran", "vihanas", "vijayashree",
    "vijender", "vijeth", "vikas", "vikash", "vikki", "vikrm", "vinayak", "vineet",
    "vineeth", "vinesh", "vinit", "vinith", "vinod", "vinodaraju", "vinodh", "vinodkumar",
    "vinoth", "vipin", "viren", "virender", "virendra", "virupaksha", "vishakha", "vishav",
    "vishnu", "vishnudevan", "vishnuvardhana", "vishwas", "vishwavinayaka", "vitthal", "vivekanand", "vrashali",
    "vukkadapu", "wade", "waheed", "waheeduddin", "wajhul", "wajid", "wakib", "warehouse",
    "waseef", "waseem", "washi", "washter", "wasim", "wasiullah", "watan", "watsal",
    "web", "welcome", "whistle", "wilfin", "wilfred", "winnie", "xaviour", "yaabish",
    "yaana", "yabesh", "yachika", "yaddla", "yadhukrishnan", "yadlapalli", "yadunandana", "yadvendra",
    "yaganti", "yagna", "yagya", "yajash", "yakshita", "yalagala", "yalalla", "yalamanchili",
    "yama", "yaman", "yamanur", "yameen", "yameena", "yaminee", "yampati", "yaseen",
    "yasharth", "yashas", "yashasav", "yashash", "yashashvee", "yashasvi", "yashaswi", "yashaswini",
    "yashaswita", "yashavanth", "yashawant", "yashawnth", "yashi", "yashika", "yashita", "yashjeet",
    "yashkumar", "yashoda", "yashodhan", "yashpal", "yashraj", "yashu", "yashvardhan", "yashveer",
    "yashvir", "yashwant", "yashwanth", "yashwi", "yasin", "yasir", "yasmeen", "yaswant",
    "yaswanth", "yathaarth", "yatharth", "yathartha", "yathish", "yatin", "yatindra", "yavvari",
    "yedakula", "yeguru", "yelampalli", "yelisetty", "yellala", "yellapu", "yellisetty", "yepuri",
    "yerni", "yerra", "yerraguntla", "yerramanedi", "yeshupal", "yeshwanth", "yesu", "yog",
    "yoga", "yogananda", "yogaraj", "yogashree", "yogender", "yogendra", "yogesh", "yogesha",
    "yogeshkumar", "yogeshwar", "yogeskumaran", "yogiraj", "yogita", "yomesh", "youki", "yudhishthir",
    "yudhister", "yug", "yugal", "yugam", "yugandhar", "yugansh", "yugeen", "yukta",
    "yuraj", "yusra", "yuvaraj", "zaheen", "zaheer", "zahid", "zaiba", "zaid",
    "zaif", "zain", "zainab", "zainub", "zala", "zamaan", "zamaluddin", "zameer",
    "zamil", "zaved", "zayd", "zeehan", "zeenat", "zehnuddin", "zehra", "zeshan",
    "ziauh", "ziaul", "zikra", "zilu", "zingmai", "ziya", "ziyaad", "ziyaul",
    "zobair", "zoheb", "zohran", "zomato", "zoya", "zte", "zubair", "zuha",
}

# CSV last names: curated Hindu/Sikh/South Indian/Odia/Tribal surnames only.
# Muslim, first-name-only, and bad-data entries removed.
CSV_INDIAN_LAST_NAMES = {
    "ahlawat", "ahluwalia", "ahuja", "anjaneyulu", "awasthi", "bagga", "bairagi", "bakshi",
    "balla", "bandari", "bansal", "bansode", "basavanagowda", "bathla", "bera", "bhandare",
    "bhasin", "bhatnagar", "bhushan", "bihani", "biradar", "borgoyari", "chadha", "chandel",
    "chandravanshi", "chary", "chaubey", "chaurasia", "chavan", "chhabra", "chittora", "choudhary",
    "chouhan", "chourasiya", "daga", "dagar", "dahiya", "dange", "debnath", "devnani",
    "dhakad", "dhankhar", "dhiman", "dhindsa", "dhingra", "dhir", "dhotre", "dhumal",
    "dinda", "dsouza", "dua", "dube", "dugar", "duggal", "dureja", "dutt",
    "ekka", "elangovan", "elumalai", "gagneja", "gambhir", "gaur", "giri", "goel",
    "gore", "gosain", "gosavi", "goswami", "goud", "gowtham", "goyal", "gulati",
    "guleria", "inamdar", "ingle", "israni", "jadav", "jaiswal", "jaiswar", "jalan",
    "jangid", "jassal", "jena", "jha", "jindal", "joshitha", "kadam", "kalra",
    "kamboj", "kanojia", "kanojiya", "kansal", "kardam", "kashyap", "kataria", "kathuria",
    "kaul", "kehar", "khandelwal", "kharbanda", "khatana", "khera", "kohli", "koranga",
    "kothidar", "kujur", "kukreja", "kumawat", "kushwah", "kutumb", "lakhera", "lakra",
    "lamba", "laskar", "lather", "lenka", "linganagowda", "lingappa", "lohia", "lohiya",
    "londhe", "lovaraju", "loya", "luthra", "mahajan", "mahata", "mahato", "maheshwari",
    "mahto", "maity", "majumder", "makkar", "makvana", "makwana", "mali", "malve",
    "mandhani", "mane", "mangla", "mathur", "mehra", "mendiratta", "menezes", "mistry",
    "mittal", "mohanty", "mourya", "munda", "nagpal", "narang", "narayan", "naskar",
    "nayak", "nayar", "negi", "nigam", "oberoi", "ohri", "ojha", "oswal",
    "pahwa", "paliwal", "panchal", "pandit", "pant", "papneja", "parashar", "pareek",
    "parihar", "parmar", "patani", "patidar", "patra", "patwa", "phul", "porwal",
    "pundir", "puri", "purswani", "rabha", "raghuvanshi", "raheja", "rai", "rajak",
    "rajasekhar", "rajawat", "rajendran", "rajpurohit", "rathi", "rawal", "rout", "sachdeva",
    "sah", "sahni", "sahu", "saini", "saluja", "samant", "sambharwal", "saran",
    "saroj", "savanur", "sawant", "sawhney", "sehgal", "selvaraj", "sethy", "shaw",
    "shishodia", "shokeen", "shrivastava", "singhal", "singla", "sirohi", "somani", "sonawane",
    "sood", "srikanth", "srinivas", "srinivasarao", "srivastav", "surana", "suryawanshi", "suthar",
    "swain", "tak", "talwar", "tamang", "tandon", "taneja", "tangade", "tewari",
    "thakor", "thapa", "tomer", "trehan", "tyagi", "uniyal", "upadhayay", "upreti",
    "utekar", "vaghela", "vaid", "varshney", "vashisht", "vasudeva", "vishwakarma", "vohra",
    "wadhawan", "wadhwa", "waghe", "waghmare", "wahi", "walanj", "walia", "wankhede",
    "ware", "warjukar", "wason", "xalxo", "xavier", "zaveri", "zirpe", "zutshi",
}

# ──────────────────────────────────────────────────────────────────────────────
# HIGH-QUALITY INDIAN LAST NAMES — from last names.csv (545 curated surnames).
# Clean, regionally comprehensive Indian surnames. Merged into indian_last
# in build_training_data().
# ──────────────────────────────────────────────────────────────────────────────
HIGH_QUALITY_LAST_NAMES = {
    "acharya", "agarwal", "agate", "aggarwal", "agrawal", "ahluwalia", "ahuja", "amble",
    "anand", "andra", "anne", "apte", "arora", "arya", "atwal", "aurora",
    "babu", "badal", "badami", "bahl", "bahri", "bail", "bains", "bajaj",
    "bajwa", "bakshi", "bal", "bala", "balakrishnan", "balan", "balasubramanian", "balay",
    "bali", "bandi", "banerjee", "banik", "bansal", "barad", "baral", "baria",
    "barman", "basak", "bassi", "basu", "bath", "batra", "batta", "bava",
    "bawa", "bedi", "behl", "ben", "bera", "bhagat", "bhakta", "bhalla",
    "bhandari", "bhardwaj", "bhargava", "bhasin", "bhat", "bhatia", "bhatnagar", "bhatt",
    "bhattacharyya", "bhatti", "bhavsar", "bir", "biswas", "boase", "bobal", "bora",
    "borah", "borde", "borra", "bose", "brahmbhatt", "brar", "buch", "bumb",
    "butala", "chacko", "chad", "chada", "chadha", "chahal", "chakrabarti", "chakraborty",
    "chana", "chand", "chanda", "chander", "chandra", "chandran", "char", "chatterjee",
    "chaudhari", "chaudhary", "chaudhry", "chaudhuri", "chaudry", "chauhan", "chawla", "cheema",
    "cherian", "chhabra", "chokshi", "chopra", "choudhary", "choudhry", "choudhury", "chowdhury",
    "comar", "contractor", "dada", "dalal", "dani", "dar", "dara", "das",
    "dasgupta", "dash", "dass", "date", "datta", "dave", "dayal", "de",
    "deep", "deo", "deol", "desai", "deshmukh", "deshpande", "devan", "devi",
    "dewan", "dey", "dhaliwal", "dhar", "dhawan", "dhillon", "dhingra", "din",
    "divan", "dixit", "doctor", "dora", "doshi", "dua", "dube", "dubey",
    "dugal", "dugar", "dutt", "dutta", "dyal", "edwin", "gaba", "gade",
    "gala", "gandhi", "ganesan", "ganesh", "ganguly", "gara", "garde", "garg",
    "gera", "ghose", "ghosh", "gill", "goda", "goel", "gokhale", "gola",
    "gole", "golla", "gopal", "goswami", "gour", "goyal", "grewal", "grover",
    "guha", "gulati", "gupta", "halder", "handa", "hans", "hari", "hayer",
    "hayre", "hegde", "hora", "issac", "iyengar", "iyer", "jaggi", "jain",
    "jani", "jayaraman", "jha", "jhaveri", "johal", "joshi", "kadakia", "kade",
    "kakar", "kala", "kale", "kalita", "kalla", "kamdar", "kanda", "kannan",
    "kant", "kapadia", "kapoor", "kapur", "kar", "kara", "karan", "kari",
    "karnik", "karpe", "kashyap", "kata", "kaul", "kaur", "keer", "khalsa",
    "khanna", "khare", "khatri", "khosla", "khurana", "kibe", "kohli", "konda",
    "korpal", "koshy", "kota", "kothari", "krish", "krishna", "krishnamurthy", "krishnan",
    "kulkarni", "kumar", "kumer", "kunda", "kurian", "kuruvilla", "lad", "lal",
    "lala", "lall", "lalla", "lanka", "lata", "loke", "loyal", "luthra",
    "madan", "magar", "mahajan", "mahal", "maharaj", "majumdar", "malhotra", "mall",
    "mallick", "mammen", "mand", "manda", "mandal", "mander", "mane", "mangal",
    "mangat", "mani", "mann", "mannan", "manne", "mathai", "mathur", "matthai",
    "meda", "mehan", "mehra", "mehrotra", "mehta", "meka", "memon", "menon",
    "merchant", "minhas", "mishra", "misra", "mistry", "mital", "mitra", "mittal",
    "mitter", "modi", "mody", "mohan", "mohanty", "morar", "more", "mukherjee",
    "mukhopadhyay", "muni", "munshi", "murthy", "murty", "mutti", "nadig", "nadkarni",
    "nagar", "nagarajan", "nagi", "naidu", "naik", "nair", "nanda", "narain",
    "narang", "narasimhan", "narayan", "narayanan", "narula", "natarajan", "nath", "natt",
    "nayak", "nayar", "nazareth", "nigam", "nori", "oak", "om", "oommen",
    "oza", "padmanabhan", "pai", "pal", "palan", "pall", "palla", "panchal",
    "pandey", "pandit", "pandya", "pant", "parekh", "parikh", "parmar", "parmer",
    "parsa", "patel", "pathak", "patil", "patla", "pau", "peri", "pillai",
    "pillay", "pingle", "prabhakar", "prabhu", "pradhan", "prakash", "prasad", "prashad",
    "puri", "purohit", "radhakrishnan", "raghavan", "rai", "raj", "raja", "rajagopal",
    "rajagopalan", "rajan", "raju", "ram", "rama", "ramachandran", "ramakrishnan", "raman",
    "ramanathan", "ramaswamy", "ramesh", "rana", "randhawa", "ranganathan", "rao", "rastogi",
    "ratta", "rattan", "ratti", "rau", "raval", "ravel", "ravi", "ray",
    "reddy", "rege", "rout", "roy", "sabharwal", "sachar", "sachdev", "sachdeva",
    "sagar", "saha", "sahni", "sahota", "saini", "salvi", "sama", "sami",
    "sampath", "samra", "sandal", "sandhu", "sane", "sangha", "sanghvi", "sani",
    "sankar", "sankaran", "sant", "saraf", "saran", "sarin", "sarkar", "sarma",
    "sarna", "sarraf", "sastry", "sathe", "savant", "sawhney", "saxena", "sehgal",
    "sekhon", "sem", "sen", "sengupta", "seshadri", "seth", "sethi", "setty",
    "sha", "shah", "shan", "shankar", "shanker", "sharaf", "sharma", "shenoy",
    "shere", "sheth", "shetty", "shroff", "shukla", "sibal", "sidhu", "singh",
    "singhal", "sinha", "sodhi", "solanki", "som", "soman", "soni", "sood",
    "sridhar", "srinivas", "srinivasan", "srivastava", "subramaniam", "subramanian", "sule", "sundaram",
    "sunder", "sur", "sura", "suresh", "suri", "swaminathan", "swamy", "tailor",
    "tak", "talwar", "tandon", "taneja", "tank", "tara", "tata", "tella",
    "thaker", "thakkar", "thakur", "thaman", "tiwari", "toor", "tripathi", "trivedi",
    "upadhyay", "uppal", "vaidya", "vala", "varghese", "varkey", "varma", "varty",
    "varughese", "vasa", "venkataraman", "venkatesh", "verma", "vig", "virk", "viswanathan",
    "vohra", "vora", "vyas", "wable", "wadhwa", "wagle", "wali", "walia",
    "walla", "warrior", "wason", "yadav", "yogi", "yohannan", "zacharia", "zachariah",
}


# Known cross-regional ambiguous names to always exclude from both sides
AMBIGUOUS_EXCLUSIONS = frozenset([
    "khan", "ali", "hassan", "ahmed", "sheikh", "islam", "malik",
    "hussain", "rahman", "rahim", "karim", "sultana", "begum",
    "mirza", "siddiqui", "ansari", "chowdhury",
    "singh",  # Sikh — ambiguous, can be Indian or not in isolation
    "lee", "park", "chen", "wang", "zhang",
    "omar", "joseph", "george", "thomas", "john", "james", "michael",
    "ram", "lal",  # Too short / too ambiguous
    "jolly",   # Ambiguous: Indian Christian surname (Kerala) but also English word
    "amal",    # Ambiguous: Indian (Kerala/Sanskrit) + Arabic (both valid)
    "anand",   # Ambiguous: used as both first and last name across cultures
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

    # Keep curated and CSV first-name sets SEPARATE so we can guarantee that
    # hand-curated names (arjun, rohit, dhruv, …) are never randomly dropped
    # when balancing to a 2:1 ratio.  Only the CSV supplement is sampled.
    indian_first_curated = _normalize(INDIAN_FIRST_NAMES)
    indian_first_csv = _normalize(CSV_INDIAN_FIRST_NAMES)
    indian_last = _normalize(INDIAN_LAST_NAMES | CSV_INDIAN_LAST_NAMES | HIGH_QUALITY_LAST_NAMES)
    non_indian_first = _normalize(NON_INDIAN_FIRST_NAMES)
    non_indian_last = _normalize(NON_INDIAN_LAST_NAMES)

    print(f"--- Raw counts ---")
    print(f"  Indian first (curated): {len(indian_first_curated)}")
    print(f"  Indian first (CSV supplement): {len(indian_first_csv)}")
    print(f"  Indian last: {len(indian_last)}")
    print(f"  Non-Indian first: {len(non_indian_first)}")
    print(f"  Non-Indian last: {len(non_indian_last)}")

    # Remove ambiguous names and overlaps
    ambiguous = set()

    all_indian_first = indian_first_curated | indian_first_csv
    first_overlap = all_indian_first & non_indian_first
    ambiguous.update(first_overlap)
    indian_first_curated -= first_overlap
    indian_first_csv -= first_overlap
    non_indian_first -= first_overlap

    last_overlap = indian_last & non_indian_last
    ambiguous.update(last_overlap)
    indian_last -= last_overlap
    non_indian_last -= last_overlap

    for name in AMBIGUOUS_EXCLUSIONS:
        n = name.lower().strip()
        indian_first_curated.discard(n)
        indian_first_csv.discard(n)
        indian_last.discard(n)
        non_indian_first.discard(n)
        non_indian_last.discard(n)
        ambiguous.add(n)

    print(f"\n--- After ambiguous removal ---")
    print(f"  Indian first (curated): {len(indian_first_curated)}")
    print(f"  Indian first (CSV supplement): {len(indian_first_csv)}")
    print(f"  Indian last: {len(indian_last)}")
    print(f"  Non-Indian first: {len(non_indian_first)}")
    print(f"  Non-Indian last: {len(non_indian_last)}")
    print(f"  Ambiguous dropped: {len(ambiguous)}")

    # Balance classes — cap majority at 2x minority.
    # For FIRST NAMES: always include ALL hand-curated names; randomly sample from
    # the CSV supplement to fill the remaining budget.  This guarantees "arjun",
    # "rohit", "dhruv" etc. are never dropped due to random downsampling.
    def _balance_first(
        curated: set[str], supplement: set[str], neg: set[str]
    ) -> tuple[set[str], set[str]]:
        target = len(neg) * 2
        if len(curated) >= target:
            # Curated alone already fills the 2:1 budget (edge case)
            pos = set(random.sample(sorted(curated), target))
            print(f"  Indian first: curated ({len(curated)}) > target ({target}), sampled")
        else:
            remaining = target - len(curated)
            pool = sorted(supplement)
            extra = set(random.sample(pool, min(remaining, len(pool))))
            pos = curated | extra
            print(f"  Indian first: {len(curated)} curated + {len(extra)} CSV = {len(pos)}")
        return pos, neg

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

    indian_first, non_indian_first = _balance_first(
        indian_first_curated, indian_first_csv, non_indian_first
    )
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
