from __future__ import annotations

import asyncio
import json
import unittest

import httpx

from mnc_careers.ats import FETCHERS, detect_ats, parse_target, strip_search_params
from mnc_careers.ats.base import RawPosting, paginate
from mnc_careers.ats.successfactors import parse_listing
from mnc_careers.registry import MNC


class _Log:
    def debug(self, *a, **k): ...
    def info(self, *a, **k): ...
    def warning(self, *a, **k): ...
    def bind(self, **k): return self


LOG = _Log()


class DetectTests(unittest.TestCase):
    def test_detects_each_ats(self) -> None:
        cases = {
            "https://autodesk.wd1.myworkdayjobs.com/en-US/Ext?q=product+manager": "workday",
            "https://fiserv.wd5.myworkdayjobs.com/ASC": "workday",
            "https://boards.greenhouse.io/razorpaysoftwareprivatelimited": "greenhouse",
            "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true": "greenhouse",
            "https://jobs.lever.co/Sprinto": "lever",
            "https://api.lever.co/v0/postings/sprinto?mode=json": "lever",
            "https://jobs.smartrecruiters.com/Freshworks": "smartrecruiters",
            "https://paypal.eightfold.ai/careers": "eightfold",
            "https://jobs.sap.com/search/?q=product+manager&locationsearch=India": "successfactors",
            "https://www.amazon.jobs/en/search.json?base_query=x": "amazon_jobs",
            "https://careers-x.icims.com/jobs/search?ss=1": "icims",
            "https://x.taleo.net/careersection/2/jobsearch.ftl": "taleo",
            "https://careers.adobe.com/us/en/search-results?keywords=product": "phenom",
            "https://jobs.fidelity.com/job-search-results/?keyword=pm": "phenom",  # heuristic; NotThisATS reroutes non-Phenom sites
            "https://jobs.intuit.com/search-jobs/product%20manager/India": "radancy",
            "https://stripe.com/jobs/search?q=product+manager": "",  # not SuccessFactors (no trailing /search/)
            "": "",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(detect_ats(url), expected)

    def test_parse_workday_targets(self) -> None:
        t = parse_target("https://autodesk.wd1.myworkdayjobs.com/en-US/Ext?q=product+manager", "workday")
        self.assertEqual((t["host"], t["tenant"], t["site"]), ("autodesk.wd1.myworkdayjobs.com", "autodesk", "Ext"))
        t = parse_target("https://fiserv.wd5.myworkdayjobs.com/ASC", "workday")
        self.assertEqual(t["site"], "ASC")
        t = parse_target("https://x.wd3.myworkdayjobs.com/wday/cxs/tenantx/SiteY/jobs", "workday")
        self.assertEqual((t["tenant"], t["site"]), ("tenantx", "SiteY"))

    def test_parse_other_targets(self) -> None:
        self.assertEqual(parse_target("https://boards-api.greenhouse.io/v1/boards/stripe/jobs", "greenhouse")["board"], "stripe")
        self.assertEqual(parse_target("https://boards.greenhouse.io/razorpay", "greenhouse")["board"], "razorpay")
        self.assertEqual(parse_target("https://jobs.lever.co/Sprinto", "lever")["slug"], "Sprinto")
        self.assertEqual(parse_target("https://jobs.smartrecruiters.com/Freshworks", "smartrecruiters")["company"], "Freshworks")
        self.assertEqual(parse_target("https://careers.ey.com/ey/search/?q=pm", "successfactors")["base"], "https://careers.ey.com/ey/search/")

    def test_strip_search_params(self) -> None:
        self.assertEqual(strip_search_params("https://a.com/jobs?q=product+manager&location=India"), "https://a.com/jobs?location=India")
        self.assertEqual(strip_search_params("https://a.com/jobs?keywords=pm"), "https://a.com/jobs")
        self.assertEqual(strip_search_params("https://a.com/jobs"), "https://a.com/jobs")


class PaginateTests(unittest.TestCase):
    def test_advances_by_returned_and_trusts_first_total(self) -> None:
        pages = {0: ([RawPosting("a", "x", "u1"), RawPosting("b", "x", "u2")], 5),
                 2: ([RawPosting("c", "x", "u3"), RawPosting("d", "x", "u4")], 0),   # Workday-style bogus later total
                 4: ([RawPosting("e", "x", "u5")], 0)}

        async def fetch_page(offset):
            return pages.get(offset, ([], None))

        r = asyncio.run(paginate(fetch_page, cap=100, log=LOG, company="t", strategy="s"))
        self.assertEqual(len(r.postings), 5)
        self.assertEqual(r.total_reported, 5)
        self.assertFalse(r.cap_hit)
        self.assertEqual(r.pages, 3)

    def test_cap_hit(self) -> None:
        async def fetch_page(offset):
            return [RawPosting(f"t{offset+i}", "x", f"u{offset+i}") for i in range(20)], 1000

        r = asyncio.run(paginate(fetch_page, cap=40, log=LOG, company="t", strategy="s"))
        self.assertTrue(r.cap_hit)
        self.assertEqual(len(r.postings), 40)

    def test_stalls_when_server_ignores_offset(self) -> None:
        async def fetch_page(offset):
            return [RawPosting("same", "x", "same-url")], 50

        r = asyncio.run(paginate(fetch_page, cap=100, log=LOG, company="t", strategy="s"))
        self.assertEqual(len(r.postings), 1)


def _run_fetcher(ats: str, mnc: MNC, handler) -> "FetchResult":  # noqa: F821
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await FETCHERS[ats](mnc, client, cap=100, net_keywords=["product"], title_predicate=lambda t: "product manager" in t.lower(),
                                       host_sem=asyncio.Semaphore(2), log=LOG)
    return asyncio.run(go())


class FetcherShapeTests(unittest.TestCase):
    def test_workday_pages_and_multi_location_resolution(self) -> None:
        mnc = MNC("Acme", "https://acme.com", "", "https://acme.wd1.myworkdayjobs.com/en-US/Ext?q=product+manager")
        calls: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(f"{req.method} {req.url.path}")
            if req.url.path == "/Ext":
                return httpx.Response(200, text="<html></html>")
            if req.url.path == "/wday/cxs/acme/Ext/jobs":
                body = json.loads(req.content)
                if body["offset"] == 0:
                    return httpx.Response(200, json={"total": 3, "jobPostings": [
                        {"title": "Senior Product Manager", "externalPath": "/job/Bengaluru/SPM_1", "locationsText": "3 Locations", "postedOn": "Posted Today", "bulletFields": ["1"]},
                        {"title": "Engineer", "externalPath": "/job/Pune/Eng_2", "locationsText": "2 Locations"},
                    ]})
                return httpx.Response(200, json={"total": 0, "jobPostings": [
                    {"title": "Product Manager II", "externalPath": "/job/Gurugram/PM_3", "locationsText": "Gurugram, IND"}]})
            if req.url.path == "/wday/cxs/acme/Ext/job/Bengaluru/SPM_1":
                return httpx.Response(200, json={"jobPostingInfo": {"location": "Bengaluru, IND", "additionalLocations": ["Gurugram, IND", "Pune, IND"], "jobDescription": "<p>desc</p>"}})
            return httpx.Response(404)

        r = _run_fetcher("workday", mnc, handler)
        self.assertEqual(len(r.postings), 3)
        self.assertEqual(r.total_reported, 3)
        by_title = {p.title: p for p in r.postings}
        self.assertEqual(by_title["Senior Product Manager"].location, "Bengaluru, IND; Gurugram, IND; Pune, IND")
        self.assertEqual(by_title["Engineer"].location, "2 Locations")  # not resolved: title fails predicate
        self.assertEqual(by_title["Product Manager II"].url, "https://acme.wd1.myworkdayjobs.com/Ext/job/Gurugram/PM_3")
        self.assertNotIn("GET /wday/cxs/acme/Ext/job/Pune/Eng_2", calls)

    def test_greenhouse(self) -> None:
        mnc = MNC("Acme", "https://acme.com", "", "https://boards.greenhouse.io/acme")

        def handler(req: httpx.Request) -> httpx.Response:
            self.assertEqual(req.url.path, "/v1/boards/acme/jobs")
            return httpx.Response(200, json={"jobs": [
                {"id": 1, "title": "Product Manager", "location": {"name": "Gurugram"}, "absolute_url": "https://boards.greenhouse.io/acme/jobs/1", "updated_at": "2026-09-01"},
                {"id": 2, "title": "Designer", "location": {"name": ""}, "offices": [{"name": "Noida"}], "absolute_url": "https://boards.greenhouse.io/acme/jobs/2"},
            ], "meta": {"total": 2}})

        r = _run_fetcher("greenhouse", mnc, handler)
        self.assertEqual([p.location for p in r.postings], ["Gurugram", "Noida"])
        self.assertEqual(r.total_reported, 2)

    def test_lever(self) -> None:
        mnc = MNC("Acme", "https://acme.com", "", "https://jobs.lever.co/acme")

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[
                {"id": "x", "text": "Product Manager", "categories": {"location": "Remote (India)", "allLocations": ["Remote (India)", "Gurugram"]}, "hostedUrl": "https://jobs.lever.co/acme/x", "createdAt": 1789497000000},
            ])

        r = _run_fetcher("lever", mnc, handler)
        self.assertEqual(r.postings[0].location, "Remote (India); Gurugram")

    def test_smartrecruiters_pagination(self) -> None:
        mnc = MNC("Acme", "https://acme.com", "", "https://jobs.smartrecruiters.com/Acme")

        def handler(req: httpx.Request) -> httpx.Response:
            offset = int(req.url.params.get("offset", 0))
            if offset == 0:
                return httpx.Response(200, json={"totalFound": 3, "content": [
                    {"id": "1", "name": "Product Manager", "location": {"city": "Bengaluru", "country": "in"}},
                    {"id": "2", "name": "Engineer", "location": {"city": "Chennai", "country": "in", "remote": True}}]})
            return httpx.Response(200, json={"totalFound": 3, "content": [{"id": "3", "name": "Staff Product Manager", "location": {"city": "Gurugram", "country": "in"}}]})

        r = _run_fetcher("smartrecruiters", mnc, handler)
        self.assertEqual(len(r.postings), 3)
        self.assertEqual(r.postings[1].location, "Chennai, in (Remote)")
        self.assertEqual(r.postings[2].url, "https://jobs.smartrecruiters.com/Acme/3")

    def test_phenom_widgets_and_not_this_ats(self) -> None:
        from mnc_careers.ats.base import NotThisATS

        mnc = MNC("Acme", "https://careers.acme.com", "", "https://careers.acme.com/global/en/search-results?keywords=pm")

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/global/en/search-results":
                return httpx.Response(200, text='<html>phApp.ddo = {"siteConfig":{"data":{"locale":"en_global"}}}; "pageId":"page17"</html>')
            if req.url.path == "/widgets":
                body = json.loads(req.content)
                assert body["lang"] == "en_global" and body["pageId"] == "page17" and body["country"] == "global"
                if body["from"] == 0:
                    return httpx.Response(200, json={"refineSearch": {"totalHits": 3, "data": {"jobs": [
                        {"title": "Product Manager", "cityStateCountry": "NEW DELHI, Delhi, India", "applyUrl": "https://apply.acme/1", "jobSeqNo": "A1"},
                        {"title": "Engineer", "city": "Pune", "country": "India", "jobSeqNo": "A2"}]}}})
                return httpx.Response(200, json={"refineSearch": {"totalHits": 3, "data": {"jobs": [
                    {"title": "Senior Product Manager", "location": "Gurugram, Haryana, India", "jobSeqNo": "A3", "isMultiLocation": True,
                     "multi_location_array": [{"location": "Gurugram, Haryana, India"}, {"location": "Bengaluru, Karnataka, India"}]}]}}})
            return httpx.Response(404)

        r = _run_fetcher("phenom", mnc, handler)
        self.assertEqual([p.url for p in r.postings], ["https://apply.acme/1", "https://careers.acme.com/global/en/job/A2", "https://careers.acme.com/global/en/job/A3"])
        self.assertEqual(r.postings[1].location, "Pune, India")
        self.assertEqual(r.postings[2].location, "Gurugram, Haryana, India; Bengaluru, Karnataka, India")
        self.assertEqual(r.total_reported, 3)

        def not_phenom(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>some other vendor</html>")

        with self.assertRaises(NotThisATS):
            _run_fetcher("phenom", mnc, not_phenom)

    def test_radancy_and_avature_reroute_on_first_page_mismatch(self) -> None:
        """URL-shape detections: a first unfiltered page that isn't that ATS → NotThisATS (reroute)."""
        from mnc_careers.ats.base import NotThisATS

        radancy = MNC("Acme", "https://jobs.acme.com", "", "https://jobs.acme.com/search-jobs/product%20manager/India")
        avature = MNC("Beta", "https://careers.beta.com", "", "https://careers.beta.com/en-US/careers/SearchJobs")

        def radancy_ok(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/search-jobs/results":
                page = int(req.url.params["CurrentPage"])
                if page == 1:
                    return httpx.Response(200, json={"results": '<section data-total-results="2"><a href="/job/gurugram/product-manager/1/1"><h2>Product Manager</h2>'
                                                                '<span class="job-location">Multiple Locations</span></a></section>'})
                return httpx.Response(200, json={"results": ""})
            return httpx.Response(404)

        for ats, mnc, status in (("radancy", radancy, 404), ("radancy", radancy, 403), ("radancy", radancy, 500)):
            with self.assertRaises(NotThisATS, msg=f"{ats} {status}"):
                _run_fetcher(ats, mnc, lambda req, status=status: httpx.Response(status, text="nope"))
        with self.assertRaises(NotThisATS):  # 200 but not JSON
            _run_fetcher("radancy", radancy, lambda req: httpx.Response(200, text="<html>SuccessFactors classic</html>"))

        r = _run_fetcher("radancy", radancy, radancy_ok)
        self.assertEqual(r.postings[0].location, "Gurugram")  # city recovered from the /job/{city}/ path
        self.assertEqual(r.total_reported, 2)

        with self.assertRaises(NotThisATS):
            _run_fetcher("avature", avature, lambda req: httpx.Response(200, text="<html><title>Beta - Careers</title><script src='x.js'></script></html>"))
        with self.assertRaises(NotThisATS):
            _run_fetcher("avature", avature, lambda req: httpx.Response(403, text="denied"))

        def avature_ok(req: httpx.Request) -> httpx.Response:
            if int(req.url.params.get("jobOffset", 0)) == 0:
                return httpx.Response(200, text='<p>1 results</p><article class="article--result"><h3><a href="/en-US/careers/JobDetail/PM/9">Product Manager</a></h3>'
                                                '<span class="list-item-location">Gurugram, India</span></article>')
            return httpx.Response(200, text="<p>1 results</p>")

        r = _run_fetcher("avature", avature, avature_ok)
        self.assertEqual([(p.title, p.location) for p in r.postings], [("Product Manager", "Gurugram, India")])
        self.assertTrue(r.postings[0].url.startswith("https://careers.beta.com/en-US/careers/JobDetail/PM/9"))

    def test_successfactors_parse_listing(self) -> None:
        html = """
        <table><tr class="data-row"><td><a class="jobTitle-link" href="/job/Gurugram-Product-Manager/1/">Product Manager</a></td>
        <td><span class="jobLocation">Gurugram, IN, 122002</span></td><td><span class="jobDate">Sep 15, 2026</span></td></tr></table>
        <span class="paginationLabel">Results 1 – 25 of 1,234</span>"""
        postings, total = parse_listing(html, "https://jobs.acme.com/search/")
        self.assertEqual(total, 1234)
        self.assertEqual(postings[0].url, "https://jobs.acme.com/job/Gurugram-Product-Manager/1/")
        self.assertEqual(postings[0].location, "Gurugram, IN, 122002")


if __name__ == "__main__":
    unittest.main()
