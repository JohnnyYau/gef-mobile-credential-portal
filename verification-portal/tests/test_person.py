"""Person-in-context + web research tests.

Uses an isolated throwaway chain. Web backends are monkeypatched so no test
ever touches the network; the mock-mode fixture is tested directly.
"""

import json
import shutil
import unittest
from unittest.mock import patch

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(prefix="portal-person-test-")

import app.main as main  # noqa: E402
from app import chain_service, person_context, web_research  # noqa: E402
from app.chain_service import SAMPLE_DIPLOMA  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _issue(client, surname, given, sid, degree="Bachelor of Arts in History"):
    doc = json.loads(json.dumps(SAMPLE_DIPLOMA))
    doc["PersonalParticulars"]["Surname"] = surname
    doc["PersonalParticulars"]["GivenNames"] = given
    doc["PersonalParticulars"]["StudentID"] = sid
    doc["AcademicInfo"]["DegreeName"] = degree
    r = client.post("/api/issue", json={"document": doc})
    return r


class PersonContextTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # All test modules share the first-imported CHAIN_DIR (config reads the
        # env once) and the in-memory admin rate limiter. Earlier modules may
        # have corrupted the chain and accumulated limiter timestamps (a shared
        # TestClient IP), so re-seed fresh and lift the admin limit, matching
        # the pattern used by test_features/test_extra2.
        from app import config as cfg
        if cfg.CHAIN_DIR.exists():
            shutil.rmtree(str(cfg.CHAIN_DIR))
        chain_service.ensure_chain()
        cls.client = TestClient(main.app)
        cls._saved_admin = main.RATE_LIMIT_ADMIN_MAX
        main.RATE_LIMIT_ADMIN_MAX = 100000
        # a deterministic person for the tests (not part of the seed)
        _issue(cls.client, "NG", "KA LOK", "88990011",
               "Bachelor of Science in Data Science")
        # clear any chat sessions carried from previous modules
        person_context._sessions.clear()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP, ignore_errors=True)
        main.RATE_LIMIT_ADMIN_MAX = cls._saved_admin

    def chat(self, question, session_id=None, web=None):
        body = {"question": question}
        if session_id is not None:
            body["session_id"] = session_id
        if web is not None:
            body["web"] = web
        return self.client.post("/api/chat", json=body).json()

    # --- person resolution ---

    def test_person_resolved_by_name(self):
        res = self.chat("Tell me about NG KA LOK")
        p = res.get("person")
        self.assertIsNotNone(p)
        self.assertEqual(p["name"], "NG KA LOK")
        self.assertEqual(p["credential"]["degree"], "Bachelor of Science in Data Science")

    def test_person_resolved_by_student_id(self):
        res = self.chat("What degree does 88990011 hold?")
        self.assertEqual(res["person"]["name"], "NG KA LOK")

    def test_person_unknown_returns_null(self):
        res = self.chat("Tell me about NOBODY XYZ")
        self.assertIsNone(res.get("person"))

    # --- privacy masking ---

    def test_profile_masks_student_id_and_never_leaks_dob(self):
        res = self.chat("Tell me about NG KA LOK")
        p = res["person"]
        self.assertIn("****", p["student_id_masked"])
        self.assertNotIn("88990011", p["student_id_masked"])
        blob = json.dumps(p)
        self.assertNotIn("DOB", blob)
        self.assertNotIn("dob", blob)
        self.assertNotIn("20010101", blob)  # sample DOB must never appear

    def test_profile_record_has_no_dob(self):
        res = self.chat("Tell me about NG KA LOK")
        rec = [s for s in res["sources"] if s.get("kind") == "person_profile"]
        self.assertEqual(len(rec), 1)
        self.assertNotIn("DOB", rec[0]["text"])

    # --- session memory / anaphora ---

    def test_anaphoric_followup_uses_session_person(self):
        self.chat("Tell me about NG KA LOK", session_id="s1")
        res = self.chat("What degree does he hold?", session_id="s1")
        self.assertEqual(res["person"]["name"], "NG KA LOK")

    def test_anaphora_without_session_is_null(self):
        self.chat("Tell me about NG KA LOK", session_id="s2")
        res = self.chat("What degree does he hold?", session_id="s-other")
        self.assertIsNone(res.get("person"))

    # --- web research ---

    def test_web_flag_runs_research_with_name_only(self):
        with patch("app.chat_service.web_research.search_person",
                   side_effect=lambda name, org=None:
                   {"status": "ok", "queried": [name], "sources": [
                       {"title": "X", "url": "https://x.example/", "snippet": "s"}]}) as m:
            res = self.chat("Tell me about NG KA LOK", web=True)
        m.assert_called_once()
        called_name = m.call_args.args[0]
        self.assertEqual(called_name, "NG KA LOK")
        self.assertEqual(res["web"]["status"], "ok")
        self.assertIn("Web research", res["answer"])

    def test_web_keyword_auto_triggers(self):
        with patch("app.chat_service.web_research.search_person",
                   return_value={"status": "ok", "sources": [{"title": "t",
                              "url": "https://x/", "snippet": "s"}]}) as m:
            self.chat("Search the web for NG KA LOK")
        m.assert_called_once()

    def test_web_unavailable_is_honest(self):
        with patch("app.chat_service.web_research.search_person",
                   return_value={"status": "unavailable", "reason": "no internet"}):
            res = self.chat("Search the web for NG KA LOK")
        self.assertEqual(res["web"]["status"], "unavailable")
        self.assertIn("unavailable", res["answer"])

    def test_web_not_run_without_person(self):
        with patch("app.chat_service.web_research.search_person") as m:
            res = self.chat("Search the web for NOBODY XYZ", web=True)
        m.assert_not_called()
        self.assertIsNone(res.get("web"))

    # --- web_research unit: mock fixture + privacy ---

    def test_mock_fixture_is_labeled(self):
        saved = web_research.MOCK
        web_research.MOCK = True
        try:
            res = web_research.search_person("CHAN TAI MAN", "UNIVERSITY OF UTOPIA")
            self.assertEqual(res["status"], "ok")
            self.assertTrue(res["demo"])
            self.assertTrue(all(s.get("sample") for s in res["sources"]))
            res2 = web_research.search_person("NOBODY XYZ")
            self.assertEqual(res2["status"], "unavailable")
        finally:
            web_research.MOCK = saved

    def test_web_query_never_contains_student_id_or_dob(self):
        res = web_research.search_person("NG KA LOK", "UNIVERSITY OF UTOPIA")
        for q in res.get("queried", []):
            self.assertNotIn("88990011", q)
            self.assertNotIn("20010101", q)


