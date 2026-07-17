from __future__ import annotations

from app.youtube_growth.schemas import GrowthScoreBreakdown, GrowthScoreComponents


GROWTH_SCORE_WEIGHTS: dict[str, float] = {
    "topic_demand": 0.25,
    "competition_gap": 0.20,
    "hook_strength": 0.20,
    "title_thumbnail_packaging": 0.15,
    "channel_fit": 0.10,
    "timing_relevance": 0.10,
}


def calculate_growth_opportunity_score(topic: str, components: GrowthScoreComponents) -> GrowthScoreBreakdown:
    component_values = components.model_dump()
    weighted = sum(
        int(component_values[name]["score"]) * weight
        for name, weight in GROWTH_SCORE_WEIGHTS.items()
    )
    total = max(0, min(100, round(weighted)))
    explanation = "; ".join(
        f"{int(weight * 100)}% {name.replace('_', ' ')}: {component_values[name]['explanation']}"
        for name, weight in GROWTH_SCORE_WEIGHTS.items()
    )
    return GrowthScoreBreakdown(
        topic=topic,
        components=components,
        total_score=total,
        explanation=explanation,
    )
