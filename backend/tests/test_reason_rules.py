from app.pipeline.process import _contains_brand


def test_brand_in_reason_uses_complete_tokens():
    aliases = ["gloria", "laive", "aro"]
    assert _contains_brand("me gusta porque es gloria", aliases) is True
    assert _contains_brand("es huarochirano", aliases) is False


def test_short_brand_alias_is_not_used_as_semantic_rule():
    assert _contains_brand("compre aro", ["aro"]) is False