class PrivacyPolicyTests(unittest.TestCase):
    """U5.3: the masking rules are a policy object, not a habit."""

    def setUp(self):
        from app.privacy import PRIVACY, PrivacyPolicy
        self.policy = PRIVACY
        self.Policy = PrivacyPolicy

    def test_whitelist_is_the_only_way_in(self):
        dirty = {
            "Surname": "NG", "GivenNames": "KA LOK", "StudentID": "88990011",
            "DOB": "20010101", "Email": "ng@example.com", "Sex": "M",
            "Nationality": "HK",
        }
        built = self.policy.build("PersonalParticulars", dirty)
        self.assertEqual(set(built), {"Surname", "GivenNames", "StudentID"})
        for key in ("DOB", "Email", "Sex", "Nationality"):
            self.assertNotIn(key, built)

    def test_even_a_whitelisted_name_cannot_smuggle_a_forbidden_field(self):
        # if someone ever adds "DOB" to the whitelist by accident, build() still
        # refuses it — the denylist is checked after the whitelist
        weird = self.Policy(whitelist={"PersonalParticulars":
                                       ("Surname", "DOB")})
        built = weird.build("PersonalParticulars",
                            {"Surname": "NG", "DOB": "20010101"})
        self.assertEqual(built, {"Surname": "NG"})

    def test_mask_student_id_keeps_prefix_and_drops_rest(self):
        self.assertEqual(self.policy.mask_student_id("88990011"), "8899****")
        self.assertEqual(self.policy.mask_student_id("123"), "****")
        self.assertEqual(self.policy.mask_student_id(""), "")
        self.assertEqual(self.policy.mask_student_id(None), "")

    def test_violations_finds_nested_forbidden_keys(self):
        bad = {"credential": {"degree": "BA"}, "DOB": "20010101",
               "extra": [{"Email": "x@y"}]}
        found = self.policy.violations(bad)
        self.assertEqual(len(found), 2, found)
        self.assertTrue(found[0].startswith("DOB"), found)

    def test_clean_profile_has_no_violations(self):
        clean = {"name": "NG KA LOK", "student_id_masked": "8899****",
                 "credential": {"degree": "BSc"}}
        self.assertEqual(self.policy.violations(clean), [])

    def test_real_profile_uses_only_whitelisted_credential_fields(self):
        # PersonContextTestCase drops its temp chain in tearDownClass, so seed
        # again here and use the demo person that ensure_chain() always writes.
        chain_service.ensure_chain()
        person = person_context.resolve_person("CHAN TAI MAN")
        self.assertIsNotNone(person)
        allowed = set(self.policy.fields("DocumentInfo")) \
            | set(self.policy.fields("AcademicInfo"))
        mapped = {"doc_type": "DocType", "degree": "DegreeName",
                  "start": "DegreeStartDate", "end": "DegreeEndDate",
                  "honour": "Honour", "issuing_org": "IssuingO",
                  "issuing_ou": "IssuingOU", "issued_on": "DateOfIssue"}
        for key in person["credential"]:
            self.assertIn(mapped[key], allowed, key)
        self.assertEqual(self.policy.violations(person), [])


