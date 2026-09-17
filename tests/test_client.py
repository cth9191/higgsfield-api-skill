"""Offline behavior tests. No credentials or paid requests."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hf", ROOT / "scripts/higgsfield_api.py")
hf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hf)
PROFILE = json.loads((ROOT / "references/models/seedance-2.5-text-to-video.json").read_text())
INPUT = {"prompt": "An ocean road", "duration": 5, "resolution": "720p"}
RID = "9417a243-e457-4075-895b-b68f3cda5303"
URL = f"{hf.BASE}/requests/{RID}/status"


class FakeClient:
    owner = "test-account"

    def __init__(self, cost="1.50", responses=None):
        self.cost = cost
        self.calls = []
        self.responses = list(responses or [])

    def estimate(self, model, payload):
        return hf.money(self.cost)

    def request(self, method, url, payload=None, timeout=30):
        self.calls.append((method, url))
        result = self.responses.pop(0) if self.responses else {"request_id": RID, "status": "queued", "status_url": URL}
        if isinstance(result, Exception):
            raise result
        return result


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = hf.Store(self.tmp.name)
        self.client = FakeClient()

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def submit(self, name="shot", client=None, payload=None, budget="batch", limit="3"):
        return hf.submit(self.store, client or self.client, PROFILE, payload or INPUT, name, budget, limit)

    def test_schema_rejects_wrong_model_parameters(self):
        for change in ({"resolution": "1080p"}, {"duration": 31}, {"duration": True}, {"image_url": "https://example.com/a.png"}):
            with self.subTest(change=change), self.assertRaises(hf.ClientError):
                hf.validate(PROFILE, {**INPUT, **change})
        self.assertEqual(hf.validate(PROFILE, INPUT), PROFILE["model"])

    def test_remote_schema_references_are_not_fetched(self):
        profile = {**PROFILE, "input_schema": {"type": "object", "$ref": "https://example.com/schema"}}
        with self.assertRaises(hf.ClientError):
            hf.validate(profile, INPUT)

    def test_duplicate_submission_posts_only_once(self):
        self.submit()
        self.submit()
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.store.get("shot", self.client.owner)["request_id"], RID)

    def test_same_job_different_input_rejected(self):
        self.submit()
        with self.assertRaises(hf.ClientError):
            self.submit(payload={**INPUT, "prompt": "Another scene"})
        self.assertEqual(len(self.client.calls), 1)

    def test_budget_is_cumulative(self):
        self.submit("one")
        self.submit("two")
        with self.assertRaisesRegex(hf.ClientError, "Budget exceeded"):
            self.submit("three")
        self.assertEqual(len(self.client.calls), 2)

    def test_no_budget_required_and_duplicates_still_protected(self):
        client = FakeClient(cost="50")
        first = hf.submit(self.store, client, PROFILE, INPUT, "uncapped")
        second = hf.submit(self.store, client, PROFILE, INPUT, "uncapped")
        self.assertEqual(first, second)
        self.assertEqual(first["estimate_usd"], "50")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM budgets").fetchone()[0], 0)

    def test_partial_or_empty_budget_rejected_before_request(self):
        for budget, limit in (("batch", None), (None, "3"), ("", "3"), ("batch", "0")):
            with self.subTest(budget=budget, limit=limit), self.assertRaises(hf.ClientError):
                hf.submit(self.store, self.client, PROFILE, INPUT, "shot", budget, limit)
        self.assertEqual(self.client.calls, [])

    def test_budget_mode_cannot_change_for_existing_job(self):
        self.submit("capped")
        with self.assertRaises(hf.ClientError):
            hf.submit(self.store, self.client, PROFILE, INPUT, "capped")
        hf.submit(self.store, self.client, PROFILE, INPUT, "uncapped")
        with self.assertRaises(hf.ClientError):
            self.submit("uncapped")
        self.assertEqual(len(self.client.calls), 2)

    def test_uncapped_unknown_submission_is_not_retried(self):
        client = FakeClient(responses=[hf.ApiError()])
        with self.assertRaises(hf.ApiError):
            hf.submit(self.store, client, PROFILE, INPUT, "unknown")
        self.assertEqual(hf.submit(self.store, client, PROFILE, INPUT, "unknown")["status"], "unknown")
        self.assertEqual(len(client.calls), 1)

    def test_cli_submit_without_budget(self):
        request = Path(self.tmp.name) / "request.json"
        request.write_text(json.dumps(INPUT))
        with patch.object(hf, "Client", return_value=self.client), patch("sys.stdout", new_callable=io.StringIO):
            result = hf.main(["--state-dir", self.tmp.name, "submit", "--profile",
                              str(ROOT / "references/models/seedance-2.5-text-to-video.json"),
                              "--input", str(request), "--job", "cli-uncapped"])
        self.assertEqual(result, 0)
        self.assertEqual(len(self.client.calls), 1)

    def test_budget_cannot_silently_change(self):
        self.submit()
        with self.assertRaises(hf.ClientError):
            self.submit("two", limit="100")

    def test_ambiguous_post_never_retried_and_reservation_retained(self):
        client = FakeClient(responses=[hf.ApiError()])
        with self.assertRaises(hf.ApiError):
            self.submit(client=client)
        self.assertEqual(self.submit(client=client)["status"], "unknown")
        self.assertEqual(len(client.calls), 1)
        with self.assertRaises(hf.ClientError):
            self.submit("next", client=FakeClient(cost="2"))

    def test_rejected_job_releases_budget_but_is_not_automatically_resubmitted(self):
        client = FakeClient(responses=[hf.ApiError(429)])
        with self.assertRaises(hf.ApiError):
            self.submit(client=client)
        self.assertEqual(self.submit(client=client)["status"], "rejected")
        self.submit("next", client=FakeClient(cost="3"))
        self.assertEqual(len(client.calls), 1)

    def test_poll_stops_for_all_terminal_states(self):
        for terminal in hf.TERMINAL:
            name = "shot-" + terminal
            client = FakeClient(cost="0", responses=[
                {"request_id": RID, "status": "queued", "status_url": URL},
                {"request_id": RID, "status": terminal}])
            self.submit(name, client=client)
            result = hf.wait_job(self.store, client, name, 30)
            self.assertEqual(result["status"], terminal)
            self.assertEqual(len(client.calls), 2)
            hf.status_job(self.store, client, name)
            self.assertEqual(len(client.calls), 2)

    def test_status_errors_backoff_without_reposting(self):
        self.submit()
        self.client.responses = [hf.ApiError(503), hf.ApiError(429), {"request_id": RID, "status": "completed"}]
        sleeps = []
        result = hf.wait_job(self.store, self.client, "shot", 30, sleep=sleeps.append)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(sum(m == "POST" for m, _ in self.client.calls), 1)
        self.assertEqual(len(sleeps), 2)
        self.assertGreater(sleeps[1], sleeps[0])

    def test_timeout_can_resume(self):
        self.submit()
        now = [0.0]
        def sleep(delay):
            now[0] += delay
        with self.assertRaisesRegex(hf.ClientError, "deadline"):
            hf.wait_job(self.store, self.client, "shot", 3, sleep=sleep, clock=lambda: now[0])
        self.client.responses = [{"request_id": RID, "status": "completed"}]
        self.assertEqual(hf.wait_job(self.store, self.client, "shot", 30)["status"], "completed")
        self.assertEqual(sum(m == "POST" for m, _ in self.client.calls), 1)

    def test_other_credential_cannot_read_poll_or_reuse_job(self):
        self.submit()
        other = FakeClient()
        other.owner = "other-account"
        for operation in (lambda: hf.status_job(self.store, other, "shot"), lambda: self.submit(client=other)):
            with self.assertRaises(hf.ClientError):
                operation()
        self.assertEqual(other.calls, [])

    def test_response_request_id_must_match(self):
        self.submit()
        self.client.responses = [{"request_id": "11111111-1111-4111-8111-111111111111", "status": "completed"}]
        with self.assertRaises(hf.ClientError):
            hf.status_job(self.store, self.client, "shot")
        self.assertEqual(self.store.get("shot", self.client.owner)["status"], "queued")

    def test_bad_status_url_never_receives_credentials(self):
        self.client.responses = [{"request_id": RID, "status": "queued", "status_url": "https://evil.example/status"}]
        with self.assertRaises(hf.ClientError):
            self.submit()
        self.assertEqual(self.store.get("shot", self.client.owner)["status"], "unknown")
        with self.assertRaises(hf.ClientError):
            hf.status_job(self.store, self.client, "shot")
        self.assertEqual(len(self.client.calls), 1)

    def test_attach_recovers_unknown_job(self):
        self.client.responses = [hf.ApiError()]
        with self.assertRaises(hf.ApiError):
            self.submit()
        self.client.responses = [{"request_id": RID, "status": "in_progress"}]
        result = hf.attach(self.store, self.client, "shot", RID)
        self.assertEqual(result["status"], "in_progress")
        self.assertEqual(sum(m == "POST" for m, _ in self.client.calls), 1)

    def test_invalid_money(self):
        for value in ("NaN", "Infinity", "-1", "abc"):
            with self.assertRaises(hf.ClientError):
                hf.money(value)

    def test_media_private_host_blocked(self):
        with patch.object(hf.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaises(hf.ClientError):
                hf.public_url("https://example.com/video.mp4")

    def test_download_writes_file_without_api_auth_and_refuses_overwrite(self):
        self.submit()
        hf.save_remote(self.store, "shot", {"request_id": RID, "status": "completed", "video": {"url": "https://media.example/video.mp4"}})
        requests = []
        class Opener:
            def open(self, request, timeout):
                requests.append(request)
                return io.BytesIO(b"test video bytes")
        destination = Path(self.tmp.name) / "outputs"
        with patch.object(hf, "public_url", side_effect=lambda value: value), patch.object(hf, "build_opener", return_value=Opener()):
            result = hf.download(self.store, self.client, "shot", destination)
            self.assertEqual(Path(result["files"][0]).read_bytes(), b"test video bytes")
            self.assertIsNone(requests[0].get_header("Authorization"))
            with self.assertRaises(hf.ClientError):
                hf.download(self.store, self.client, "shot", destination)
        self.assertEqual(len(requests), 1)

    def test_upload_uses_only_storage_headers(self):
        path = Path(self.tmp.name) / "reference.png"
        path.write_bytes(b"test image bytes")
        self.client.responses = [{"upload_url": "https://storage.example/upload", "public_url": "https://media.example/reference.png", "upload_headers": {"Content-Type": "image/png", "x-amz-tagging": "retention=temporary"}}]
        requests = []
        class Response(io.BytesIO):
            status = 200
        class Opener:
            def open(self, request, timeout):
                requests.append(request)
                return Response()
        with patch.object(hf, "public_url", side_effect=lambda value: value), patch.object(hf, "build_opener", return_value=Opener()):
            result = hf.upload(self.client, path)
        self.assertEqual(result["public_url"], "https://media.example/reference.png")
        self.assertEqual(requests[0].method, "PUT")
        self.assertEqual(requests[0].get_header("X-amz-tagging"), "retention=temporary")
        self.assertIsNone(requests[0].get_header("Authorization"))

    def test_http_client_uses_production_authorization(self):
        requests = []
        class Opener:
            def open(self, request, timeout):
                requests.append(request)
                return io.BytesIO(b'{"usd":"1.23"}')
        with patch.dict(hf.os.environ, {"HF_API_KEY_ID": "test-key", "HF_API_KEY_SECRET": "test-secret"}, clear=True), patch.object(hf, "build_opener", return_value=Opener()):
            client = hf.Client()
            self.assertEqual(client.estimate(PROFILE["model"], INPUT), hf.money("1.23"))
            self.assertEqual(requests[0].get_header("Authorization"), "Key test-key:test-secret")
            self.assertEqual(requests[0].get_header("Content-type"), "application/json")
            with self.assertRaises(hf.ClientError):
                client.request("GET", "https://other.example/status")
            self.assertEqual(len(requests), 1)

    def test_concurrent_submissions_only_one_post(self):
        barrier = threading.Barrier(2)
        calls = []
        errors = []
        class RacingClient(FakeClient):
            def estimate(self, model, payload):
                barrier.wait(timeout=5)
                return hf.money("1")
            def request(self, *args, **kwargs):
                calls.append(args[0])
                return super().request(*args, **kwargs)
        def run():
            local = hf.Store(self.tmp.name)
            try:
                hf.submit(local, RacingClient(), PROFILE, INPUT, "racing", "racing-budget", "3")
            except Exception as exc:
                errors.append(exc)
            finally:
                local.db.close()
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(calls, ["POST"])


if __name__ == "__main__":
    unittest.main()
