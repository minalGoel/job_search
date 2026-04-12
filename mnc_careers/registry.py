from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MNC:
    name: str
    careers_url: str
    delhi_ncr_office: str = ""  # "Gurugram", "Noida", "Delhi", etc.
    pm_search_url: str = ""  # Pre-built URL filtered for PM roles in Delhi NCR
    notes: str = ""
    api_url: str = ""      # JSON API endpoint (skips Playwright entirely when set)
    api_type: str = ""     # "amazon_jobs" | "greenhouse" | "lever"


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
        "Microsoft", "https://careers.microsoft.com/v2/global/en/locations/india.html",
        "Noida, Gurugram",
        # jobs.careers.microsoft.com has ERR_CERT_COMMON_NAME_INVALID (SSL cert mismatch)
        # Use the v2 careers portal instead; lc= is the location filter, q= is the keyword
        "https://careers.microsoft.com/v2/global/en/search?lc=India&q=product%20manager",
    ),
    MNC(
        "Amazon", "https://www.amazon.jobs/en/",
        "Gurugram, Noida",
        "https://www.amazon.jobs/en/search?base_query=product+manager&loc_query=India",
        api_url="https://www.amazon.jobs/en/search.json?base_query=product+manager&loc_query=India&result_limit=20",
        api_type="amazon_jobs",
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
        "VMware (Broadcom)", "https://www.broadcom.com/company/careers",
        "Gurugram",
        # careers.broadcom.com now redirects to Broadcom's Workday portal after VMware acquisition
        # Workday tenant: broadcom.wd1.myworkdayjobs.com/External_Career
        "https://broadcom.wd1.myworkdayjobs.com/en-US/External_Career?q=product+manager",
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

    # ---- Batch 01: Financial Banks (Part A) ----
    MNC(
        "DE Shaw", "https://www.deshawindia.com/careers",
        "Hyderabad primary, Gurugram",
        "",
        "D.E. Shaw India; quant/tech but occasional PM roles; filter manually on site",
    ),
    MNC(
        "Barclays", "https://search.jobs.barclays/",
        "Noida",
        "https://search.jobs.barclays/search?q=product+manager&location=India",
    ),
    MNC(
        "HSBC", "https://mycareer.hsbc.com/",
        "Gurugram",
        "https://mycareer.hsbc.com/en_GB/cx/job-search-results.html?keyword=product+manager&location=India",
    ),
    MNC(
        "Deutsche Bank", "https://careers.db.com/",
        "Gurugram",
        "https://careers.db.com/professionals/search-roles/#/professional/job/india/product+manager",
    ),
    MNC(
        "Bank of America", "https://careers.bankofamerica.com/",
        "Gurugram",
        "https://careers.bankofamerica.com/us/en/search-results?keywords=product+manager&location=India",
    ),
    MNC(
        "Wells Fargo", "https://www.wellsfargojobs.com/",
        "Gurugram (Hyderabad primary)",
        "https://www.wellsfargojobs.com/en/jobs/?q=product+manager&location=India",
    ),
    MNC(
        "Fidelity Investments", "https://jobs.fidelity.com/",
        "Gurugram",
        "https://jobs.fidelity.com/job-search-results/?keyword=product+manager&location=India",
    ),
    MNC(
        "BlackRock", "https://careers.blackrock.com/",
        "Gurugram",
        "https://careers.blackrock.com/job-search-results/?keyword=product%20manager&location=India",
    ),
    MNC(
        "State Street", "https://careers.statestreet.com/",
        "Gurugram",
        "https://careers.statestreet.com/global/en/search-results?keywords=product+manager&location=India",
    ),
    MNC(
        "BNY Mellon", "https://bnymellon.eightfold.ai/careers",
        "Gurugram (Pune larger)",
        "https://bnymellon.eightfold.ai/careers?query=product+manager&location=India",
    ),

    # ---- Batch 02: Financial Banks (Part B) + Financial Data ----
    MNC(
        "UBS", "https://www.ubs.com/global/en/careers.html",
        "Gurugram",
        "https://jobs.ubs.com/TGWebHost/jobsearch.aspx?partnerid=25008&siteid=5012&KeyWords=product+manager&Location=India",
    ),
    MNC(
        "Standard Chartered", "https://scb.taleo.net/careersection/jobsearch.ftl",
        "Gurugram (Chennai larger)",
        "https://scb.taleo.net/careersection/jobsearch.ftl?lang=en&SearchJob=product+manager&portalCode=900220",
    ),
    MNC(
        "Macquarie Group", "https://recruit.macquarie.com/",
        "Gurugram (Mumbai primary)",
        "https://recruit.macquarie.com/en_US/careers/SearchJobs/product%20manager?4178=%5BIND%5D",
    ),
    MNC(
        "Nomura", "https://nomuracareers.com/",
        "Gurugram (Mumbai primary)",
        "https://nomuracareers.com/search/?q=product+manager&location=India",
    ),
    MNC(
        "S&P Global", "https://careers.spglobal.com/",
        "Gurugram, Noida",
        "https://careers.spglobal.com/jobs?keywords=product+manager&location=India",
    ),
    MNC(
        "Moody's Analytics", "https://careers.moodys.com/",
        "Gurugram, Noida",
        "https://moodys.wd1.myworkdayjobs.com/en-US/Moodys?q=product+manager",
    ),
    MNC(
        "MSCI", "https://www.msci.com/careers",
        "Gurugram",
        "https://msci.wd1.myworkdayjobs.com/en-US/MSCIcareers?q=product+manager",
    ),
    MNC(
        "Bloomberg LP", "https://www.bloomberg.com/company/careers/",
        "Gurugram",
        "https://bloomberg.wd1.myworkdayjobs.com/en-US/Careers?q=product+manager&location=India",
    ),
    MNC(
        "LSEG (Refinitiv)", "https://www.lseg.com/en/careers",
        "Gurugram, Noida",
        "https://lseg.wd3.myworkdayjobs.com/en-US/Careers?q=product+manager",
    ),
    MNC(
        "Verisk Analytics", "https://careers.verisk.com/",
        "Gurugram (Hyderabad primary)",
        "https://verisk.wd5.myworkdayjobs.com/en-US/careers?q=product+manager",
    ),

    # ---- Batch 03: FinTech / Banking Software ----
    MNC(
        "Fiserv", "https://careers.fiserv.com/",
        "Gurugram, Noida",
        "https://fiserv.wd5.myworkdayjobs.com/ASC?q=product+manager",
    ),
    MNC(
        "FIS Global", "https://careers.fisglobal.com/",
        "Noida, Gurugram",
        "https://careers.fisglobal.com/us/en/search-results?keywords=product+manager&location=India",
    ),
    MNC(
        "Broadridge Financial", "https://careers.broadridge.com/",
        "Gurugram",
        "https://broadridge.wd1.myworkdayjobs.com/en-US/broadridge_external_career_site?q=product+manager",
    ),
    MNC(
        "Western Union", "https://careers.westernunion.com/",
        "Gurugram",
        "https://careers.westernunion.com/global/en/search-results?keywords=product+manager&location=India",
    ),
    MNC(
        "Finastra", "https://www.finastra.com/careers",
        "Noida",
        "https://finastra.wd3.myworkdayjobs.com/en-US/FinastraCareerSite?q=product+manager",
        "Banking/payments software; Noida is major product engineering hub",
    ),
    MNC(
        "Temenos", "https://www.temenos.com/careers/",
        "Noida",
        "https://jobs.temenos.com/search?q=product+manager&location=India",
        "Core banking software; Noida office",
    ),
    MNC(
        "Razorpay", "https://razorpay.com/jobs/",
        "Gurugram, Bengaluru",
        "https://boards.greenhouse.io/razorpaysoftwareprivatelimited",
        api_url="https://boards-api.greenhouse.io/v1/boards/razorpaysoftwareprivatelimited/jobs?content=true",
        api_type="greenhouse",
    ),
    MNC(
        "Chargebee", "https://www.chargebee.com/careers/",
        "Gurugram, Chennai",
        "https://jobs.chargebee.com",
    ),
    MNC(
        "Icertis", "https://www.icertis.com/company/careers/",
        "Gurugram (Pune also)",
        "https://icertis.wd1.myworkdayjobs.com/en-US/Icertis?q=product+manager",
        "Contract intelligence SaaS; Gurugram India center",
    ),
    MNC(
        "Whatfix", "https://www.whatfix.com/careers/",
        "Gurugram",
        "https://whatfix101.hire.trakstar.com",
        "DAP/SaaS; actively hiring PMs; uses Trakstar ATS",
    ),

    # ---- Batch 04: Cybersecurity / Observability ----
    MNC(
        "Palo Alto Networks", "https://jobs.paloaltonetworks.com/",
        "Gurugram",
        "https://paloaltonetworks.wd1.myworkdayjobs.com/External?q=product+manager",
    ),
    MNC(
        "CrowdStrike", "https://careers.crowdstrike.com/",
        "Remote India",
        "https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers?q=product+manager",
    ),
    MNC(
        "Fortinet", "https://www.fortinet.com/corporate/about-us/careers.html",
        "Gurugram",
        "https://fortinet.wd3.myworkdayjobs.com/fortinet?q=product+manager",
    ),
    MNC(
        "Check Point Software", "https://careers.checkpoint.com/",
        "Gurugram",
        "https://careers.checkpoint.com/jobs?q=product+manager&location=India",
    ),
    MNC(
        "Akamai Technologies", "https://careers.akamai.com/",
        "Gurugram",
        "https://careers.akamai.com/job-search-results/?keyword=product+manager&location=India",
    ),
    MNC(
        "F5 Networks", "https://f5.com/company/careers",
        "Gurugram",
        "https://ffive.wd5.myworkdayjobs.com/en-US/f5jobs?q=product+manager",
    ),
    MNC(
        "Dynatrace", "https://careers.dynatrace.com/",
        "Gurugram",
        "https://careers.dynatrace.com/jobs/job-search/?q=product+manager&location=India",
    ),
    MNC(
        "New Relic", "https://newrelic.com/about/careers",
        "Gurugram (Remote India)",
        "https://newrelic.com/about/careers#open-positions?q=product+manager",
    ),
    MNC(
        "Datadog", "https://www.datadoghq.com/careers/",
        "Gurugram (Remote India)",
        "https://boards.greenhouse.io/datadog",
        api_url="https://boards-api.greenhouse.io/v1/boards/datadog/jobs?content=true",
        api_type="greenhouse",
    ),
    MNC(
        "Elastic", "https://www.elastic.co/about/careers",
        "Remote India",
        "https://boards.greenhouse.io/elastic",
        api_url="https://boards-api.greenhouse.io/v1/boards/elastic/jobs?content=true",
        api_type="greenhouse",
    ),

    # ---- Batch 05: Enterprise SaaS — CX / Collaboration ----
    MNC(
        "Workday", "https://workday.wd5.myworkdayjobs.com/Workday",
        "Gurugram (Hyderabad also)",
        "https://workday.wd5.myworkdayjobs.com/Workday?q=product+manager",
    ),
    MNC(
        "Freshworks", "https://www.freshworks.com/company/careers/",
        "Gurugram (Chennai HQ)",
        "https://careers.smartrecruiters.com/Freshworks",
    ),
    MNC(
        "Zendesk", "https://jobs.zendesk.com/",
        "Gurugram (Bengaluru primary)",
        "https://jobs.zendesk.com/us/en/search-results?keywords=product+manager&location=India",
    ),
    MNC(
        "NICE Systems", "https://careers.nice.com/",
        "Gurugram",
        "https://nice.wd3.myworkdayjobs.com/en-US/nice_careers?q=product+manager",
    ),
    MNC(
        "Genesys", "https://www.genesys.com/company/careers",
        "Gurugram",
        "https://genesys.wd1.myworkdayjobs.com/en-US/Genesys?q=product+manager",
    ),
    MNC(
        "Verint Systems", "https://www.verint.com/careers/",
        "Gurugram",
        "https://jobs.verint.com/search?q=product+manager&location=India",
    ),
    MNC(
        "Qualtrics", "https://www.qualtrics.com/careers/",
        "Gurugram",
        "https://qualtrics.wd1.myworkdayjobs.com/en-US/careers?q=product+manager",
    ),
    MNC(
        "RingCentral", "https://www.ringcentral.com/us/en/careers.html",
        "Gurugram",
        "https://ringcentral.wd1.myworkdayjobs.com/RingCentral?q=product+manager",
    ),
    MNC(
        "Zoom Video", "https://careers.zoom.us/",
        "Noida, Gurugram",
        "https://careers.zoom.us/jobs/search?q=product+manager&location=India",
    ),
    MNC(
        "Medallia", "https://www.medallia.com/careers/",
        "Remote India",
        "https://www.medallia.com/careers/?q=product+manager",
        "Went private (Thoma Bravo 2021); CX/VoC platform",
    ),

    # ---- Batch 06: Enterprise SaaS — Dev Tools / Data ----
    MNC(
        "MongoDB", "https://www.mongodb.com/careers",
        "Gurugram",
        "https://boards.greenhouse.io/mongodb",
        api_url="https://boards-api.greenhouse.io/v1/boards/mongodb/jobs?content=true",
        api_type="greenhouse",
    ),
    MNC(
        "Databricks", "https://www.databricks.com/company/careers",
        "Gurugram (Remote India)",
        "https://boards.greenhouse.io/databricks",
        api_url="https://boards-api.greenhouse.io/v1/boards/databricks/jobs?content=true",
        api_type="greenhouse",
    ),
    MNC(
        "Snowflake", "https://careers.snowflake.com/",
        "Gurugram (Bengaluru also)",
        "https://snowflake.wd1.myworkdayjobs.com/en-US/Snowflake_Careers?q=product+manager",
    ),
    MNC(
        "GitLab", "https://about.gitlab.com/jobs/",
        "Remote India",
        "https://boards.greenhouse.io/gitlab",
        "Fully distributed; any India location; strong PM hiring",
        api_url="https://boards-api.greenhouse.io/v1/boards/gitlab/jobs?content=true",
        api_type="greenhouse",
    ),
    MNC(
        "Twilio", "https://www.twilio.com/en-us/company/jobs",
        "Remote India",
        "https://boards.greenhouse.io/twilio",
        api_url="https://boards-api.greenhouse.io/v1/boards/twilio/jobs?content=true",
        api_type="greenhouse",
    ),
    MNC(
        "Okta", "https://www.okta.com/company/careers/",
        "Remote India (Gurugram)",
        "https://boards.greenhouse.io/okta",
        api_url="https://boards-api.greenhouse.io/v1/boards/okta/jobs?content=true",
        api_type="greenhouse",
    ),
    MNC(
        "DocuSign", "https://careers.docusign.com/",
        "Gurugram",
        "https://docusign.wd1.myworkdayjobs.com/en-US/DocuSign?q=product+manager",
    ),
    MNC(
        "Informatica", "https://careers.informatica.com/",
        "Gurugram",
        "https://informatica.wd1.myworkdayjobs.com/en-US/Informatica_Careers?q=product+manager",
    ),
    MNC(
        "PTC Inc", "https://www.ptc.com/en/careers",
        "Gurugram",
        "https://ptc.wd1.myworkdayjobs.com/en-US/Careers?q=product+manager",
        "Industrial IoT/PLM software",
    ),
    MNC(
        "NetApp", "https://jobs.netapp.com/",
        "Gurugram, Bengaluru",
        "https://jobs.netapp.com/search-jobs/product%20manager/India",
    ),

    # ---- Batch 07: Consulting / Professional Services ----
    MNC(
        "Accenture", "https://www.accenture.com/in-en/careers",
        "Gurugram, Noida, Delhi",
        "https://www.accenture.com/in-en/careers/jobsearch?jk=product+manager&lc=India",
    ),
    MNC(
        "BCG (Boston Consulting Group)", "https://careers.bcg.com/",
        "Gurugram, Delhi",
        "https://careers.bcg.com/job-search?q=digital+product&location=India",
        "BCG Platinion has product/delivery roles; Avature ATS",
    ),
    MNC(
        "Bain & Company", "https://www.bain.com/careers/",
        "Gurugram, Delhi",
        "https://www.bain.com/careers/explore-roles/?office=new-delhi",
    ),
    MNC(
        "EY (Ernst & Young)", "https://careers.ey.com/",
        "Gurugram, Delhi, Noida",
        "https://careers.ey.com/ey/search/?q=product+manager&location=India",
        "EY GDS India has large tech presence",
    ),
    MNC(
        "KPMG India", "https://home.kpmg/in/en/home/careers.html",
        "Gurugram, Delhi",
        "https://home.kpmg/in/en/home/careers.html",
        "KPMG India careers portal; filter manually for PM roles",
    ),
    MNC(
        "PwC India", "https://www.pwc.in/careers.html",
        "Gurugram, Delhi, Noida",
        "https://www.pwc.in/careers/experienced-careers.html?q=product+manager",
    ),
    MNC(
        "Capgemini", "https://www.capgemini.com/in-en/careers/",
        "Gurugram, Noida, Delhi",
        "https://www.capgemini.com/in-en/careers/find-a-job/?q=product+manager",
    ),
    MNC(
        "Cognizant", "https://careers.cognizant.com/",
        "Gurugram, Noida",
        "https://careers.cognizant.com/global/en/search-results?keywords=product+manager&location=Delhi",
    ),
    MNC(
        "DXC Technology", "https://careers.dxc.com/",
        "Noida, Gurugram",
        "https://dxc.wd1.myworkdayjobs.com/en-US/DXCCareers?q=product+manager",
    ),
    MNC(
        "NTT Data", "https://www.nttdata.com/global/en/careers/",
        "Noida, Gurugram",
        "https://nttdata.wd3.myworkdayjobs.com/en-US/nttdatacareers?q=product+manager",
    ),

    # ---- Batch 08: India IT Services / BPO ----
    MNC(
        "Wipro", "https://careers.wipro.com/",
        "Noida, Gurugram, Delhi",
        "https://careers.wipro.com/careers-home/jobs?q=product+manager&location=Delhi",
    ),
    MNC(
        "HCL Technologies", "https://www.hcltech.com/careers",
        "Noida (HCL HQ)",
        "https://www.hcltech.com/careers?q=product+manager&location=Noida",
        "HCL HQ is Noida; large product/digital roles",
    ),
    MNC(
        "Tech Mahindra", "https://careers.techmahindra.com/",
        "Gurugram, Noida, Delhi",
        "https://careers.techmahindra.com/search-results?keywords=product+manager&location=India",
    ),
    MNC(
        "WNS Global Services", "https://www.wns.com/careers",
        "Gurugram, Noida, Delhi",
        "https://www.wns.com/careers?q=product+manager",
    ),
    MNC(
        "EXL Service", "https://exlservice.com/careers/",
        "Noida, Gurugram, Delhi (India HQ)",
        "https://exl.wd1.myworkdayjobs.com/en-US/EXL?q=product+manager",
    ),
    MNC(
        "Genpact", "https://www.genpact.com/careers",
        "Gurugram (India HQ)",
        "https://genpact.wd5.myworkdayjobs.com/en-US/Genpact_Careers?q=product+manager",
    ),
    MNC(
        "Concentrix", "https://jobs.concentrix.com/",
        "Gurugram, Noida, Delhi",
        "https://jobs.concentrix.com/job-search-results/?keyword=product+manager&location=India",
    ),
    MNC(
        "TCS", "https://www.tcs.com/careers",
        "Noida, Gurugram, Delhi",
        "https://www.tcs.com/careers/tcs-careers-portal",
        "TCS NextStep portal; filter for product owner/PM roles in Digital division",
    ),
    MNC(
        "Infosys", "https://career.infosys.com/",
        "Noida, Gurugram",
        "https://career.infosys.com/jobdesc/0/INFSYS/jobList.jsp?searchTitle=product+manager",
        "Custom Taleo portal at career.infosys.com",
    ),
    MNC(
        "Mphasis", "https://www.mphasis.com/careers.html",
        "Noida (Bengaluru HQ)",
        "https://mphasis.eightfold.ai/careers?query=product+manager",
    ),

    # ---- Batch 09: Industrial / Engineering Tech ----
    MNC(
        "Honeywell", "https://careers.honeywell.com/",
        "Gurugram",
        "https://careers.honeywell.com/us/en/search-results?keywords=product+manager&location=India",
        notes="Honeywell Technology Solutions Gurugram (~6000 employees); strong product roles",
    ),
    MNC(
        "Siemens", "https://jobs.siemens.com/",
        "Gurugram, Noida, Delhi",
        "https://jobs.siemens.com/careers?query=product+manager&location=India",
    ),
    MNC(
        "ABB", "https://careers.abb/global/en",
        "Gurugram, Noida",
        "https://careers.abb/global/en/search-results?keywords=product+manager&location=India",
    ),
    MNC(
        "Schneider Electric", "https://www.se.com/ww/en/about-us/careers/",
        "Gurugram, Noida",
        "https://www.se.com/ww/en/about-us/careers/search-results.jsp?q=product+manager&location=India",
    ),
    MNC(
        "Autodesk", "https://www.autodesk.com/careers/overview",
        "Noida, Gurugram",
        "https://autodesk.wd1.myworkdayjobs.com/en-US/Ext?q=product+manager",
        notes="Noida is major Autodesk product/engineering hub globally",
    ),
    MNC(
        "Ansys", "https://www.ansys.com/about-ansys/careers",
        "Noida",
        "https://ansys.wd1.myworkdayjobs.com/en-US/Ansys?q=product+manager",
        notes="Noida is one of Ansys' largest R&D centers globally; simulation software",
    ),
    MNC(
        "Emerson Electric", "https://www.emerson.com/en-us/careers",
        "Gurugram",
        "https://emerson.wd1.myworkdayjobs.com/en-US/External?q=product+manager",
    ),
    MNC(
        "Eaton Corporation", "https://eaton.eightfold.ai/careers",
        "Gurugram, Noida",
        "https://eaton.eightfold.ai/careers?query=product+manager&location=India",
        notes="Eaton India Innovation Center in Gurugram; power management",
    ),
    MNC(
        "Rockwell Automation", "https://www.rockwellautomation.com/en-us/company/careers.html",
        "Gurugram",
        "https://rockwellautomation.wd1.myworkdayjobs.com/en-US/External_Career_Site?q=product+manager",
        notes="Industrial automation software; India GCC in Gurugram",
    ),
    MNC(
        "Synopsys", "https://careers.synopsys.com/",
        "Noida, Gurugram",
        "https://synopsys.wd1.myworkdayjobs.com/en-US/Synopsys?q=product+manager",
        notes="EDA/semiconductor software; Noida R&D center is significant",
    ),

    # ---- Batch 10: Travel / Media / Telecom / Healthcare ----
    MNC(
        "MakeMyTrip", "https://careers.makemytrip.com/",
        "Gurugram (India HQ)",
        "https://careers.makemytrip.com/?department=product+management",
        notes="India travel tech; strong PM culture; India-based team",
    ),
    MNC(
        "Disney+ Hotstar", "https://www.thewaltdisneycompany.com/careers/",
        "Noida",
        "https://jobs.disneycareers.com/search-jobs/product%20manager/India",
        notes="Hotstar India tech team is in Noida; excellent PM org; check for Reliance JV changes",
    ),
    MNC(
        "Nokia", "https://www.nokia.com/careers/",
        "Gurugram, Noida",
        "https://nokia.wd3.myworkdayjobs.com/nokia_careers?q=product+manager",
    ),
    MNC(
        "Ericsson", "https://jobs.ericsson.com/careers",
        "Gurugram, Noida",
        "https://jobs.ericsson.com/careers?query=product+manager&location=India",
        notes="Ericsson India GDC in Gurugram; telecom/5G/cloud product roles",
    ),
    MNC(
        "Optum (UnitedHealth Group)", "https://careers.unitedhealthgroup.com/",
        "Gurugram, Noida",
        "https://careers.unitedhealthgroup.com/job-search-results/?keyword=product+manager&location=India",
        notes="Optum India GCC in Gurugram/Noida (~30K employees); health IT/data; PM roles plentiful",
    ),
    MNC(
        "Philips HealthTech", "https://www.philips.com/a-w/careers.html",
        "Gurugram, Noida",
        "https://philips.wd3.myworkdayjobs.com/en-US/Philips_External_Careers?q=product+manager",
        notes="Philips India Innovation Center in Gurugram; health informatics PM roles",
    ),
    MNC(
        "Agoda", "https://careersatagoda.com/",
        "Remote India (Gurugram)",
        "https://boards.greenhouse.io/agoda",
        notes="Booking Holdings subsidiary; Thailand HQ but strong India product hiring",
        api_url="https://boards-api.greenhouse.io/v1/boards/agoda/jobs?content=true",
        api_type="greenhouse",
    ),
    MNC(
        "Pearson", "https://pearson.jobs/",
        "Noida, Gurugram",
        "https://pearson.jobs/search-jobs/product%20manager/India",
        notes="EdTech/content; Noida GCC is significant",
    ),
    MNC(
        "Sabre Corporation", "https://careers.sabre.com/",
        "Gurugram",
        "https://sabre.wd1.myworkdayjobs.com/en-US/SabreCareers?q=product+manager",
        notes="Travel technology/GDS; Gurugram India center; PM roles in B2B travel tech",
    ),
    MNC(
        "Amadeus IT", "https://amadeus.com/en/careers",
        "Gurugram",
        "https://jobs.amadeus.com/search?q=product+manager&location=India",
        notes="Travel tech/GDS; airline/hotel tech PM roles",
    ),

    # ---- Batch 11: Telecom / Networking / EDA / Engineering Software ----
    MNC(
        "CommScope", "https://careers.commscope.com/",
        "Gurugram, Noida",
        "https://commscope.wd1.myworkdayjobs.com/en-US/commscope?q=product+manager",
    ),
    MNC(
        "Juniper Networks", "https://www.juniper.net/us/en/about/careers.html",
        "Gurugram (Bengaluru primary)",
        "https://juniper.wd5.myworkdayjobs.com/en-US/careers?q=product+manager",
    ),
    MNC(
        "Ciena Corporation", "https://www.ciena.com/about/careers.html",
        "Gurugram",
        "https://ciena.wd1.myworkdayjobs.com/en-US/Careers?q=product+manager",
        notes="Optical networking software; Gurugram India center",
    ),
    MNC(
        "Cadence Design Systems", "https://www.cadence.com/en_US/home/company/careers.html",
        "Noida, Gurugram",
        "https://cadence.wd1.myworkdayjobs.com/en-US/External_Careers?q=product+manager",
        notes="EDA software; Noida R&D center; PM roles in semiconductor/IC design tools",
    ),
    MNC(
        "Dassault Systèmes", "https://www.3ds.com/careers/",
        "Noida, Gurugram",
        "https://www.3ds.com/careers/search-jobs?query=product+manager&location=India",
        notes="PLM software (CATIA/SOLIDWORKS/SIMULIA); Noida office",
    ),
    MNC(
        "Trimble Inc", "https://www.trimble.com/en/our-company/careers",
        "Noida, Gurugram",
        "https://trimble.wd1.myworkdayjobs.com/en-US/TrimbleCareers?q=product+manager",
        notes="Geospatial/construction tech; Noida center",
    ),
    MNC(
        "Hexagon AB", "https://www.hexagon.com/careers",
        "Gurugram, Noida",
        "https://hexagon.wd3.myworkdayjobs.com/en-US/HEXAGON?q=product+manager",
        notes="Geospatial/engineering software; India R&D",
    ),
    MNC(
        "Bentley Systems", "https://www.bentley.com/about-us/careers/",
        "Noida, Gurugram",
        "https://jobs.bentley.com/search?q=product+manager&location=India",
        notes="Engineering software (AEC/infrastructure); Noida office",
    ),
    MNC(
        "Nutanix", "https://www.nutanix.com/company/careers",
        "Gurugram",
        "https://nutanix.eightfold.ai/careers?query=product+manager&location=India",
        notes="HCI/cloud; Gurugram India R&D hub",
    ),
    MNC(
        "Teradata", "https://www.teradata.com/About-Us/Careers",
        "Gurugram, Hyderabad",
        "https://careers.teradata.com/search?q=product+manager&location=India",
    ),

    # ---- Batch 12: Financial Services (Misc) / Media / Other ----
    MNC(
        "Marsh McLennan", "https://careers.marshmclennan.com/",
        "Gurugram, Noida",
        "https://careers.marshmclennan.com/global/en/search-results?keywords=product+manager&location=India",
        notes="Risk/insurance advisory GCC in Gurugram; Workday ATS",
    ),
    MNC(
        "BNP Paribas", "https://group.bnpparibas/en/careers",
        "Gurugram (Mumbai primary)",
        "https://bnpparibas.recruitmentplatform.com/applis/VACANTE.GF?ID=&LANGUE=UK&RECHERCHE_CRITERE_METIER=product+manager&RECHERCHE_CRITERE_PAYS=IND",
    ),
    MNC(
        "Société Générale", "https://careers.societegenerale.com/",
        "Gurugram",
        "https://careers.societegenerale.com/en/job-offers#job-search?search=product%20manager&country=IN",
        notes="SG Global Solution Centre Gurugram; SAP SuccessFactors ATS",
    ),
    MNC(
        "FactSet Research", "https://factset.wd1.myworkdayjobs.com/FactSetCareers",
        "Hyderabad (Gurugram secondary)",
        "https://factset.wd1.myworkdayjobs.com/FactSetCareers?q=product+manager",
        notes="Financial data terminal; Workday ATS",
    ),
    MNC(
        "Tata Communications", "https://www.tatacommunications.com/careers/",
        "Noida, Gurugram, Delhi",
        "https://tatacommunications.wd1.myworkdayjobs.com/en-US/TataCommunicationsCareers?q=product+manager",
        notes="Telecom/cloud/IoT; India HQ",
    ),
    MNC(
        "Tata Elxsi", "https://www.tataelxsi.com/career",
        "Noida, Gurugram",
        "https://www.tataelxsi.com/career?search=product+manager",
        notes="Engineering services/embedded/OTT; product management roles",
    ),
    MNC(
        "Samsung India R&D", "https://www.samsung.com/in/aboutsamsung/careers/",
        "Noida (Samsung R&D Institute India)",
        "https://www.samsung.com/in/aboutsamsung/careers/jobs/?q=product+manager",
        notes="Samsung R&D Noida (SRI-N) is one of Samsung's largest globally; product/engineering roles",
    ),
    MNC(
        "Warner Bros. Discovery", "https://wbdcareers.com/",
        "Gurugram (Mumbai primary)",
        "https://wbd.wd5.myworkdayjobs.com/wbdcareers?q=product+manager&location=India",
        notes="Max streaming; India tech team in Gurugram; PM roles",
    ),
    MNC(
        "Coursera", "https://careers.coursera.org/",
        "Remote India (Gurugram)",
        "https://boards.greenhouse.io/coursera",
        notes="EdTech; India remote hiring active; PM roles",
        api_url="https://boards-api.greenhouse.io/v1/boards/coursera/jobs?content=true",
        api_type="greenhouse",
    ),
    MNC(
        "EPAM Systems", "https://www.epam.com/careers",
        "Gurugram (Remote India)",
        "https://www.epam.com/careers/job-listings?q=product+manager&location=India",
        notes="Engineering services; product owner/PM roles",
    ),

    # ---- Batch 13: Healthcare IT / Enterprise Misc ----
    MNC(
        "GE HealthCare", "https://jobs.gehealthcare.com/",
        "Gurugram",
        "https://jobs.gehealthcare.com/search-jobs/product+manager/India/26178/1/2/-/-/-/1",
        "GE HealthCare split from GE in 2023; India tech center in Gurugram; digital health PM roles",
    ),
    MNC(
        "Becton Dickinson", "https://jobs.bd.com/",
        "Gurugram",
        "https://bd.wd1.myworkdayjobs.com/en-US/BD?q=product+manager",
        "Medical devices/diagnostics; Gurugram India center",
    ),
    MNC(
        "NCR Voyix", "https://www.ncrvoyix.com/company/careers",
        "Gurugram, Noida",
        "https://ncrvoyix.wd1.myworkdayjobs.com/en-US/NCRCareers?q=product+manager",
        "Retail/hospitality tech (POS/payments); Gurugram India center",
    ),
    MNC(
        "OpenText", "https://careers.opentext.com/",
        "Noida, Gurugram",
        "https://opentext.wd1.myworkdayjobs.com/en-US/opentext?q=product+manager",
        "Acquired Micro Focus 2023; Noida/Gurugram large India team; enterprise content mgmt",
    ),
    MNC(
        "Conduent", "https://careers.conduent.com/",
        "Noida, Gurugram",
        "https://conduent.taleo.net/careersection/10/jobsearch.ftl?lang=en&SearchJob=product+manager",
        "BPO/tech services; significant India presence",
    ),
    MNC(
        "Hexaware Technologies", "https://hexaware.com/careers/",
        "Noida, Gurugram",
        "https://hexaware.com/careers?q=product+manager",
        "IT services; Noida/Gurugram delivery centers",
    ),
    MNC(
        "Druva", "https://www.druva.com/company/careers/",
        "Pune, Gurugram",
        "https://boards.greenhouse.io/druva",
        "Cloud data protection SaaS; India PM roles",
        api_url="https://boards-api.greenhouse.io/v1/boards/druva/jobs?content=true",
        api_type="greenhouse",
    ),
    MNC(
        "Glean", "https://www.glean.com/careers",
        "Remote India (Gurugram growing)",
        "https://www.glean.com/careers?q=product+manager",
        "Enterprise search/AI; fast-growing; India remote hiring",
    ),
    MNC(
        "Unisys", "https://www.unisys.com/careers/",
        "Noida, Gurugram",
        "https://careers.unisys.com/job-search-results/?keyword=product+manager&location=India",
        "IT services; Noida office",
    ),
    MNC(
        "Fujitsu", "https://jobs.fujitsu.com/",
        "Noida",
        "https://jobs.fujitsu.com/search?q=product+manager&location=India",
        "IT services; Noida India hub",
    ),

    # ---- Batch 14: More SaaS / Cloud / India-HQ Tech ----
    MNC(
        "Veeva Systems", "https://careers.veeva.com/",
        "Remote India (Gurugram)",
        "https://careers.veeva.com/?q=product+manager&location=India",
        notes="Life sciences cloud SaaS; remote-friendly; India tech roles",
    ),
    MNC(
        "Coupa Software", "https://www.coupa.com/company/careers",
        "Remote India",
        "https://coupa.wd1.myworkdayjobs.com/en-US/CoupaCareer?q=product+manager",
        notes="BSM/procurement SaaS; private (Thoma Bravo 2023)",
    ),
    MNC(
        "Appian", "https://careers.appian.com/",
        "Remote India (Gurugram)",
        "https://careers.appian.com/job-search?q=product+manager",
        notes="Low-code BPM; India PM roles",
    ),
    MNC(
        "Box Inc", "https://www.box.com/en-us/careers",
        "Remote India",
        "https://box.eightfold.ai/careers?query=product+manager",
        notes="Cloud content management; Eightfold ATS",
    ),
    MNC(
        "Asana", "https://asana.com/company/careers",
        "Remote India",
        "https://boards.greenhouse.io/asana",
        notes="Work management SaaS; remote India PM roles",
        api_url="https://boards-api.greenhouse.io/v1/boards/asana/jobs?content=true",
        api_type="greenhouse",
    ),
    MNC(
        "MuleSoft (Salesforce)", "https://careers.salesforce.com/en/jobs/",
        "Gurugram (under Salesforce umbrella)",
        "https://careers.salesforce.com/en/jobs/?search=mulesoft+product+manager&location=India",
        notes="Integration platform; part of Salesforce; search under Salesforce careers",
    ),
    MNC(
        "Zoho Corporation", "https://careers.zohocorp.com/",
        "Remote India (Chennai HQ)",
        "https://careers.zohocorp.com/jobs/Careers/search?term=product+manager",
        notes="India-HQ SaaS suite; Chennai primary but India-wide remote",
    ),
    MNC(
        "CleverTap", "https://clevertap.com/careers/",
        "Gurugram, Mumbai",
        "https://clevertap.com/careers/?department=Product+Management",
        notes="Mobile marketing/analytics SaaS; India-HQ; PM roles active",
    ),
    MNC(
        "MoEngage", "https://www.moengage.com/careers/",
        "Gurugram, Bengaluru",
        "https://moengage.hire.trakstar.com",
        notes="Customer engagement platform; India-HQ; uses Trakstar ATS",
    ),
    MNC(
        "Postman", "https://www.postman.com/company/careers/",
        "Remote India (Bengaluru HQ)",
        "https://boards.greenhouse.io/postman",
        notes="API platform; India HQ; PM roles for developer tools",
        api_url="https://boards-api.greenhouse.io/v1/boards/postman/jobs?content=true",
        api_type="greenhouse",
    ),

    # ---- Batch 15: Consumer Tech / Media / Misc Final ----
    MNC(
        "LG Electronics India", "https://www.lg.com/in/jobs/",
        "Noida, Gurugram",
        "https://www.lg.com/in/jobs/?q=product+manager",
        notes="LG Electronics India HQ in Noida; LG Soft India division; software/product roles",
    ),
    MNC(
        "Sony India Software Centre", "https://www.sony.co.in/en/article/careers",
        "Noida",
        "https://www.sony.co.in/en/article/careers",
        notes="Sony India Software Centre in Noida Tech Park; embedded/IoT product roles",
    ),
    MNC(
        "Travelport", "https://www.travelport.com/about-us/careers",
        "Gurugram",
        "https://travelport.wd1.myworkdayjobs.com/en-US/TPGlobalCareers?q=product+manager",
        notes="Travel technology; Gurugram India center; went private 2019",
    ),
    MNC(
        "Sprinto", "https://sprinto.com/careers/",
        "Gurugram",
        "https://jobs.lever.co/Sprinto?team=Product",
        notes="Compliance automation SaaS; Gurugram HQ; PM roles for B2B SaaS",
        api_url="https://api.lever.co/v0/postings/Sprinto?mode=json",
        api_type="lever",
    ),
    MNC(
        "Darwinbox", "https://darwinbox.com/careers",
        "Gurugram, Hyderabad",
        "https://darwinbox.com/careers/open-positions",
        notes="HCM SaaS; India-HQ; Gurugram office; PM roles active; uses own HRMS portal",
    ),
    MNC(
        "Zeta (Tech Fin)", "https://www.zeta.tech/in/careers/",
        "Gurugram, Bengaluru",
        "https://www.zeta.tech/in/careers/?department=Product",
        notes="Fintech/banking-as-a-service; India-HQ; Gurugram office; senior PM roles",
    ),
    MNC(
        "Fareye", "https://www.fareye.com/company/careers",
        "Noida (HQ)",
        "https://careers.getfareye.com",
        notes="Logistics SaaS; Noida HQ; PM roles; uses custom Spire ATS",
    ),
    MNC(
        "WebEngage", "https://webengage.com/careers/",
        "Gurugram, Mumbai",
        "https://webengage.com/careers/?department=Product",
        notes="Customer data platform/marketing automation; India-HQ; PM roles",
    ),
    MNC(
        "Samsara", "https://www.samsara.com/company/careers",
        "Remote India",
        "https://boards.greenhouse.io/samsara",
        notes="IoT/fleet management; US-HQ; India remote hiring; strong PM culture",
        api_url="https://boards-api.greenhouse.io/v1/boards/samsara/jobs?content=true",
        api_type="greenhouse",
    ),
    MNC(
        "Zuora", "https://www.zuora.com/company/careers/",
        "Gurugram (Remote India)",
        "https://zuora.wd1.myworkdayjobs.com/en-US/ZuoraCareers?q=product+manager",
        notes="Subscription billing SaaS; India office; PM roles",
    ),
]