class SessionStoreTests(unittest.TestCase):
    """U5.3: session memory sits behind a replaceable interface."""

    def setUp(self):
        from app import session_store
        self.ss = session_store
        self._saved = person_context._sessions

    def tearDown(self):
        person_context._sessions = self._saved

    def test_default_backend_is_in_memory_and_capped_by_config(self):
        from app.config import SESSION_LIMIT
        store = self.ss.open_session_store()
        self.assertEqual(store.limit, SESSION_LIMIT)

    def test_unknown_backend_falls_back_to_memory(self):
        store = self.ss.open_session_store("nowhere")
        self.assertIsInstance(store, self.ss.InMemorySessionStore)

    def test_redis_backend_is_an_honest_placeholder(self):
        # declaring it must not pretend to be a Redis implementation
        store = self.ss.open_session_store("redis")
        self.assertIsInstance(store, self.ss.InMemorySessionStore)

    def test_store_evicts_least_recently_used(self):
        store = self.ss.InMemorySessionStore(limit=2)
        store.set("a", {"name": "A"})
        store.set("b", {"name": "B"})
        self.assertEqual(store.get("a"), {"name": "A"})   # touch a
        store.set("c", {"name": "C"})                     # evicts b
        self.assertIsNone(store.get("b"))
        self.assertIsNotNone(store.get("a"))
        self.assertEqual(len(store), 2)

    def test_person_context_works_against_a_swapped_store(self):
        person_context._sessions = self.ss.InMemorySessionStore(limit=1)
        person = {"name": "NG KA LOK", "student_id_masked": "8899****",
                  "credential": {"degree": "BSc"}}
        person_context.remember("sA", person)
        self.assertIsNotNone(person_context.context_person("sA", "his degree"))
        # limit 1: the second session pushes the first out
        person_context.remember("sB", person)
        self.assertIsNone(person_context.context_person("sA", "his degree"))
        self.assertIsNotNone(person_context.context_person("sB", "his degree"))


if __name__ == "__main__":
    unittest.main()
