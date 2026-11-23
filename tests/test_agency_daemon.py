import pytest
from autonomous_agency_daemon import LeadClassifier, NotificationManager, AgencyDaemon

def test_lead_classifier_heuristics():
    # Test interested inquiry
    res1 = LeadClassifier.analyze_email(
        "drsmith@austindental.com",
        "Website quote",
        "Hi Karan, I saw your dental website demo. How much does it cost and how fast can you deliver?"
    )
    assert res1["intent"] in ["INTERESTED", "QUESTION"]
    assert "draft_reply" in res1
    assert len(res1["draft_reply"]) > 10

    # Test meeting request
    res2 = LeadClassifier.analyze_email(
        "brett@denverhvac.com",
        "Let's schedule a call",
        "Can we set up a quick 10-minute call tomorrow afternoon to talk about our site?"
    )
    assert res2["intent"] in ["MEETING_REQUEST", "INTERESTED"]
    assert "https://wa.me/917204059791" in res2["draft_reply"]

    # Test unsubscribe
    res3 = LeadClassifier.analyze_email(
        "spam@test.com",
        "Unsubscribe",
        "Please remove me from your email list, stop sending emails."
    )
    assert res3["intent"] in ["NOT_INTERESTED", "UNSUBSCRIBE"]


def test_notification_manager():
    alert = NotificationManager.create_whatsapp_alert(
        "lead@example.com",
        "Lone Star Roofing",
        "INTERESTED",
        "We want to book a new site"
    )
    assert alert["phone"] == "+917204059791"
    assert "HOT AGENCY LEAD ALERT" in alert["message"]
    assert "https://wa.me/917204059791" in alert["wa_direct_link"]

    ticket = NotificationManager.schedule_meeting(
        "lead@example.com",
        "Lone Star Roofing",
        "Wants full PPF/Roofing website"
    )
    assert ticket["id"].startswith("MTG-")
    assert ticket["client_email"] == "lead@example.com"
    assert ticket["status"] == "AWAITING_TIME_CONFIRMATION"


def test_daemon_dry_run_safety():
    daemon = AgencyDaemon(send_live=False)
    assert daemon.send_live is False
    # Verifies send_reply_email does not raise or throw in dry-run
    daemon.send_reply_email("test@example.com", "Hello", "Test body")
