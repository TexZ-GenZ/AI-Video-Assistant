"""End-to-end smoke test: run a full job through the pipeline and verify.

Usage:
    python scripts/e2e_smoke.py --source <youtube-url-or-file-id> [options]

Options:
    --api-url URL   ingestion API base (default http://localhost:8001)
    --sum-url URL   summarization API base (default http://localhost:8002)
    --ask "Q"       ask this question after the job completes (repeatable)
    --timeout MIN   max minutes to wait for completion (default 30)
    --file PATH     upload a local file first, then process it by file_id

Works against the docker-compose local stack AND the EKS ALB (pass both URLs).
"""

import argparse
import json
import sys
import time
import urllib.request


# Windows consoles often can't encode emoji — keep output ASCII.
def _fix_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


_fix_stdout()


def http(method: str, url: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def poll_until_done(sum_url: str, job_id: str, timeout_min: int):
    deadline = time.time() + timeout_min * 60
    last = ""
    while time.time() < deadline:
        status = http("GET", f"{sum_url}/api/process/{job_id}/status")
        if status["progress"] and status["progress"] != last:
            print(f"  [{time.strftime('%H:%M:%S')}] {status['progress']}")
            last = status["progress"]
        if status["status"] in ("done", "error"):
            return status
        time.sleep(5)
    raise TimeoutError(f"job {job_id} did not finish within {timeout_min} min")


def main():
    parser = argparse.ArgumentParser(description="VideoSense E2E smoke test")
    parser.add_argument("--source", help="YouTube URL or file_id")
    parser.add_argument("--api-url", default="http://localhost:8001")
    parser.add_argument("--sum-url", default="http://localhost:8002")
    parser.add_argument("--ask", action="append", default=[], help="question to ask (repeatable)")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--file", help="upload this file, then process it")
    parser.add_argument("--job", help="skip processing; inspect an existing job id")
    args = parser.parse_args()

    if args.job:
        job_id = args.job
        print(f"Inspecting existing job: {job_id}")
    else:
        source = args.source
        if args.file:
            import mimetypes
            import urllib.request as u

            boundary = "----videosense-e2e"
            with open(args.file, "rb") as f:
                content = f.read()
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{args.file.split("/")[-1]}"\r\n'
                f"Content-Type: {mimetypes.guess_type(args.file)[0] or 'application/octet-stream'}\r\n\r\n"
            ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
            req = u.Request(
                f"{args.api_url}/api/upload", data=body, method="POST",
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            with u.urlopen(req, timeout=120) as resp:
                source = json.loads(resp.read().decode())["file_id"]
            print(f"Uploaded {args.file} → file_id {source}")

        if not source:
            parser.error("provide --source, --file or --job")

        print(f"Processing: {source}")
        job = http("POST", f"{args.api_url}/api/process",
                   {"source": source, "language": "english"})
        job_id = job["job_id"]
        print(f"Job: {job_id}")

        final = poll_until_done(args.sum_url, job_id, args.timeout)
        if final["status"] == "error":
            print(f"[FAIL] Job failed: {final.get('error')}")
            sys.exit(1)

        print("[OK] Job done")
    results = http("GET", f"{args.sum_url}/api/process/{job_id}/results")
    print(f"\nTitle: {results['title']}")
    print(f"\nSummary:\n{results['summary'][:2000]}")
    print(f"\nAction items:\n{results['actionables'][:1000]}")
    print(f"\nKey information:\n{results['information'][:1000]}")
    print(f"\nQuestions:\n{results['questions'][:1000]}")

    for q in args.ask:
        answer = http("POST", f"{args.sum_url}/api/process/{job_id}/ask", {"question": q})
        print(f"\nQ: {q}\nA: {answer['answer']}")

    print(f"\nJob id for manual checks: {job_id}")


if __name__ == "__main__":
    main()
