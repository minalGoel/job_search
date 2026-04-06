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
    job_portal_type: str = ""  # "lever", "greenhouse", "pyjamahr", "custom", ""
    contact_email: str = ""


# All VCs from the user's list with known job portal URLs
VC_REGISTRY: list[VCFund] = [
    VCFund("3one4 Capital", 2016, "Licious, Jupiter, Koo", "Consumer Internet, Fintech, Digital Health", "Seed Stage", "$100M", "Pranav Pai, Siddarth Pai"),
    VCFund("Accel India", 2008, "Flipkart, Freshworks, Swiggy", "Consumer, SaaS, Fintech", "Early Stage", "$550M", "Subrata Mitra, Prashanth Prakash", "https://jobs.accel.com/jobs", "custom"),
    VCFund("Blume Ventures", 2010, "Dunzo, Unacademy, HealthifyMe", "Early-stage, Seed", "Early Stage", "$102M", "Karthik Reddy, Sanjay Nath"),
    VCFund("Chiratae Ventures", 2006, "Lenskart, Myntra, FirstCry", "Consumer Media, SaaS, Health Tech", "Growth Stage", "$337M", "Sudhir Sethi, TC Meenakshisundaram"),
    VCFund("India Quotient", 2012, "ShareChat, Lendingkart, Sugar", "Tech, Fintech", "Seed Stage", "$60M", "Anand Lunia, Madhukar Sinha"),
    VCFund("Kalaari Capital", 2006, "Dream11, Snapdeal, Urban Ladder", "Consumer, Deep Tech", "Early Stage", "$290M", "Vani Kola, Rajesh Raju", "https://kalaari.com/jobs/", "custom"),
    VCFund("Lightbox Ventures", 2014, "Rebel Foods, Furlenco, Dunzo", "Consumer Tech", "Early Stage", "$200M", "Siddharth Talwar, Prashant Mehta", "", "", "talent@lightbox.vc"),
    VCFund("Lightspeed Venture Partners", 2000, "OYO, Udaan, ShareChat", "Consumer, Enterprise, Health Tech", "Early to Growth Stage", "$4B", "Bejul Somaia, Hemant Mohapatra", "https://lsvp.com/jobs/", "custom"),
    VCFund("Z47 (Matrix Partners India)", 2006, "Ola, Practo, Quikr", "Consumer, Enterprise", "Early Stage", "$300M", "Tarun Davda"),
    VCFund("Nexus Venture Partners", 2006, "Postman, Delhivery", "Tech, Consumer Services", "Growth Stage", "$450M", "Naren Gupta, Sandeep Singhal", "https://jobs.nexusvp.com/jobs", "custom"),
    VCFund("Omnivore Partners", 2010, "Stellapps, DeHaat, Reshamandi", "Agritech, Foodtech", "Seed to Early Stage", "$100M", "Mark Kahn, Jinesh Shah", "https://jobs.omnivore.vc/jobs", "custom"),
    VCFund("Elevation Capital (SAIF)", 2001, "Paytm, BookMyShow, Swiggy", "Consumer, SaaS, Logistics", "Growth Stage", "$1.8B", "Ravi Adusumalli, Mukul Arora", "https://elevationcapital.com/careers", "custom"),
    VCFund("Peak XV (Sequoia India)", 2006, "Byju's, Zomato, OYO", "Tech, Consumer", "Growth Stage", "$1.35B", "Shailendra Singh, GV Ravishankar", "https://careers.peakxv.com/jobs", "custom"),
    VCFund("Stellaris Venture Partners", 2016, "Mamaearth, mFine", "Tech, Consumer", "Early Stage", "$160M", "Ritesh Banglani, Alok Goyal", "https://www.stellarisvp.com/opportunities/", "custom"),
    VCFund("Tiger Global Management", 2001, "Flipkart, Ola, Razorpay", "Tech, Consumer, Media", "Growth Stage", "$6.7B", "Scott Shleifer, Lee Fixel"),
    VCFund("Titan Capital", 2015, "Razorpay, Khatabook, Mamaearth", "Tech, Consumer, Fintech", "Seed Stage", "$40M", "Kunal Bahl, Rohit Bansal"),
    VCFund("Together Fund", 2021, "Spendflo, Spry, Kula", "SaaS, Enterprise Software", "Early Stage", "$85M", "Girish Mathrubootham, Manav Garg"),
    VCFund("YourNest Venture Capital", 2011, "Uniphore, MyGate, Cron AI", "Tech, Deep Tech, IoT", "Seed Stage", "$45M", "Sunil Goyal, Girish Shivani", "https://app.pyjamahr.com/careers?company=YourNest%20Venture%20Capital&company_uuid=987EE7EF32", "pyjamahr"),
    VCFund("Aavishkaar Capital", 2001, "Agrostar, Nepra, Vortex", "Impact Investment, Financial Services", "Growth Stage", "$300M", "Vineet Rai, Sushma Kaushik"),
    VCFund("Alfa Ventures", 2017, "Moglix, Yulu", "Tech, Consumer", "Early Stage", "$25M", "Gautam Mehra, Manish Arora"),
    VCFund("Ankur Capital", 2014, "CropIn, ERC Eye Care, StringBio", "Agritech, Healthtech, Edtech", "Seed Stage", "$50M", "Ritu Verma, Rema Subramanian"),
    VCFund("Aspada / Lightrock India", 2013, "Capital Float, LEAP India", "Agriculture, Healthcare, Financial Inclusion", "Growth Stage", "$100M", "Thomas Hyland, Kartik Srivatsa"),
    VCFund("Beenext", 2015, "Shadowfax, Open", "Tech, Fintech", "Seed Stage", "$110M", "Teruhide Sato"),
    VCFund("Bharat Innovation Fund", 2018, "ToneTag, Entropik Tech", "Deep Tech", "Growth Stage", "$100M", "Ashwin Raguraman"),
    VCFund("Inventus Capital Partners", 2007, "PolicyBazaar, Insta Health", "Tech, Consumer", "Growth Stage", "$51M", "Kanwaljit Singh, Rutvik Doshi"),
    VCFund("Kae Capital", 2012, "1mg, Porter, Fynd", "Tech-enabled startups", "Seed Stage", "$50M", "Sasha Mirchandani, Gaurav Chaturvedi"),
    VCFund("Norwest Venture Partners", 1961, "Pepperfry, Quikr", "Consumer, Enterprise, Healthcare", "Growth Stage", "$2B", "Promod Haque, Matthew Howard"),
    VCFund("Omidyar Network India", 2008, "Dailyhunt, Pratilipi, ZestMoney", "Fintech, Edtech, Digital Tech", "Early to Growth Stage", "$250M", "Roopa Kudva, Jayant Sinha"),
    VCFund("Prime Venture Partners", 2011, "Ezetap, Sigtuple", "Tech, Fintech", "Growth Stage", "$72M", "Sanjay Swamy, Amit Somani"),
    VCFund("Qualcomm Ventures", 2000, "Jio Platforms, Ninjacart, Zuddl", "Mobile, AI, Deep Tech", "Early to Growth Stage", "$1B", "Quinn Li, Varsha Tagare"),
]
