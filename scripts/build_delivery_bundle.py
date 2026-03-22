from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spendinggovua_api.batch_export import DEFAULT_ARCHIVE_NAME, export_form2_html_archive

PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"
DOCKERFILE = ROOT / "Dockerfile"
GITHUB_ABOUT = ROOT / "docs" / "github-about.md"
DIST_DIR = ROOT / "dist"
OUTPUT_DIR = ROOT / "output"
RELEASE_DIR = ROOT / "release"


def read_version() -> str:
    with PYPROJECT.open("rb") as fh:
        payload = tomllib.load(fh)
    return str(payload["project"]["version"])


def run_uv_build() -> None:
    subprocess.run(["uv", "build"], cwd=ROOT, check=True)


def git_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


async def ensure_reports_archive() -> Path:
    archive_path = OUTPUT_DIR / DEFAULT_ARCHIVE_NAME
    if archive_path.exists():
        return archive_path
    return await export_form2_html_archive(output_dir=OUTPUT_DIR)


def build_bundle(version: str, reports_archive: Path) -> Path:
    RELEASE_DIR.mkdir(exist_ok=True)
    bundle_path = RELEASE_DIR / f"spendinggovua_api-delivery-{version}.zip"
    wheel_path = DIST_DIR / f"spendinggovua_api-{version}-py3-none-any.whl"
    sdist_path = DIST_DIR / f"spendinggovua_api-{version}.tar.gz"

    files = [
        ("README.md", README),
        ("Dockerfile", DOCKERFILE),
        ("docs/github-about.md", GITHUB_ABOUT),
        (f"dist/{wheel_path.name}", wheel_path),
        (f"dist/{sdist_path.name}", sdist_path),
        (f"output/{reports_archive.name}", reports_archive),
    ]

    manifest = {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "version": version,
        "git_commit": git_commit(),
        "files": [
            {
                "archive_path": archive_name,
                "source_path": str(source_path),
                "size": source_path.stat().st_size,
            }
            for archive_name, source_path in files
        ],
    }

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for archive_name, source_path in files:
            archive.write(source_path, archive_name)

    return bundle_path


async def main() -> None:
    version = read_version()
    run_uv_build()
    reports_archive = await ensure_reports_archive()
    bundle_path = build_bundle(version, reports_archive)

    print(f"Version: {version}")
    print(f"Reports archive: {reports_archive}")
    print(f"Delivery bundle: {bundle_path}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}: {exc.cmd}", file=sys.stderr)
        raise
