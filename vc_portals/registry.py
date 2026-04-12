from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VCFund:
    name: str
    founded_year: int = 0
    notable_investments: str = ""
    investment_focus: str = ""
    fund_type: str = ""  # "Seed Stage", "Early Stage", "Growth Stage"
    recent_fund_size: str = ""
    key_people: str = ""
    job_portal_url: str = ""
    job_portal_type: str = ""  # "lever", "greenhouse", "pyjamahr", "getro", "consider", "custom", ""
    contact_email: str = ""


# All VCs from the user's list with known job portal URLs
VC_REGISTRY: list[VCFund] = [
    # ── Core Indian VCs ────────────────────────────────────────────────────────
    VCFund("3one4 Capital", 2016, "Licious, Jupiter, Koo", "Consumer Internet, Fintech, Digital Health", "Seed Stage", "$100M", "Pranav Pai, Siddarth Pai",
           # No dedicated portfolio job board found; 3one4capital.com/portfolio has no jobs link.
           # Wellfound lists their own VC-internal roles only (0 open as of 2025).
           "", ""),
    VCFund("Accel India", 2008, "Flipkart, Freshworks, Swiggy", "Consumer, SaaS, Fintech", "Early Stage", "$550M", "Subrata Mitra, Prashanth Prakash", "https://jobs.accel.com/jobs", "getro"),
    VCFund("Blume Ventures", 2010, "Dunzo, Unacademy, HealthifyMe", "Early-stage, Seed", "Early Stage", "$102M", "Karthik Reddy, Sanjay Nath", "https://jobs.blume.vc/jobs", "getro"),
    VCFund("Chiratae Ventures", 2006, "Lenskart, Myntra, FirstCry", "Consumer Media, SaaS, Health Tech", "Growth Stage", "$337M", "Sudhir Sethi, TC Meenakshisundaram", "https://careers.chiratae.com/jobs", "consider"),
    VCFund("India Quotient", 2012, "ShareChat, Lendingkart, Sugar", "Tech, Fintech", "Seed Stage", "$60M", "Anand Lunia, Madhukar Sinha"),
    VCFund("Kalaari Capital", 2006, "Dream11, Snapdeal, Urban Ladder", "Consumer, Deep Tech", "Early Stage", "$290M", "Vani Kola, Rajesh Raju",
           # Custom WordPress job board on their own domain — no Lever/Greenhouse/Getro
           "https://kalaari.com/job-board/", "custom"),
    VCFund("Lightbox Ventures", 2014, "Rebel Foods, Furlenco, Dunzo", "Consumer Tech", "Early Stage", "$200M", "Siddharth Talwar, Prashant Mehta", "", "", "talent@lightbox.vc"),
    VCFund("Lightspeed Venture Partners", 2000, "OYO, Udaan, ShareChat", "Consumer, Enterprise, Health Tech", "Early to Growth Stage", "$4B", "Bejul Somaia, Hemant Mohapatra", "https://jobs.lsvp.com/jobs", "consider"),
    VCFund("Z47 (Matrix Partners India)", 2006, "Ola, Practo, Quikr", "Consumer, Enterprise", "Early Stage", "$300M", "Tarun Davda",
           # No portfolio job board found on z47.com or any aggregator after Matrix→Z47 rebrand.
           # Founders/candidates directed to email namaste@z47.com
           "", ""),
    VCFund("Nexus Venture Partners", 2006, "Postman, Delhivery", "Tech, Consumer Services", "Growth Stage", "$450M", "Naren Gupta, Sandeep Singhal", "https://jobs.nexusvp.com/jobs", "consider"),
    VCFund("Omnivore Partners", 2010, "Stellapps, DeHaat, Reshamandi", "Agritech, Foodtech", "Seed to Early Stage", "$100M", "Mark Kahn, Jinesh Shah", "https://jobs.omnivore.vc/jobs", "getro"),
    VCFund("Elevation Capital (SAIF)", 2001, "Paytm, BookMyShow, Swiggy", "Consumer, SaaS, Logistics", "Growth Stage", "$1.8B", "Ravi Adusumalli, Mukul Arora",
           # Careers page exists but lists only VC-internal roles, not portfolio company jobs.
           # No Getro/Greenhouse/Lever portfolio board found.
           "https://elevationcapital.com/careers", "custom"),
    VCFund("Peak XV (Sequoia India)", 2006, "Byju's, Zomato, OYO", "Tech, Consumer", "Growth Stage", "$1.35B", "Shailendra Singh, GV Ravishankar", "https://careers.peakxv.com/jobs", "consider"),
    VCFund("Surge (Peak XV Accelerator)", 2019, "Khatabook, Cred, Groww", "Seed Stage, Consumer, Fintech", "Seed Stage", "$200M", "Rajan Anandan, Shailendra Singh", "https://jobs.surgeahead.com/jobs", "consider"),
    VCFund("Stellaris Venture Partners", 2016, "Mamaearth, mFine", "Tech, Consumer", "Early Stage", "$160M", "Ritesh Banglani, Alok Goyal",
           # Listed on jobsinvc.getro.com but page says "no jobs relevant to this board".
           # Direct website: stellarisvp.com has a Talent Acquisition contact but no job board.
           "", ""),
    VCFund("Tiger Global Management", 2001, "Flipkart, Ola, Razorpay", "Tech, Consumer, Media", "Growth Stage", "$6.7B", "Scott Shleifer, Lee Fixel"),
    VCFund("Titan Capital", 2015, "Razorpay, Khatabook, Mamaearth", "Tech, Consumer, Fintech", "Seed Stage", "$40M", "Kunal Bahl, Rohit Bansal"),
    VCFund("Together Fund", 2021, "Spendflo, Spry, Kula", "SaaS, Enterprise Software", "Early Stage", "$85M", "Girish Mathrubootham, Manav Garg",
           # No portfolio job board found on together.fund or any aggregator.
           # Contact via together.fund/contact
           "", ""),
    VCFund("YourNest Venture Capital", 2011, "Uniphore, MyGate, Cron AI", "Tech, Deep Tech, IoT", "Seed Stage", "$45M", "Sunil Goyal, Girish Shivani", "https://app.pyjamahr.com/careers?company=YourNest%20Venture%20Capital&company_uuid=987EE7EF32", "pyjamahr"),

    # ── Global VCs with India presence ─────────────────────────────────────────
    VCFund("Bessemer Venture Partners", 2007, "Swiggy, Meesho, Turtlemint", "Consumer, SaaS, Fintech", "Growth Stage", "$2.5B", "Vishal Gupta, Anant Vidur Puri", "https://jobs.bvp.com/jobs", "consider"),
    VCFund("General Catalyst", 2000, "Stripe, Airbnb, Snap", "Consumer, Enterprise, Health Tech", "Growth Stage", "$6B", "Hemant Taneja, Joel Cutler", "https://jobs.generalcatalyst.com/jobs", "getro"),
    VCFund("Antler India", 2017, "Multiverse Computing, Willo", "Deep Tech, SaaS, Consumer", "Seed Stage", "$300M", "Nitin Sharma, Rajiv Srivatsa", "https://careers.antler.co/jobs", "getro"),
    VCFund("B Capital Group", 2015, "Bizongo, KiotViet, Coda", "B2B Tech, Enterprise, Fintech", "Growth Stage", "$2.1B", "Howard Morgan, Eduardo Saverin", "https://jobs.b.capital/jobs", "getro"),
    VCFund("Norwest Venture Partners", 1961, "Pepperfry, Quikr, Swiggy", "Consumer, Enterprise, Healthcare", "Growth Stage", "$2B", "Promod Haque, Matthew Howard", "https://careers.nvp.com/jobs", "consider"),

    # ── Other Indian VCs (no verified portfolio job board) ─────────────────────
    VCFund("Aavishkaar Capital", 2001, "Agrostar, Nepra, Vortex", "Impact Investment, Financial Services", "Growth Stage", "$300M", "Vineet Rai, Sushma Kaushik"),
    VCFund("Alfa Ventures", 2017, "Moglix, Yulu", "Tech, Consumer", "Early Stage", "$25M", "Gautam Mehra, Manish Arora"),
    VCFund("Ankur Capital", 2014, "CropIn, ERC Eye Care, StringBio", "Agritech, Healthtech, Edtech", "Seed Stage", "$50M", "Ritu Verma, Rema Subramanian"),
    VCFund("Aspada / Lightrock India", 2013, "Capital Float, LEAP India", "Agriculture, Healthcare, Financial Inclusion", "Growth Stage", "$100M", "Thomas Hyland, Kartik Srivatsa"),
    VCFund("Beenext", 2015, "Shadowfax, Open", "Tech, Fintech", "Seed Stage", "$110M", "Teruhide Sato",
           # Uses Snaphunt (a Beenext portfolio company) for portfolio company job listings
           "https://beenext.snaphunt.com/", "custom"),
    VCFund("Bharat Innovation Fund", 2018, "ToneTag, Entropik Tech", "Deep Tech", "Growth Stage", "$100M", "Ashwin Raguraman"),
    VCFund("Inventus Capital Partners", 2007, "PolicyBazaar, Insta Health", "Tech, Consumer", "Growth Stage", "$51M", "Kanwaljit Singh, Rutvik Doshi"),
    VCFund("Kae Capital", 2012, "1mg, Porter, Fynd", "Tech-enabled startups", "Seed Stage", "$50M", "Sasha Mirchandani, Gaurav Chaturvedi",
           # Custom WordPress job board on kae-capital.com (not Getro/Greenhouse/Lever)
           "https://kae-capital.com/about-us/careers/", "custom"),
    VCFund("Omidyar Network India", 2008, "Dailyhunt, Pratilipi, ZestMoney", "Fintech, Edtech, Digital Tech", "Early to Growth Stage", "$250M", "Roopa Kudva, Jayant Sinha",
           # Global Omidyar Network uses Greenhouse; India jobs are mixed in with global listings.
           # No separate India-only portal found. Current openings are US-focused.
           "https://job-boards.greenhouse.io/omidyarnetwork", "greenhouse"),
    VCFund("Prime Venture Partners", 2011, "Ezetap, Sigtuple", "Tech, Fintech", "Growth Stage", "$72M", "Sanjay Swamy, Amit Somani",
           # Listed on jobsinvc.getro.com/companies/primevp but currently shows no active jobs.
           # primevp.in has no jobs section. Best entry point remains the Getro board.
           "https://jobsinvc.getro.com/companies/primevp", "getro"),
    VCFund("Qualcomm Ventures", 2000, "Jio Platforms, Ninjacart, Zuddl", "Mobile, AI, Deep Tech", "Early to Growth Stage", "$1B", "Quinn Li, Varsha Tagare"),
]
