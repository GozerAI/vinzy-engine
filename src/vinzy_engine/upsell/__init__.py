"""Upsell module -- recommendations, upgrade prompts, loyalty programs."""

from vinzy_engine.upsell.recommendations import CrossProductRecommendationEngine
from vinzy_engine.upsell.loyalty import LoyaltyEngine

__all__ = [
    "CrossProductRecommendationEngine",
    "LoyaltyEngine",
]
