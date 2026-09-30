from scrapers.runner import _to_db_dict
from scrapers.schema import ScholarshipExtract


def test_unknown_award_and_deadline_remain_null():
    row = _to_db_dict(ScholarshipExtract(title="Healthcare Scholarship", provider="Foundation", portal_url="https://example.org/scholarship"))
    assert row["award_amount"] is None
    assert row["deadline"] is None
    # C3: lifecycle fields are owned by app.services.lifecycle, not the field
    # mapper, so a refresh can never overwrite archival state.
    assert "is_archived" not in row
    assert "lifecycle_status" not in row

    # An unknown (NULL) deadline is not an expired one: a new record publishes.
    from app.models.models import Scholarship
    from app.services import lifecycle

    s = Scholarship(**row)
    lifecycle.initialize_new(s)
    assert s.lifecycle_status == "published"
    assert s.is_archived is False
    assert s.deadline is None


def test_unknown_facts_are_publishable_not_invented():
    extract = ScholarshipExtract(title="Rolling Award")
    assert extract.is_critical_complete() is True
