from scripts.evaluation_graphrag import compare_rankings, ndcg_at_k, run, run_controlled


def test_ndcg_rewards_relevant_products_near_top():
    relevance = {"A": 2, "B": 1, "C": 0}

    assert ndcg_at_k(["A", "B", "C"], relevance) == 1.0
    assert ndcg_at_k(["C", "B", "A"], relevance) < 1.0


def test_controlled_graphrag_uses_production_ranking_and_improves_relevance():
    result = run_controlled()

    assert result["ranking_changed"] is True
    assert result["strict_relevance_improved"] is True
    assert result["ndcg_delta"] > 0
    assert result["graphrag"]["mrr"] >= result["pure_rag"]["mrr"]


def test_comparison_does_not_claim_improvement_for_identical_rankings():
    rows = [{"product_code": "A"}, {"product_code": "B"}]
    result = compare_rankings(rows, rows, {"A": 2, "B": 1})

    assert result["ranking_changed"] is False
    assert result["strict_relevance_improved"] is False
    assert result["ndcg_delta"] == 0


def test_default_run_is_offline_and_marks_real_proof_missing():
    result = run(with_storage=False)

    assert result["storage"] is None
    assert result["acceptance"]["controlled_relevance_improved"] is True
    assert result["acceptance"]["real_ranking_improved_proven"] is False
