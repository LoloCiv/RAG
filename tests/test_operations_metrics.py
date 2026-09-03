"""Las metricas del piloto se calculan desde la auditoria, sin otro servicio."""

from app.operations.metrics import summarize_work_items


def test_summary_measures_review_and_resolution_times_without_sending():
    records = [
        {
            "created_at": "2026-09-03T10:00:00+00:00",
            "status": "sent",
            "audit": [
                {"at": "2026-09-03T10:00:00+00:00", "event": "created"},
                {"at": "2026-09-03T10:01:00+00:00", "event": "draft_generated"},
                {"at": "2026-09-03T10:02:00+00:00", "event": "approved"},
                {"at": "2026-09-03T10:03:00+00:00", "event": "sent"},
            ],
        },
        {
            "created_at": "2026-09-03T10:00:00+00:00",
            "status": "rejected",
            "audit": [
                {"at": "2026-09-03T10:00:00+00:00", "event": "created"},
                {"at": "2026-09-03T10:02:00+00:00", "event": "draft_generated"},
                {"at": "2026-09-03T10:02:30+00:00", "event": "draft_edited"},
                {"at": "2026-09-03T10:04:00+00:00", "event": "rejected"},
            ],
        },
    ]

    summary = summarize_work_items(records)

    assert summary["total"] == 2
    assert summary["by_status"] == {"rejected": 1, "sent": 1}
    assert summary["average_seconds_to_draft"] == 90
    assert summary["average_seconds_to_resolution"] == 210
    assert summary["approval_without_edit_rate"] == 1.0
    assert summary["external_actions_without_approval"] == 0


def test_summary_detects_invalid_external_action_in_audit():
    summary = summarize_work_items([
        {
            "created_at": "2026-09-03T10:00:00+00:00",
            "status": "sent",
            "audit": [{"at": "2026-09-03T10:01:00+00:00", "event": "sent"}],
        }
    ])

    assert summary["external_actions_without_approval"] == 1
