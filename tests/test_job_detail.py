from __future__ import annotations

import asyncio
import json
import unittest

import httpx

from services.job_detail import (
    DetailLocation,
    DetailRecord,
    fetch_detail,
    parse_greenhouse_job,
    parse_jsonld,
    parse_microdata,
    parse_oracle_detail,
    parse_smartrecruiters_posting,
    parse_workday_detail,
    strategy_for,
)
from services.location_resolver import passes, resolve


class _Log:
    def debug(self, *a, **k): ...
    def info(self, *a, **k): ...
    def warning(self, *a, **k): ...


LOG = _Log()

JSONLD_HTML = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting","title":"Product Manager","datePosted":"2026-09-18T00:00:00",
 "employmentType":"FULL_TIME","jobLocationType":"TELECOMMUTE","description":"<p>Own the roadmap. <b>Hybrid</b> from our Gurgaon office.</p>",
 "jobLocation":[{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"IND-Gurgaon (SVG)","addressCountry":"India"}},
                {"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"Bangalore","addressRegion":"Karnataka","postalCode":"560045","addressCountry":"IN"}}]}
</script></head><body>…</body></html>"""

MICRODATA_HTML = """<div itemscope itemtype="http://schema.org/JobPosting">
 <span itemprop="title">Product Manager</span>
 <div itemprop="jobLocation" itemscope itemtype="http://schema.org/Place">
   <span itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">
     <span itemprop="addressLocality">Noida</span>, <span itemprop="addressRegion">UP</span>,
     <span itemprop="postalCode">201301</span>, <span itemprop="addressCountry">IN</span>
   </span></div>
 <div itemprop="description">Great role. Work from home 2 days a week (hybrid).</div></div>"""

ORACLE_JSON = {"items": [{"Id": "38278", "Title": "Online Product Owner", "PrimaryLocation": "India", "PrimaryLocationCountry": "IN",
                          "WorkplaceType": "Hybrid", "PostedDate": "2026-09-10", "ExternalDescriptionStr": "<p>Own the online channel.</p>",
                          "workLocation": [{"AddressLine1": "Silver Oak, A Wing, Manyata Embassy Business Park", "TownOrCity": "Bangalore",
                                            "PostalCode": "560045", "Country": "IN", "Region2": "Karnataka"}]}]}

WORKDAY_JSON = {"jobPostingInfo": {"location": "Noida, Uttar Pradesh, India", "additionalLocations": ["Bangalore, Karnataka, India"],
                                   "remoteType": "", "jobDescription": "<p>Lead Firefly.</p>", "startDate": "2026-09-19", "timeType": "Full time"}}

SR_JSON = {"location": {"city": "Bogotá", "region": "Bogotá", "country": "co", "remote": True, "fullLocation": "Bogotá, co"},
           "releasedDate": "2026-09-01T10:00:00.000Z", "typeOfEmployment": {"label": "Full-time"},
           "jobAd": {"sections": {"jobDescription": {"text": "<p>Assess orthopaedic devices.</p>"}}}}

GH_JSON = {"location": {"name": "Gurugram, India"}, "offices": [{"name": "Gurugram", "location": "Gurugram, Haryana, India"}],
           "content": "&lt;p&gt;Remote-friendly team.&lt;/p&gt;", "updated_at": "2026-09-15T00:00:00-04:00"}


class ParserTests(unittest.TestCase):
    def test_jsonld(self) -> None:
        rec = parse_jsonld(JSONLD_HTML)
        self.assertEqual(rec.source, "jsonld")
        self.assertEqual([l.city for l in rec.locations], ["Gurgaon", "Bangalore"])
        self.assertEqual(rec.locations[1].postal, "560045")
        self.assertEqual(rec.workplace_type, "remote_or_hybrid")
        self.assertIn("Own the roadmap", rec.description)
        self.assertNotIn("<p>", rec.description)
        self.assertEqual(rec.posted_date, "2026-09-18")

    def test_microdata(self) -> None:
        rec = parse_microdata(MICRODATA_HTML)
        self.assertEqual(rec.source, "microdata")
        self.assertEqual((rec.locations[0].city, rec.locations[0].region, rec.locations[0].country), ("Noida", "UP", "IN"))
        self.assertEqual(rec.workplace_type, "hybrid")

    def test_oracle(self) -> None:
        rec = parse_oracle_detail(ORACLE_JSON)
        self.assertEqual(rec.city_level()[0].city, "Bangalore")
        self.assertEqual(rec.workplace_type, "hybrid")
        self.assertEqual(rec.posted_date, "2026-09-10")

    def test_workday_smartrecruiters_greenhouse(self) -> None:
        wd = parse_workday_detail(WORKDAY_JSON)
        self.assertEqual([l.city for l in wd.locations], ["Noida", "Bangalore"])
        sr = parse_smartrecruiters_posting(SR_JSON)
        self.assertEqual((sr.locations[0].city, sr.locations[0].country, sr.workplace_type), ("Bogotá", "co", "remote"))
        gh = parse_greenhouse_job(GH_JSON)
        self.assertEqual(gh.locations[0].city, "Gurugram")
        self.assertEqual(len(gh.locations), 1)  # office duplicate collapsed

    def test_strategy(self) -> None:
        self.assertEqual(strategy_for("https://x.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/38278"), "oracle_api")
        self.assertEqual(strategy_for("https://adobe.wd5.myworkdayjobs.com/en-US/ext/job/Noida/PM_R1"), "workday_cxs")
        self.assertEqual(strategy_for("https://jobs.smartrecruiters.com/sgs/744000148734579"), "smartrecruiters_api")
        self.assertEqual(strategy_for("https://boards.greenhouse.io/zuora/jobs/1"), "greenhouse_api")
        self.assertEqual(strategy_for("https://www.naukri.com/job-listings-pm"), "none")
        self.assertEqual(strategy_for("https://careers.cisco.com/global/en/job/1"), "page")


class FetchTests(unittest.TestCase):
    def _fetch(self, url, handler):
        async def go():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await fetch_detail(url, client, host_sem=asyncio.Semaphore(2), log=LOG)
        return asyncio.run(go())

    def test_oracle_api_call_shape_and_page_fallback(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if "recruitingCEJobRequisitionDetails" in req.url.path:
                self.assertEqual(req.url.params["finder"], 'ById;Id="38278",siteNumber=CX_1')
                return httpx.Response(200, json=ORACLE_JSON)
            if req.url.host == "careers.acme.com":
                return httpx.Response(200, text=JSONLD_HTML)
            return httpx.Response(404)

        rec = self._fetch("https://x.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/38278", handler)
        self.assertEqual((rec.status, rec.source, rec.city_level()[0].city), ("ok", "oracle_api", "Bangalore"))
        rec = self._fetch("https://careers.acme.com/job/1", handler)
        self.assertEqual((rec.status, rec.source), ("ok", "jsonld"))

    def test_blocked_and_none_never_raise(self) -> None:
        rec = self._fetch("https://careers.acme.com/job/1", lambda req: httpx.Response(403, text="denied"))
        self.assertEqual(rec.status, "blocked")
        rec = self._fetch("https://careers.acme.com/job/1", lambda req: httpx.Response(200, text="<html>no structured data</html>"))
        self.assertEqual(rec.status, "none")
        rec = self._fetch("https://www.naukri.com/job-listings-pm", lambda req: httpx.Response(200, text=""))
        self.assertEqual(rec.status, "none")


class ResolverTests(unittest.TestCase):
    def test_nokia_hybrid_in_bangalore_is_rejected(self) -> None:
        r = resolve("India (Hybrid)", detail=parse_oracle_detail(ORACLE_JSON))
        self.assertFalse(r.location_ok)
        self.assertEqual((r.source, r.work_mode), ("structured", "hybrid"))
        self.assertIn("not NCR", r.reason)
        self.assertEqual(r.locations, ["Bangalore, Karnataka, IN"])

    def test_multi_city_with_ncr_passes(self) -> None:
        r = resolve("India", detail=parse_workday_detail(WORKDAY_JSON))
        self.assertTrue(r.location_ok)
        self.assertTrue(r.ncr_match)

    def test_other_country_rejected_even_when_remote(self) -> None:
        r = resolve("Bogotá, Bogotá, co (Remote)", detail=parse_smartrecruiters_posting(SR_JSON))
        self.assertFalse(r.location_ok)
        self.assertIn("outside India", r.reason)
        ph = DetailRecord(status="ok", locations=[DetailLocation(city="Taguig", region="NCR", country="PH")])
        self.assertFalse(resolve("Taguig, National Capital Region (NCR), Philippines", detail=ph).location_ok)

    def test_india_remote_passes_and_llm_narrows(self) -> None:
        self.assertTrue(resolve("Remote - India").location_ok)
        ok = resolve("India", llm={"cities": ["Gurgaon"], "countries": ["India"], "work_mode": "onsite", "remote_scope": "unknown"})
        self.assertTrue(ok.location_ok)
        self.assertEqual(ok.source, "llm")
        bad = resolve("India", llm={"cities": ["Bengaluru"], "countries": ["India"], "work_mode": "hybrid", "remote_scope": "unknown"})
        self.assertFalse(bad.location_ok)
        self.assertEqual(bad.locations, ["Bangalore"])

    def test_structured_beats_llm_and_listing_fallback_matches_filter(self) -> None:
        r = resolve("India", detail=parse_oracle_detail(ORACLE_JSON), llm={"cities": ["Gurgaon"], "countries": ["India"]})
        self.assertEqual((r.source, r.location_ok), ("structured", False))
        self.assertTrue(resolve("Gurugram, Haryana, India (Hybrid)").location_ok)
        self.assertFalse(resolve("Bengaluru").location_ok)

    def test_passes_predicate(self) -> None:
        self.assertTrue(passes("Bengaluru", {"en_location_ok": 1}))
        self.assertFalse(passes("Gurugram", {"en_location_ok": 0}))
        self.assertTrue(passes("Gurugram", None))
        self.assertFalse(passes("Bengaluru", {"en_location_ok": None}))

    def test_to_row_shape(self) -> None:
        row = resolve("India (Hybrid)", detail=parse_oracle_detail(ORACLE_JSON)).to_row()
        self.assertEqual(row["en_location_ok"], 0)
        self.assertEqual(row["en_resolution_source"], "structured")
        self.assertTrue(set(parse_oracle_detail(ORACLE_JSON).to_row()) <= {
            "en_detail_source", "en_detail_url", "en_detail_status", "en_locations_json", "en_workplace_type",
            "en_description_full", "en_posted_date", "en_employment_type"})


if __name__ == "__main__":
    unittest.main()
