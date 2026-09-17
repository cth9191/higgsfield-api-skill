"""Local, resumable Higgsfield REST client. Credentials are environment-only."""
import argparse
import hashlib
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import random
import re
import socket
import sqlite3
import sys
import time
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from uuid import UUID

BASE = "https://api.higgsfield.ai"
TERMINAL = {"completed", "failed", "nsfw", "canceled"}
REMOTE_STATES = TERMINAL | {"queued", "in_progress"}
RELEASED = {"rejected", "failed", "nsfw", "canceled"}
MAX_FILE = 256 * 1024 * 1024


class ClientError(Exception):
    pass


class ApiError(ClientError):
    def __init__(self, code=0, correlation=""):
        self.code = code
        self.correlation = correlation if re.fullmatch(r"[A-Za-z0-9_.:-]{1,150}", correlation) else ""
        super().__init__(f"API HTTP {code}" if code else "Network failure; request outcome may be unknown")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def money(value):
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ClientError("Invalid USD amount") from None
    if not amount.is_finite() or amount < 0:
        raise ClientError("USD amount must be finite and nonnegative")
    return amount


def api_url(url):
    p = urlsplit(url)
    if p.scheme != "https" or p.netloc != "api.higgsfield.ai" or p.fragment:
        raise ClientError("Refusing authenticated request outside the production API")
    return url


def public_url(url):
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ClientError("Media URL must be public HTTPS without embedded credentials")
    try:
        addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise ClientError("Cannot resolve media host") from None
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ClientError("Refusing non-public media host")
    return url


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def validate(profile, payload):
    from jsonschema import validators, FormatChecker
    from referencing import Registry
    from referencing.exceptions import NoSuchResource

    model = profile.get("model", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)+", model) or any(x in (".", "..") for x in model.split("/")):
        raise ClientError("Profile needs an exact production model path")
    if profile.get("environment") != "production":
        raise ClientError("Only production profiles are supported")
    source = urlsplit(profile.get("source_url", ""))
    if source.scheme != "https" or source.netloc not in ("console.higgsfield.ai", "docs.higgsfield.ai"):
        raise ClientError("Profile must cite official model documentation")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", profile.get("verified_at", "")):
        raise ClientError("Profile needs a verification date")
    if not isinstance(payload, dict):
        raise ClientError("Request JSON must be an object")
    schema = profile["input_schema"]
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ClientError("Profile needs a model input object schema")

    def deny_remote(uri):
        raise NoSuchResource(ref=uri)

    cls = validators.validator_for(schema)
    cls.check_schema(schema)
    validator = cls(schema, registry=Registry(retrieve=deny_remote), format_checker=FormatChecker())
    try:
        issue = next(validator.iter_errors(payload), None)
    except Exception:
        raise ClientError("Schema could not be resolved; inline documented external references") from None
    if issue:
        location = ".".join(map(str, issue.absolute_path)) or "request"
        raise ClientError(f"Invalid input at {location} ({issue.validator}); inspect the model schema")
    # JSON excludes NaN and infinities even though Python's decoder accepts them.
    json.dumps(payload, allow_nan=False)
    return model


class Client:
    def __init__(self):
        key_id = os.environ.get("HF_API_KEY_ID", "").strip()
        secret = os.environ.get("HF_API_KEY_SECRET", "").strip()
        if bool(key_id) != bool(secret):
            raise ClientError("Set both HF_API_KEY_ID and HF_API_KEY_SECRET")
        if not key_id:
            combined = os.environ.get("HF_CREDENTIALS") or os.environ.get("HF_KEY", "")
            key_id, _, secret = combined.partition(":")
        if not key_id or not secret or any(c.isspace() for c in key_id + secret):
            raise ClientError("Configure Higgsfield credentials in the process environment")
        self.owner = hashlib.sha256(key_id.encode()).hexdigest()
        self._auth = f"Key {key_id}:{secret}"

    def request(self, method, url, payload=None, timeout=30):
        api_url(url)
        data = None if payload is None else json.dumps(payload, allow_nan=False).encode()
        req = Request(url, data=data, method=method, headers={"Authorization": self._auth, "Content-Type": "application/json"})
        try:
            with build_opener(NoRedirect()).open(req, timeout=timeout) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ClientError("API response exceeded size limit")
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ClientError("Unexpected API response shape")
                return result
        except HTTPError as exc:
            raise ApiError(exc.code, exc.headers.get("X-Correlation-ID", "")) from None
        except (URLError, TimeoutError, OSError):
            raise ApiError() from None
        except (ValueError, UnicodeError):
            raise ClientError("Invalid JSON response; submission outcome may be unknown") from None

    def estimate(self, model, payload):
        result = self.request("POST", f"{BASE}/estimate/{model}", payload)
        if "usd" not in result:
            raise ClientError("Estimate missing USD amount; no generation submitted")
        return money(result["usd"])


