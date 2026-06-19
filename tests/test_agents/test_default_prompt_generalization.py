from novel_dev.agents._default_prompts import DEFAULT_PROMPTS


def test_default_prompts_do_not_embed_cultivation_specific_examples():
    combined = "\n".join(DEFAULT_PROMPTS.values())

    forbidden_fragments = [
        "「灵器」空间",
        "凡人→修士",
        "师兄→师弟",
        "凡人突然筑基",
        "碎石硌掌心",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in combined
