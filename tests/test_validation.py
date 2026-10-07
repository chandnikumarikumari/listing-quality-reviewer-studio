import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from app import validate, analyze

OK = {"title": "Cotton T-Shirt", "description": "Soft cotton t-shirt in blue, machine washable, regular fit.",
      "category": "Clothing", "price": "9.50", "seller": "s", "attributes": {"size": "M", "condition": "new"}}

def test_valid_listing_has_no_errors(): assert validate(OK, set()) == []
def test_bad_price(): assert any("Price" in e for e in validate({**OK, "price": "abc"}, set()))
def test_unsupported_category(): assert any("category" in e for e in validate({**OK, "category": "Jewelry"}, set()))
def test_missing_field(): assert any("title" in e for e in validate({**OK, "title": ""}, set()))
def test_duplicate_exact_and_fuzzy():
    seen = set(); validate(OK, seen)
    assert any("Duplicate" in e for e in validate(OK, seen))
    assert any("Duplicate" in e for e in validate({**OK, "title": "Cotton T-Shirts"}, seen))
def test_counterfeit_is_critical_and_cited():
    f = analyze({**OK, "title": "Rolex replica watch"})
    assert f and f[0]["severity"] == "critical" and f[0]["policy"].startswith("P1")
def test_missing_attribute_flagged():
    assert any(x["kind"] == "incomplete" for x in analyze({**OK, "attributes": {"size": "M"}}))

def test_rupee_price_accepted(): assert validate({**OK, "price": "\u20b91,299"}, set()) == []
def test_contact_details_cited_to_p8():
    f = analyze({**OK, "description": "Great fit. Call me on 9876543210 for a discount please."})
    assert any(x["policy"].startswith("P8") and x["severity"] == "high" for x in f)
def test_price_claim_flagged():
    assert any(x["kind"] == "misleading" for x in analyze({**OK, "description": "Cheapest price in town, soft cotton, machine washable."}))
