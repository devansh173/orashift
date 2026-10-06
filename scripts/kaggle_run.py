"""Drive a Kaggle notebook from the command line: push, poll, fetch results.

Training runs on Kaggle's free T4 rather than locally, and doing that by hand
means uploading a notebook in a browser and remembering to download the outputs
before the session is reclaimed. This does the whole cycle in one command, so a
run is reproducible and the results land in `results/` automatically.

    python scripts/kaggle_run.py ca-bundle          # once, behind a TLS proxy
    python scripts/kaggle_run.py push --wait        # push, poll, fetch
    python scripts/kaggle_run.py status
    python scripts/kaggle_run.py fetch

Authentication is the Kaggle CLI's own: run `kaggle auth login` once. This
script never reads or stores credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTEBOOKS = REPO_ROOT / "notebooks"
RESULTS = REPO_ROOT / "results" / "kaggle"
"""Raw Kaggle outputs. Curated artefacts are promoted up to results/ and committed."""

DEFAULT_CA_BUNDLE = Path.home() / ".config" / "orashift" / "ca-bundle.pem"

ADAPTER_DATASET_SLUG = "orashift-qlora-adapter"
"""The trained adapter, uploaded as a Kaggle Dataset so the prediction notebook
can mount it. It is 125 MB, so it is not committed to git."""

KERNELS = {
    "train": {
        "slug": "orashift-qlora-train",
        "title": "OraShift QLoRA train",
        "notebook": "train_qlora.ipynb",
        "datasets": [],
    },
    "predict": {
        # The slug must match what Kaggle derives from the title, or the push
        # lands at a different id than status and fetch look for.
        "slug": "orashift-predictions",
        "title": "OraShift predictions",
        "notebook": "predict.ipynb",
        "datasets": [ADAPTER_DATASET_SLUG],
    },
}

# Kaggle reports these; anything else means the run is still going.
TERMINAL_STATUSES = {"complete", "error", "cancelled", "cancelAcknowledged"}


def build_ca_bundle(path: Path = DEFAULT_CA_BUNDLE) -> Path:
    """Combine certifi's roots with any extra roots macOS already trusts.

    A TLS-inspecting proxy (Netskope, Zscaler and friends) re-signs every HTTPS
    connection with a corporate root. macOS trusts it, so `curl` works, but
    Python's `requests` uses certifi's bundle, which does not contain it. The
    result is `CERTIFICATE_VERIFY_FAILED: self-signed certificate in chain`.

    Combining the two is the correct fix. Disabling verification is not.
    """
    import certifi

    if sys.platform != "darwin":
        raise SystemExit("ca-bundle is macOS-only; on Linux add the root to your CA store")

    extra = subprocess.run(
        ["security", "find-certificate", "-a", "-p", "/Library/Keychains/System.keychain"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        Path(certifi.where()).read_text(encoding="utf-8") + "\n" + extra, encoding="utf-8"
    )
    count = path.read_text(encoding="utf-8").count("BEGIN CERTIFICATE")
    print(f"wrote {path} ({count} certificates)")
    return path


def kaggle_env() -> dict[str, str]:
    """Environment for the Kaggle CLI, pointed at a working CA bundle."""
    env = dict(os.environ)
    bundle = env.get("ORASHIFT_CA_BUNDLE") or (
        str(DEFAULT_CA_BUNDLE) if DEFAULT_CA_BUNDLE.exists() else None
    )
    if bundle:
        env.setdefault("SSL_CERT_FILE", bundle)
        env.setdefault("REQUESTS_CA_BUNDLE", bundle)
    return env


def run_kaggle(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["kaggle", *args], capture_output=True, text=True, env=kaggle_env(), check=False
    )
    if check and result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        if "CERTIFICATE_VERIFY_FAILED" in output:
            raise SystemExit(
                "TLS verification failed, which usually means an inspecting proxy.\n"
                "Run: python scripts/kaggle_run.py ca-bundle"
            )
        raise SystemExit(f"kaggle {' '.join(args)} failed:\n{output}")
    return result


def whoami() -> str:
    """The account slug, taken from the CLI rather than configured by hand."""
    result = run_kaggle(["config", "view"], check=False)
    for line in (result.stdout + result.stderr).splitlines():
        if "username" in line.lower():
            return line.split()[-1].strip()
    listing = run_kaggle(["kernels", "list", "--mine"]).stdout.splitlines()
    for line in listing[2:]:
        if "/" in line:
            return line.split("/")[0].strip()
    raise SystemExit("could not determine the Kaggle username; run `kaggle auth login`")


def stage(kernel: dict, username: str, private: bool) -> Path:
    """A temporary folder holding the notebook and its kernel-metadata.json."""
    notebook = NOTEBOOKS / kernel["notebook"]
    if not notebook.exists():
        raise SystemExit(f"{notebook} does not exist yet")

    staging = Path(tempfile.mkdtemp(prefix="orashift-kaggle-"))
    shutil.copy2(notebook, staging / notebook.name)
    metadata = {
        "id": f"{username}/{kernel['slug']}",
        "title": kernel["title"],
        "code_file": notebook.name,
        "language": "python",
        "kernel_type": "notebook",
        "is_private": private,
        "enable_gpu": True,
        "enable_internet": True,  # needed to download the model and clone the repo
        "dataset_sources": [f"{username}/{d}" for d in kernel.get("datasets", [])],
        "competition_sources": [],
        "kernel_sources": [],
    }
    (staging / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return staging


def find_adapter() -> Path:
    """Locate the adapter fetched from the training run."""
    candidates = sorted(RESULTS.rglob("orashift-qlora-adapter"))
    for path in candidates:
        if (path / "adapter_model.safetensors").exists():
            return path
    raise SystemExit(
        "no adapter found under results/kaggle/. Run the training notebook first:\n"
        "  python scripts/kaggle_run.py push --kernel train --wait"
    )


def upload_adapter(username: str) -> str:
    """Publish the adapter as a Kaggle Dataset, creating or versioning it."""
    adapter = find_adapter()
    slug = f"{username}/{ADAPTER_DATASET_SLUG}"

    staging = Path(tempfile.mkdtemp(prefix="orashift-adapter-"))
    try:
        for item in adapter.iterdir():
            if item.is_file():
                shutil.copy2(item, staging / item.name)
        (staging / "dataset-metadata.json").write_text(
            json.dumps(
                {
                    "title": "OraShift QLoRA adapter",
                    "id": slug,
                    "licenses": [{"name": "CC0-1.0"}],
                },
                indent=2,
            )
            + "\n"
        )
        size_mb = sum(f.stat().st_size for f in staging.iterdir()) / 1024**2
        print(f"uploading {adapter.name} ({size_mb:.0f} MB) as {slug}")

        existing = run_kaggle(
            ["datasets", "list", "--mine", "-s", ADAPTER_DATASET_SLUG], check=False
        ).stdout
        if ADAPTER_DATASET_SLUG in existing:
            result = run_kaggle(
                ["datasets", "version", "-p", str(staging), "-m", "retrained adapter"]
            )
        else:
            result = run_kaggle(["datasets", "create", "-p", str(staging)])
        print(result.stdout.strip())
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return slug


def require_datasets_ready(username: str, slugs: list[str]) -> None:
    """Fail before pushing if a required dataset is missing or still processing.

    Kaggle accepts a kernel that references a dataset which is not ready yet,
    mounts nothing, and the run fails a minute later. Checking here turns that
    into an immediate, readable error instead of a wasted queue cycle.
    """
    for slug in slugs:
        ref = f"{username}/{slug}"
        listing = run_kaggle(["datasets", "files", ref], check=False)
        output = listing.stdout + listing.stderr
        if listing.returncode != 0 or "name" not in output:
            raise SystemExit(
                f"dataset {ref} is not available yet.\n"
                f"Upload it with: python scripts/kaggle_run.py upload-adapter\n"
                f"If it was just uploaded, give Kaggle a minute to process it.\n"
                f"{output.strip()[:300]}"
            )
        print(f"dataset ready: {ref}")


def current_status(ref: str) -> str:
    output = run_kaggle(["kernels", "status", ref], check=False).stdout.strip()
    for status in (*TERMINAL_STATUSES, "running", "queued"):
        if status.lower() in output.lower():
            return status
    return output or "unknown"


def wait_for(ref: str, poll_seconds: int, timeout_minutes: int) -> str:
    deadline = time.time() + timeout_minutes * 60
    last = None
    while time.time() < deadline:
        status = current_status(ref)
        if status != last:
            print(f"[{time.strftime('%H:%M:%S')}] {status}")
            last = status
        if status in TERMINAL_STATUSES:
            return status
        time.sleep(poll_seconds)
    return "timed out"


def fetch(ref: str, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    run_kaggle(["kernels", "output", ref, "-p", str(destination), "-o"])
    files = sorted(p for p in destination.rglob("*") if p.is_file())
    print(f"\n{len(files)} file(s) in {destination}:")
    for path in files[:30]:
        print(f"  {path.relative_to(destination)}  ({path.stat().st_size / 1024:.0f} KB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ca-bundle", help="Build a CA bundle that includes proxy roots")
    sub.add_parser("upload-adapter", help="Publish the trained adapter as a Kaggle Dataset")

    for name in ("push", "status", "fetch"):
        p = sub.add_parser(name)
        p.add_argument("--kernel", choices=sorted(KERNELS), default="train")
        if name == "push":
            p.add_argument("--wait", action="store_true", help="Poll until the run finishes")
            p.add_argument("--public", action="store_true", help="Publish the notebook")
            p.add_argument("--poll-seconds", type=int, default=60)
            p.add_argument("--timeout-minutes", type=int, default=120)
            p.add_argument(
                "--kernel-timeout-minutes",
                type=int,
                default=60,
                help="Hard cap Kaggle applies to the run itself. A hung install "
                "once burned 3.6 hours of GPU quota in silence; this stops that.",
            )

    args = parser.parse_args()

    if args.command == "ca-bundle":
        build_ca_bundle()
        return 0

    if args.command == "upload-adapter":
        print(upload_adapter(whoami()))
        return 0

    kernel = KERNELS[args.kernel]
    username = whoami()
    ref = f"{username}/{kernel['slug']}"

    if args.command == "status":
        print(f"{ref}: {current_status(ref)}")
        return 0

    if args.command == "fetch":
        fetch(ref, RESULTS / args.kernel)
        return 0

    require_datasets_ready(username, kernel.get("datasets", []))
    staging = stage(kernel, username, private=not args.public)
    try:
        seconds = args.kernel_timeout_minutes * 60
        print(
            f"pushing {kernel['notebook']} to {ref} "
            f"(gpu=on, internet=on, hard cap {args.kernel_timeout_minutes}m)"
        )
        print(
            run_kaggle(["kernels", "push", "-p", str(staging), "-t", str(seconds)]).stdout.strip()
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    print(f"\nhttps://www.kaggle.com/code/{ref}")
    if not args.wait:
        print("run with --wait to poll, or: python scripts/kaggle_run.py status")
        return 0

    status = wait_for(ref, args.poll_seconds, args.timeout_minutes)
    print(f"\nfinal status: {status}")
    if status == "complete":
        fetch(ref, RESULTS / args.kernel)
        return 0
    print("fetching whatever output exists, for the logs")
    fetch(ref, RESULTS / args.kernel)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
