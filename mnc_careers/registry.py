from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MNC:
    name: str
    careers_url: str
    delhi_ncr_office: str = ""  # "Gurugram", "Noida", "Delhi", etc.
    pm_search_url: str = ""  # Pre-built URL filtered for PM roles in Delhi NCR
    notes: str = ""


# US MNCs with known offices in Delhi NCR
# Careers URLs are their main careers pages; pm_search_url is pre-filtered where possible
MNC_REGISTRY: list[MNC] = [
    # ---- Tech Giants ----
    MNC(
        "Google", "https://www.google.com/about/careers/applications/jobs/results/",
        "Gurugram",
        "https://www.google.com/about/careers/applications/jobs/results/?location=India&q=product%20manager",
    ),
    MNC(
        "Microsoft", "https://careers.microsoft.com/",
        "Noida, Gurugram",
        "https://jobs.careers.microsoft.com/global/en/search?q=product%20manager&l=India",
    ),
    MNC(
        "Amazon", "https://www.amazon.jobs/en/",
        "Gurugram, Noida",
        "https://www.amazon.jobs/en/search?base_query=product+manager&loc_query=India",
    ),
    MNC(
        "Meta", "https://www.metacareers.com/jobs/",
        "Gurugram",
        "https://www.metacareers.com/jobs/?q=product%20manager&location=India",
    ),
    MNC(
        "Apple", "https://jobs.apple.com/en-us/search",
        "Gurugram, Hyderabad (NCR satellite)",
        "https://jobs.apple.com/en-us/search?search=product%20manager&location=india",
    ),

    # ---- Enterprise Software / SaaS ----
    MNC(
        "Adobe", "https://careers.adobe.com/us/en/search-results",
        "Noida",
        "https://careers.adobe.com/us/en/search-results?keywords=product%20manager&location=India",
    ),
    MNC(
        "Salesforce", "https://careers.salesforce.com/en/jobs/",
        "Gurugram",
        "https://careers.salesforce.com/en/jobs/?search=product+manager&location=India",
    ),
    MNC(
        "Oracle", "https://www.oracle.com/in/careers/",
        "Gurugram, Noida",
        "https://www.oracle.com/in/careers/?keyword=product+manager",
    ),
    MNC(
        "SAP", "https://jobs.sap.com/",
        "Gurugram",
        "https://jobs.sap.com/search/?q=product+manager&locationsearch=India",
    ),
    MNC(
        "ServiceNow", "https://careers.servicenow.com/",
        "Gurugram",
        "https://careers.servicenow.com/jobs?keywords=product%20manager&location=India",
    ),
    MNC(
        "Intuit", "https://jobs.intuit.com/",
        "Gurugram",
        "https://jobs.intuit.com/search-jobs/product%20manager/India",
    ),
    MNC(
        "Cisco", "https://jobs.cisco.com/",
        "Gurugram",
        "https://jobs.cisco.com/jobs/SearchJobs/product%20manager?listFilterMode=1&21178=%5B169482%5D",
    ),
    MNC(
        "VMware (Broadcom)", "https://careers.broadcom.com/",
        "Gurugram",
        "https://careers.broadcom.com/search?q=product+manager&location=India",
    ),
    MNC(
        "Atlassian", "https://www.atlassian.com/company/careers/all-jobs",
        "Gurugram (Remote India)",
        "https://www.atlassian.com/company/careers/all-jobs?search=product+manager&location=India",
    ),

    # ---- Financial Services ----
    MNC(
        "American Express", "https://aexp.eightfold.ai/careers/",
        "Gurugram",
        "https://aexp.eightfold.ai/careers?query=product%20manager&location=Gurugram",
    ),
    MNC(
        "Mastercard", "https://careers.mastercard.com/us/en/search-results",
        "Gurugram",
        "https://careers.mastercard.com/us/en/search-results?keywords=product%20manager&location=India",
    ),
    MNC(
        "Visa", "https://corporate.visa.com/en/careers.html",
        "Gurugram (Bangalore primary)",
        "",
    ),
    MNC(
        "Goldman Sachs", "https://www.goldmansachs.com/careers/",
        "Gurugram",
        "https://higher.gs.com/roles?q=product+manager&location=India",
    ),
    MNC(
        "JPMorgan Chase", "https://careers.jpmorgan.com/",
        "Gurugram",
        "https://careers.jpmorgan.com/us/en/search-results?keywords=product%20manager&location=India",
    ),
    MNC(
        "Morgan Stanley", "https://www.morganstanley.com/careers/",
        "Gurugram",
        "",
    ),
    MNC(
        "Citi", "https://jobs.citi.com/",
        "Gurugram",
        "https://jobs.citi.com/search-jobs/product%20manager/India",
    ),
    MNC(
        "Capital One", "https://www.capitalonecareers.com/",
        "Gurugram (Tech hub)",
        "https://www.capitalonecareers.com/search-jobs?k=product+manager&l=India",
    ),

    # ---- Consulting / Professional Services ----
    MNC(
        "McKinsey & Company", "https://www.mckinsey.com/careers/search-jobs",
        "Gurugram, Delhi",
        "https://www.mckinsey.com/careers/search-jobs?query=product&locations=Delhi",
    ),
    MNC(
        "Deloitte", "https://apply.deloitte.com/careers/SearchJobs",
        "Gurugram, Noida",
        "https://apply.deloitte.com/careers/SearchJobs?keyword=product+manager&location=India",
    ),

    # ---- E-commerce / Consumer ----
    MNC(
        "Expedia Group", "https://careers.expediagroup.com/jobs/",
        "Gurugram",
        "https://careers.expediagroup.com/jobs/?keyword=product+manager&location=India",
    ),
    MNC(
        "Uber", "https://www.uber.com/us/en/careers/",
        "Gurugram, Delhi",
        "https://www.uber.com/us/en/careers/?query=product%20manager&location=India",
    ),
    MNC(
        "LinkedIn (Microsoft)", "https://careers.linkedin.com/",
        "Gurugram",
        "https://www.linkedin.com/jobs/search/?keywords=product%20manager&company=linkedin",
    ),

    # ---- Telecom / Infra ----
    MNC(
        "Qualcomm", "https://qualcomm.wd5.myworkdayjobs.com/External",
        "Noida",
        "https://qualcomm.wd5.myworkdayjobs.com/External?q=product+manager&locationCountry=a30a87ed25634629aa6c3958aa2b91ea",
    ),
    MNC(
        "Dell Technologies", "https://jobs.dell.com/",
        "Gurugram, Noida",
        "https://jobs.dell.com/search-jobs/product%20manager/India",
    ),
    MNC(
        "Hewlett Packard Enterprise", "https://careers.hpe.com/",
        "Gurugram",
        "https://careers.hpe.com/search?keywords=product+manager&location=India",
    ),

    # ---- Other Tech ----
    MNC(
        "IBM", "https://www.ibm.com/careers/search",
        "Gurugram, Noida",
        "https://www.ibm.com/careers/search?field_keyword_18[0]=product+manager&field_keyword_05[0]=IN",
    ),
    MNC(
        "PayPal", "https://careers.pypl.com/home/",
        "Gurugram (Chennai primary)",
        "https://paypal.eightfold.ai/careers?query=product%20manager&location=India",
    ),
    MNC(
        "Stripe", "https://stripe.com/jobs/search",
        "Remote India (Delhi NCR candidates)",
        "https://stripe.com/jobs/search?q=product+manager",
    ),
    MNC(
        "Twitter / X", "https://careers.x.com/",
        "Gurugram (reduced presence)",
        "",
    ),
    MNC(
        "Spotify", "https://www.lifeatspotify.com/jobs",
        "Remote India",
        "https://www.lifeatspotify.com/jobs?query=product+manager&location=India",
    ),
    MNC(
        "Airbnb", "https://careers.airbnb.com/",
        "Gurugram",
        "https://careers.airbnb.com/?query=product+manager&location=India",
    ),
    MNC(
        "Booking.com", "https://jobs.booking.com/",
        "Gurugram",
        "https://jobs.booking.com/search?keywords=product+manager&location=India",
    ),
    MNC(
        "Sprinklr", "https://www.sprinklr.com/careers/",
        "Gurugram",
        "https://www.sprinklr.com/careers/?search=product+manager",
    ),
    MNC(
        "Gartner", "https://jobs.gartner.com/",
        "Gurugram",
        "https://jobs.gartner.com/search?query=product+manager&location=India",
    ),
    MNC(
        "Amdocs", "https://www.amdocs.com/careers",
        "Gurugram",
        "https://www.amdocs.com/careers?search=product+manager",
    ),
    MNC(
        "Publicis Sapient", "https://careers.publicissapient.com/",
        "Gurugram, Noida",
        "https://careers.publicissapient.com/search?q=product+manager&location=India",
    ),
    MNC(
        "Nagarro", "https://www.nagarro.com/en/careers",
        "Gurugram",
        "https://www.nagarro.com/en/careers?q=product+manager",
    ),
]
