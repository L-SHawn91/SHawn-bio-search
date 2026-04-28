import csv
from pathlib import Path

from shawn_bio_search import institutional_access as ia


def test_select_rows_defaults_to_ready_status():
    rows = [
        {"idx": "1", "doi": "10.1/a", "new_status": "institutional_access_ready"},
        {"idx": "2", "doi": "10.1/b", "new_status": "manual_review_institutional_access_available"},
        {"idx": "3", "doi": "", "new_status": "institutional_access_ready"},
    ]

    selected = ia.select_rows(rows, statuses=ia.DEFAULT_STATUSES, start=0, limit=None)

    assert [r["idx"] for r in selected] == ["1"]


def test_open_queue_rows_dry_run_does_not_spawn_browser():
    rows = [
        {
            "idx": "9",
            "doi": "10.1016/j.dnarep.2026.103935",
            "title": "Altered lipid profile",
            "new_status": "institutional_access_ready",
            "institutional_access": "available",
        }
    ]

    audit = ia.open_queue_rows(
        rows,
        browser_command="xdg-open",
        access_route="current_network_institutional_access",
        network_label="",
        auth_provider_label="",
        url_template="",
        preserve_queue_route=False,
        batch_size=5,
        sleep_s=0,
        dry_run=True,
    )

    assert audit[0]["action"] == "dry_run"
    assert audit[0]["source_url"] == "https://doi.org/10.1016/j.dnarep.2026.103935"
    assert audit[0]["url"] == "https://doi.org/10.1016/j.dnarep.2026.103935"
    assert audit[0]["access_route"] == "current_network_institutional_access"


def test_environment_can_use_current_network_label():
    env = ia.environment_status(
        access="auto",
        browser_command="true",
        network_label="Example University Network",
    )

    assert env.institutional_access == "available"
    assert env.access_route == "institutional_access_example_university_network"


def test_auth_provider_overrides_physical_network_for_route():
    env = ia.environment_status(
        access="auto",
        browser_command="true",
        network_label="Konkuk campus network",
        auth_provider_label="Yonsei University Library",
    )

    assert env.institutional_access == "available"
    assert env.network_label == "Konkuk campus network"
    assert env.auth_provider_label == "Yonsei University Library"
    assert env.access_route == "institutional_access_yonsei_university_library"


def test_access_url_template_wraps_doi_url():
    url = ia.access_url(
        "10.1002/pros.21126",
        "https://library.example/login?url={url}&doi={doi}",
    )

    assert "https%3A%2F%2Fdoi.org%2F10.1002%2Fpros.21126" in url
    assert "10.1002%2Fpros.21126" in url


def test_main_cli_writes_audit_for_other_environments(tmp_path: Path):
    queue = tmp_path / "queue.tsv"
    with queue.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["idx", "doi", "title", "new_status", "institutional_access"],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerow(
            {
                "idx": "1",
                "doi": "10.1002/pros.21126",
                "title": "Inhibition of DHCR24/Seladin-1",
                "new_status": "institutional_access_ready",
                "institutional_access": "available",
            }
        )

    rc = ia.main_cli(
        [
            "--queue", str(queue),
            "--out-dir", str(tmp_path),
            "--institutional-access", "available",
            "--network-label", "Example Library Network",
            "--auth-provider-label", "Example Auth Library",
            "--no-detect-network",
            "--browser-command", "true",
            "--dry-run",
        ]
    )

    assert rc == 0
    audits = list(tmp_path.glob("institutional_browser_open_audit_*.tsv"))
    assert len(audits) == 1
    text = audits[0].read_text(encoding="utf-8")
    assert "10.1002/pros.21126" in text
    assert "institutional_access_example_auth_library" in text
    assert "Example Library Network" in text
    assert "Example Auth Library" in text
