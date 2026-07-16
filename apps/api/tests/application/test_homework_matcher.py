from review_assistant.application.homework.matcher import combine_scores


def test_hybrid_match_rewards_keyword_and_semantic_agreement() -> None:
    score, method = combine_scores(keyword=0.8, semantic=0.9)
    assert score == 0.845
    assert method == "hybrid"


def test_matcher_can_fall_back_to_one_signal() -> None:
    assert combine_scores(keyword=0.7, semantic=None) == (0.7, "keyword")
    assert combine_scores(keyword=0.0, semantic=0.8) == (0.8, "vector")
