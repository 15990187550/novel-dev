from novel_dev.schemas.quality_issues import QualityIssueCode, QualityIssueSeverity

def test_issue_codes_are_strings():
    assert QualityIssueCode.AI_FLAVOR_HIGH == "AI_FLAVOR_HIGH"
    assert isinstance(QualityIssueCode.AI_FLAVOR_HIGH, str)

def test_issue_code_groups_exist():
    structure = {QualityIssueCode.BEAT_BOUNDARY_VIOLATION, QualityIssueCode.EVENT_ORDER_DRIFT}
    content = {QualityIssueCode.AI_FLAVOR_HIGH, QualityIssueCode.WORD_COUNT_DRIFT}
    flow = {QualityIssueCode.REVIEW_TIMEOUT, QualityIssueCode.EXPORT_FAILED}
    assert structure.isdisjoint(content)
    assert content.isdisjoint(flow)
    assert structure.isdisjoint(flow)

def test_severity_enum():
    assert QualityIssueSeverity.BLOCK == "block"
    assert QualityIssueSeverity.WARN == "warn"
    assert QualityIssueSeverity.MANUAL_REVIEW == "manual_review"