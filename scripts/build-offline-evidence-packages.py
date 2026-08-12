#!/usr/bin/env python3
"""Build three raw-data offline evidence packages from public NCBI sources.

The generated files are runtime data, not committed fixtures. They retain the
original PubMed NBIB export and Europe PMC full-text XML; no screening or
evidence extraction is performed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


CASES = (
    {
        "package_id": "hf-remote-follow-up-v2",
        "title": "心衰出院后远程随访：原始离线证据包",
        "source": "offline_pubmed_pmc_export",
        "query": "(heart failure[Title/Abstract]) AND (telephone[Title/Abstract] OR telehealth[Title/Abstract] OR telemedicine[Title/Abstract] OR text messaging[Title/Abstract]) AND randomized controlled trial[Publication Type]",
        "papers": (
            ("40055862", "PMC12132665"),
            ("38955396", "PMC11217996"),
            ("30170422", "PMC6392598"),
            ("34898447", "PMC8713094"),
            ("31432915", "PMC6703101"),
            ("30418101", "PMC6784489"),
            ("30169539", "PMC6118377"),
            ("27488754", "PMC5336747"),
            ("30478888", "PMC6352960"),
        ),
    },
    {
        "package_id": "hf-home-rehabilitation-v2",
        "title": "心衰居家与远程心脏康复：原始离线证据包",
        "source": "offline_pubmed_pmc_export",
        "query": "(heart failure[Title/Abstract]) AND (cardiac rehabilitation[Title/Abstract] OR home rehabilitation[Title/Abstract] OR telerehabilitation[Title/Abstract]) AND randomized controlled trial[Publication Type]",
        "papers": (
            ("40736732", "PMC12311714"),
            ("40159769", "PMC11955713"),
            ("37221704", "PMC10375147"),
            ("38787817", "PMC11125511"),
            ("35534907", "PMC9288767"),
            ("35313751", "PMC9082976"),
            ("30304644", "PMC6376602"),
            ("29369178", "PMC5794362"),
            ("33031130", "PMC7808349"),
        ),
    },
    {
        "package_id": "pharmacist-medication-reconciliation-v2",
        "title": "药师主导用药核对与出院过渡：原始离线证据包",
        "source": "offline_pubmed_pmc_export",
        "query": "(medication reconciliation[Title/Abstract]) AND (pharmacist[Title/Abstract]) AND (hospital discharge[Title/Abstract] OR transition[Title/Abstract] OR readmission[Title/Abstract])",
        "papers": (
            ("38602274", "PMC11007753"),
            ("40279301", "PMC12027055"),
            ("35241436", "PMC8896047"),
            ("35831783", "PMC9281036"),
            ("37312222", "PMC10265814"),
            ("37056529", "PMC10092899"),
            ("34529065", "PMC8446815"),
            ("31539073", "PMC6755531"),
            ("31592290", "PMC6763293"),
        ),
    },
)


def fetch(url: str, attempts: int = 4) -> bytes:
    """Retrieve public source material while tolerating transient API resets."""
    request = urllib.request.Request(url, headers={"User-Agent": "ClinResearch-offline-package-builder/0.2"})
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except OSError as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    # Europe PMC occasionally closes urllib HTTP connections while its curl
    # endpoint is healthy. Use curl as a portable fallback for package builds.
    curl_result = subprocess.run(
        [
            "curl", "--http1.1", "--retry", "5", "--retry-all-errors",
            "--retry-delay", "2", "--connect-timeout", "15", "--max-time", "90",
            "--fail", "--silent", "--show-error", "--location", url,
        ],
        check=False,
        capture_output=True,
    )
    if curl_result.returncode == 0:
        return curl_result.stdout
    raise RuntimeError(f"Unable to retrieve source after {attempts} attempts: {url}") from last_error


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_case(root: Path, case: dict[str, object]) -> None:
    package = root / str(case["package_id"])
    fulltext_dir = package / "fulltext"
    fulltext_dir.mkdir(parents=True, exist_ok=True)
    pmids = [paper[0] for paper in case["papers"]]
    nbib_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urllib.parse.urlencode({
        "db": "pubmed", "id": ",".join(pmids), "rettype": "medline", "retmode": "text",
    })
    citation_path = package / "citations.nbib"
    citation_path.write_bytes(fetch(nbib_url))

    documents = []
    for index, (pmid, pmcid) in enumerate(case["papers"], start=1):
        xml_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        xml_path = fulltext_dir / f"paper-{index:02d}-{pmid}.xml"
        if xml_path.exists():
            content = xml_path.read_bytes()
        else:
            content = fetch(xml_url)
            xml_path.write_bytes(content)
        if len(content) < 10_000 or b"<article" not in content[:2_000]:
            xml_path.unlink(missing_ok=True)
            raise RuntimeError(f"Europe PMC did not return usable original XML for {pmcid}.")
        documents.append({
            "path": xml_path.relative_to(package).as_posix(),
            "content_type": "application/xml",
            "sha256": digest(xml_path),
            "citation_match": {"external_id": pmid},
            "source_url": xml_url,
        })
        # Europe PMC may reset rapid consecutive XML requests. Limit each call.
        time.sleep(1.0)

    manifest = {
        "schema_version": 1,
        "package_id": case["package_id"],
        "title": case["title"],
        "source": case["source"],
        "provenance": {
            "databases": [{
                "name": "PubMed and PubMed Central",
                "searched_at": datetime.now(UTC).date().isoformat(),
                "query": case["query"],
                "exported_count": len(pmids),
                "retrieval_method": "NCBI E-utilities NBIB export plus original Europe PMC fullTextXML",
            }],
        },
        "citation_file": {
            "path": "citations.nbib",
            "format": "nbib",
            "sha256": digest(citation_path),
        },
        "documents": documents,
    }
    (package / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download public raw source material for three offline Agent cases.")
    parser.add_argument("--output-dir", default="data/offline-evidence-packages")
    parser.add_argument(
        "--package-id",
        choices=[str(case["package_id"]) for case in CASES],
        help="Build one package only; useful for resuming an interrupted download.",
    )
    args = parser.parse_args()
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    selected_cases = [case for case in CASES if not args.package_id or case["package_id"] == args.package_id]
    for case in selected_cases:
        build_case(root, case)
        print(f"Built {case['package_id']}")


if __name__ == "__main__":
    main()