class Store:
    def __init__(self, directory):
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path / "jobs.sqlite3", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS budgets (
            name TEXT PRIMARY KEY, owner TEXT NOT NULL, limit_usd TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS jobs (
            name TEXT PRIMARY KEY, owner TEXT NOT NULL, fingerprint TEXT NOT NULL,
            budget TEXT NOT NULL, model TEXT NOT NULL, input_json TEXT NOT NULL,
            estimate_usd TEXT NOT NULL, status TEXT NOT NULL,
            request_id TEXT, status_url TEXT, response_json TEXT, correlation TEXT);
        """)

    def get(self, name, owner):
        row = self.db.execute("SELECT * FROM jobs WHERE name=?", (name,)).fetchone()
        if row is None:
            raise ClientError("Job not found in this state directory")
        if row["owner"] != owner:
            raise ClientError("Job belongs to a different API credential")
        return dict(row)

    def update(self, name, **fields):
        allowed = {"status", "request_id", "status_url", "response_json", "correlation"}
        if not fields or not set(fields) <= allowed:
            raise ClientError("Invalid job update")
        assignments = ",".join(f"{k}=?" for k in fields)
        with self.db:
            self.db.execute(f"UPDATE jobs SET {assignments} WHERE name=?", (*fields.values(), name))


def summary(job):
    return {k: job[k] for k in ("name", "model", "status", "request_id", "estimate_usd", "budget")}


def identity(model, payload):
    data = json.dumps([model, payload], sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def submit(store, client, profile, payload, name, budget=None, limit=None):
    model = validate(profile, payload)
    fingerprint = identity(model, payload)
    if not name.strip():
        raise ClientError("A job name is required")
    if (budget is None) != (limit is None):
        raise ClientError("Supply both --budget-id and --budget-usd, or omit both")
    if budget is not None:
        limit = money(limit)
        if limit <= 0 or not budget.strip():
            raise ClientError("Budget ID must be nonempty and its limit positive")
    # Empty budget keeps old NOT NULL ledgers compatible; no budget row is created.
    budget = budget or ""

    def existing():
        row = store.db.execute("SELECT * FROM jobs WHERE name=?", (name,)).fetchone()
        if not row:
            return None
        record = store.get(name, client.owner)
        if record["fingerprint"] != fingerprint or record["budget"] != budget:
            raise ClientError("Job ID already exists with different inputs or budget; it will not be resubmitted")
        if budget:
            budget_row = store.db.execute("SELECT limit_usd FROM budgets WHERE name=?", (budget,)).fetchone()
            if not budget_row or money(budget_row[0]) != limit:
                raise ClientError("Existing budget limit differs")
        return summary(record)

    result = existing()
    if result:
        return result
    estimate = client.estimate(model, payload)
    # Acquire a write lock, recheck duplicates, and reserve before any paid POST.
    try:
        store.db.execute("BEGIN IMMEDIATE")
        result = existing()
        if result:
            store.db.rollback()
            return result
        if budget:
            b = store.db.execute("SELECT * FROM budgets WHERE name=?", (budget,)).fetchone()
            if b and (b["owner"] != client.owner or money(b["limit_usd"]) != limit):
                raise ClientError("Budget belongs to another credential or its saved limit differs")
            used = sum((money(r[0]) for r in store.db.execute(
                "SELECT estimate_usd,status FROM jobs WHERE budget=?", (budget,)) if r[1] not in RELEASED), Decimal(0))
            if used + estimate > limit:
                raise ClientError(f"Budget exceeded: estimated {estimate} USD, remaining {limit - used} USD")
            if not b:
                store.db.execute("INSERT INTO budgets VALUES(?,?,?)", (budget, client.owner, str(limit)))
        store.db.execute("INSERT INTO jobs(name,owner,fingerprint,budget,model,input_json,estimate_usd,status) VALUES(?,?,?,?,?,?,?,?)",
                         (name, client.owner, fingerprint, budget, model, json.dumps(payload), str(estimate), "submitting"))
        store.db.commit()
    except Exception:
        store.db.rollback()
        raise
    try:
        result = client.request("POST", f"{BASE}/{model}", payload)
        save_remote(store, name, result, require_url=True)
    except Exception as exc:
        rejected = isinstance(exc, ApiError) and exc.code in (400, 401, 403, 404, 422, 423, 429)
        store.update(name, status="rejected" if rejected else "unknown", correlation=getattr(exc, "correlation", ""))
        raise
    return summary(store.get(name, client.owner))


def save_remote(store, name, result, require_url=False):
    status = result.get("status")
    if status not in REMOTE_STATES:
        raise ClientError("Unrecognized provider status; preserve the job and check current docs")
    rid = result.get("request_id", "")
    try:
        UUID(rid)
    except (ValueError, TypeError, AttributeError):
        raise ClientError("Response lacks a valid request ID") from None
    previous = store.db.execute("SELECT request_id,status FROM jobs WHERE name=?", (name,)).fetchone()
    if previous["request_id"] and previous["request_id"] != rid:
        raise ClientError("Response request ID does not match the saved job")
    # Retain terminal observations if a concurrent poll returns an older state.
    if previous["status"] in TERMINAL and status not in TERMINAL:
        return
    fields = {"status": status, "request_id": rid, "response_json": json.dumps(result)}
    if "status_url" in result:
        url = api_url(result["status_url"])
        if urlsplit(url).path != f"/requests/{rid}/status" or urlsplit(url).query:
            raise ClientError("Status URL does not match the accepted request")
        fields["status_url"] = url
    elif require_url and status not in TERMINAL:
        # Preserve the known request ID for manual recovery, without resubmitting.
        store.update(name, request_id=rid)
        raise ClientError("Accepted request has no status URL; use attach to recover")
    store.update(name, **fields)


def status_job(store, client, name, timeout=30):
    job = store.get(name, client.owner)
    if job["status"] in TERMINAL:
        return summary(job)
    if not job["status_url"]:
        raise ClientError("No polling URL: inspect the console and attach the matching request; do not resubmit")
    result = client.request("GET", job["status_url"], timeout=timeout)
    save_remote(store, name, result)
    return summary(store.get(name, client.owner))


def wait_job(store, client, name, timeout, sleep=time.sleep, clock=time.monotonic):
    if timeout <= 0:
        raise ClientError("Timeout must be positive")
    deadline = clock() + timeout
    delay = 2.0
    last = None
    while clock() < deadline:
        try:
            result = status_job(store, client, name, timeout=max(0.1, min(30, deadline - clock())))
            if result["status"] != last:
                print(json.dumps(result), file=sys.stderr)
                last = result["status"]
            if result["status"] in TERMINAL:
                return result
        except ApiError as exc:
            if exc.code not in (0, 429) and exc.code < 500:
                raise
        remaining = deadline - clock()
        if remaining > 0:
            sleep(min(delay + random.uniform(0, 0.5), remaining))
        delay = min(10, delay * 1.5)
    raise ClientError("Polling deadline reached; job remains saved. Run wait again to resume")


def attach(store, client, name, rid):
    job = store.get(name, client.owner)
    if job["status"] not in ("unknown", "submitting"):
        raise ClientError("Attach is only for uncertain submissions")
    rid = str(UUID(rid))
    url = f"{BASE}/requests/{rid}/status"
    result = client.request("GET", url)
    if result.get("request_id") != rid:
        raise ClientError("Recovery request ID mismatch")
    result["status_url"] = url
    save_remote(store, name, result)
    return summary(store.get(name, client.owner))


def download(store, client, name, directory):
    job = store.get(name, client.owner)
    if job["status"] != "completed":
        raise ClientError("Download requires a completed saved job")
    result = json.loads(job["response_json"])
    media = []
    for field, default_ext in (("images", ".png"), ("video", ".mp4"), ("audio", ".wav"), ("audios", ".wav"),
                               ("zip", ".zip"), ("mov", ".mov"), ("jsx", ".jsx"), ("fbx", ".fbx"), ("ply", ".ply")):
        value = result.get(field, [])
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict) and isinstance(item.get("url"), str):
                if item["url"] not in [m[0] for m in media]:
                    media.append((item["url"], default_ext))
    if not media:
        raise ClientError("No supported media URLs; inspect this model's output documentation")
    target = Path(directory).resolve()
    target.mkdir(parents=True, exist_ok=True)
    files = []
    for index, (url, ext) in enumerate(media, 1):
        public_url(url)
        suffix = Path(urlsplit(url).path).suffix.lower()
        if suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".wav", ".mp3", ".zip", ".jsx", ".fbx", ".ply"):
            ext = suffix
        dest = target / f"{job['request_id']}-{index}{ext}"
        partial = dest.with_suffix(dest.suffix + ".part")
        if dest.exists():
            raise ClientError("Output file already exists; inspect it or choose another output directory")
        # Exclusive partial file prevents concurrent writers or accidental overwrite.
        with partial.open("xb") as output:
            try:
                with build_opener(NoRedirect()).open(Request(url), timeout=60) as response:
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_FILE:
                            raise ClientError("Media exceeds 256 MiB download limit")
                        output.write(chunk)
                if total == 0:
                    raise ClientError("Downloaded empty media")
            except Exception:
                output.close()
                partial.unlink(missing_ok=True)
                raise
        # Exclusive destination avoids races after the earlier existence check.
        try:
            os.link(partial, dest)
        except OSError:
            raise ClientError("Could not finalize without overwrite; complete .part file retained") from None
        partial.unlink()
        files.append(str(dest))
    return {"files": files, "estimated_usd": job["estimate_usd"]}


def upload(client, filename):
    path = Path(filename)
    if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024 or path.stat().st_size == 0:
        raise ClientError("Upload needs a nonempty local file no larger than 64 MiB")
    content_type = mimetypes.guess_type(path.name)[0]
    if content_type not in {"image/jpeg", "image/png", "image/webp", "image/gif", "audio/wav", "audio/x-wav", "video/mp4"}:
        raise ClientError("Unsupported upload content type")
    info = client.request("POST", f"{BASE}/files/generate-upload-url", {"content_type": content_type})
    url = public_url(info["upload_url"])
    public_url(info["public_url"])
    headers = info["upload_headers"]
    if not isinstance(headers, dict) or any(k.lower() in ("authorization", "cookie", "proxy-authorization", "host") for k in headers):
        raise ClientError("Unexpected storage upload headers")
    req = Request(url, data=path.read_bytes(), headers=headers, method="PUT")
    with build_opener(NoRedirect()).open(req, timeout=60) as response:
        if not 200 <= response.status < 300:
            raise ClientError("Storage upload failed")
    return {"public_url": info["public_url"], "content_type": content_type}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default="work/higgsfield")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "estimate", "submit"):
        p = sub.add_parser(command)
        p.add_argument("--profile", required=True)
        p.add_argument("--input", required=True)
        if command == "submit":
            p.add_argument("--job", required=True)
            p.add_argument("--budget-id", help="Optional batch budget; requires --budget-usd")
            p.add_argument("--budget-usd", help="Optional estimated spending cap; requires --budget-id")
    for command in ("status", "wait", "download", "attach"):
        p = sub.add_parser(command)
        p.add_argument("--job", required=True)
        if command == "wait":
            p.add_argument("--timeout", type=float, default=1200)
        if command == "download":
            p.add_argument("--output-dir", default="outputs")
        if command == "attach":
            p.add_argument("--request-id", required=True)
    sub.add_parser("upload").add_argument("--file", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in ("validate", "estimate", "submit"):
            profile, payload = load_json(args.profile), load_json(args.input)
            model = validate(profile, payload)
        if args.command == "validate":
            result = {"valid": True, "model": model, "schema_verified_at": profile["verified_at"]}
        else:
            client = Client()
            if args.command == "estimate":
                result = {"estimated_usd": str(client.estimate(model, payload)), "model": model}
            elif args.command == "upload":
                result = upload(client, args.file)
            else:
                store = Store(args.state_dir)
                try:
                    if args.command == "submit":
                        result = submit(store, client, profile, payload, args.job, args.budget_id, args.budget_usd)
                    elif args.command == "status":
                        result = status_job(store, client, args.job)
                    elif args.command == "wait":
                        result = wait_job(store, client, args.job, args.timeout)
                    elif args.command == "attach":
                        result = attach(store, client, args.job, args.request_id)
                    else:
                        result = download(store, client, args.job, args.output_dir)
                finally:
                    store.db.close()
        print(json.dumps(result))
        return 2 if result.get("status") in {"failed", "nsfw", "canceled", "rejected", "unknown", "submitting"} else 0
    except ClientError as exc:
        print(json.dumps({"error": str(exc), "correlation_id": getattr(exc, "correlation", "")}), file=sys.stderr)
        return 2
    except ModuleNotFoundError:
        print('Missing dependency; install this skill requirements.txt with the chosen Python interpreter.', file=sys.stderr)
        return 2
    except Exception as exc:
        # Avoid printing URLs, request contents or raw HTTP errors containing signed tokens.
        print(json.dumps({"error": f"Operation stopped ({type(exc).__name__}); inspect local setup and saved job state"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
