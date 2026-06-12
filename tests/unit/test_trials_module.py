"""Tests for trials module."""

import pytest
from datetime import datetime, timedelta, timezone

from vinzy_engine.trials.engine import (
    TrialEngine, TrialStatus, TrialSegment,
)


class TestTrialEngine:
    def test_create_trial(self):
        engine = TrialEngine()
        trial = engine.create_trial("lic1", "user@test.com", ["AGW", "NXS"])
        assert trial.trial_id.startswith("TRL-")
        assert trial.status == TrialStatus.ACTIVE
        assert trial.days_remaining > 0

    def test_record_usage(self):
        engine = TrialEngine()
        trial = engine.create_trial("lic1", "u@test.com", ["AGW"])
        engine.record_usage(trial.trial_id, "api_calls", 10)
        engine.record_usage(trial.trial_id, "api_calls", 5)
        assert trial.usage_data["api_calls"] == 15

    def test_record_feature_explored(self):
        engine = TrialEngine()
        trial = engine.create_trial("lic1", "u@test.com", ["AGW"])
        engine.record_feature_explored(trial.trial_id, "dashboard")
        engine.record_feature_explored(trial.trial_id, "dashboard")  # duplicate
        assert len(trial.features_explored) == 1

    def test_extend_trial(self):
        """Item 369: trial extension."""
        engine = TrialEngine()
        trial = engine.create_trial("lic1", "u@test.com", ["AGW"])
        old_expires = trial.expires_at
        engine.extend_trial(trial.trial_id, days=7)
        assert trial.expires_at > old_expires
        assert trial.status == TrialStatus.EXTENDED
        assert trial.extensions_used == 1

    def test_max_extensions(self):
        engine = TrialEngine()
        trial = engine.create_trial("lic1", "u@test.com", ["AGW"])
        engine.extend_trial(trial.trial_id)
        engine.extend_trial(trial.trial_id)
        with pytest.raises(ValueError, match="Maximum extensions"):
            engine.extend_trial(trial.trial_id)

    def test_conversion_prediction_high(self):
        """Item 373: trial usage analytics for conversion prediction."""
        engine = TrialEngine()
        trial = engine.create_trial("lic1", "u@test.com", ["AGW"])
        engine.record_usage(trial.trial_id, "api_calls", 60)
        for f in ["dashboard", "reports", "settings", "integrations", "analytics"]:
            engine.record_feature_explored(trial.trial_id, f)
        engine.save_progress(trial.trial_id, {"config": "done"})

        prediction = engine.predict_conversion(trial.trial_id)
        assert prediction.conversion_probability >= 0.5

    def test_conversion_prediction_low(self):
        engine = TrialEngine()
        trial = engine.create_trial("lic1", "u@test.com", ["AGW"])
        prediction = engine.predict_conversion(trial.trial_id)
        assert prediction.conversion_probability < 0.3

    def test_save_progress_and_convert(self):
        """Item 377: trial-to-paid transition with saved progress."""
        engine = TrialEngine()
        trial = engine.create_trial("lic1", "u@test.com", ["AGW", "NXS"])
        engine.save_progress(trial.trial_id, {"workspace": "my-workspace", "team": ["a", "b"]})
        engine.record_usage(trial.trial_id, "api_calls", 50)

        result = engine.convert_trial(trial.trial_id)
        assert result["progress_data"]["workspace"] == "my-workspace"
        assert result["usage_data"]["api_calls"] == 50
        assert trial.status == TrialStatus.CONVERTED

    def test_early_conversion_incentive(self):
        """Item 382: trial conversion incentive."""
        engine = TrialEngine()
        trial = engine.create_trial("lic1", "u@test.com", ["AGW"])
        incentive = engine.create_early_conversion_incentive(trial.trial_id, discount_pct=20)
        assert incentive.value > 0
        assert incentive.type == "early_conversion_discount"

    def test_detect_abandoned(self):
        """Item 386: abandoned trial re-engagement."""
        engine = TrialEngine(default_trial_days=30)
        # Create trial with no usage, started 10 days ago
        trial = engine.create_trial("lic1", "u@test.com", ["AGW"])
        trial.started_at = datetime.now(timezone.utc) - timedelta(days=10)
        abandoned = engine.detect_abandoned_trials(inactive_days=5)
        assert len(abandoned) >= 1

    def test_trial_referral(self):
        """Item 390: trial referral program."""
        engine = TrialEngine()
        trial = engine.create_trial("lic1", "u@test.com", ["AGW"])
        referral = engine.create_referral(trial.trial_id, "friend@test.com")
        assert referral.referral_code == trial.referral_code

    def test_complete_referral_extends_trial(self):
        engine = TrialEngine()
        trial = engine.create_trial("lic1", "u@test.com", ["AGW"])
        old_expires = trial.expires_at
        ref = engine.create_referral(trial.trial_id, "friend@test.com")
        engine.complete_referral(ref.referral_id)
        assert ref.status == "converted"
        assert trial.expires_at > old_expires

    def test_segment_trial(self):
        """Item 394: trial segment analysis."""
        engine = TrialEngine()
        trial = engine.create_trial("lic1", "u@test.com", ["AGW"])
        seg = engine.segment_trial(trial.trial_id)
        assert seg == TrialSegment.INACTIVE

        engine.record_usage(trial.trial_id, "api_calls", 50)
        for f in ["a", "b", "c", "d", "e"]:
            engine.record_feature_explored(trial.trial_id, f)
        seg = engine.segment_trial(trial.trial_id)
        assert seg == TrialSegment.HIGHLY_ENGAGED

    def test_power_user_segment(self):
        engine = TrialEngine()
        trial = engine.create_trial("lic1", "u@test.com", ["AGW"])
        engine.record_usage(trial.trial_id, "api_calls", 150)
        for f in ["a", "b", "c", "d", "e", "f", "g", "h"]:
            engine.record_feature_explored(trial.trial_id, f)
        seg = engine.segment_trial(trial.trial_id)
        assert seg == TrialSegment.POWER_USER

    def test_analyze_segments(self):
        engine = TrialEngine()
        # Create multiple trials in different segments
        t1 = engine.create_trial("lic1", "a@test.com", ["AGW"])
        engine.record_usage(t1.trial_id, "api_calls", 100)
        for f in ["a", "b", "c", "d", "e", "f", "g"]:
            engine.record_feature_explored(t1.trial_id, f)

        t2 = engine.create_trial("lic2", "b@test.com", ["AGW"])
        # No usage = inactive

        analyses = engine.analyze_segments()
        assert len(analyses) >= 1
        for a in analyses:
            assert a.count > 0
            assert len(a.recommendations) > 0

    def test_referred_trial(self):
        engine = TrialEngine()
        trial = engine.create_trial("lic1", "u@test.com", ["AGW"], referred_by="ref123")
        assert trial.referred_by == "ref123"

    def test_get_trials_by_status(self):
        engine = TrialEngine()
        engine.create_trial("lic1", "a@test.com", ["AGW"])
        t2 = engine.create_trial("lic2", "b@test.com", ["AGW"])
        engine.convert_trial(t2.trial_id)
        active = engine.get_trials(status=TrialStatus.ACTIVE)
        assert len(active) == 1
