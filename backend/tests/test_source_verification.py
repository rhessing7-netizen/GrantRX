from scrapers.schema import ScholarshipExtract
from scrapers.verification import verify_extract_against_source


def test_concrete_core_facts_are_verified_from_source_text():
    html = """<h1>Future Pharmacist Scholarship</h1><p>Award: $10,000</p>
    <p>Deadline: October 15, 2026. Minimum GPA: 3.5.</p>"""
    extract = ScholarshipExtract(
        title="Future Pharmacist Scholarship", provider="Example Foundation",
        award_amount=10000, deadline="2026-10-15", min_gpa=3.5,
    )
    result = verify_extract_against_source(extract, html)
    assert result["status"] == "verified"
    assert set(result["fields"].values()) == {"verified"}


def test_hallucinated_amount_forces_review():
    html = "<h1>Future Pharmacist Scholarship</h1><p>Award amount varies.</p>"
    extract = ScholarshipExtract(
        title="Future Pharmacist Scholarship", provider="Example Foundation", award_amount=10000
    )
    result = verify_extract_against_source(extract, html)
    assert result["status"] == "needs_review"
    assert result["fields"]["award_amount"] == "unverified"


def test_unknown_values_are_not_treated_as_failed_verification():
    html = "<h1>Future Pharmacist Scholarship</h1><p>Applications open annually.</p>"
    extract = ScholarshipExtract(title="Future Pharmacist Scholarship", provider="Example Foundation")
    result = verify_extract_against_source(extract, html)
    assert result["status"] == "verified"
    assert result["fields"]["award_amount"] == "not_asserted"
    assert result["fields"]["deadline"] == "not_asserted"
