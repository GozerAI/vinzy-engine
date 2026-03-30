"""Tests for compliance modules: fraud detection, investigation, reporting,
schema migration, key evolution, revenue recognition, and recovery."""

import time
import pytest

from vinzy_engine.compliance.fraud_detection import (
    FraudDetector,
    FraudSeverity,
    FraudType,
    FraudSignal,
    UsageEvent,
)
from vinzy_engine.compliance.investigation import (
    InvestigationEngine,
    InvestigationStatus,
    EvidenceType,
)
from vinzy_engine.compliance.reporting import (
    ComplianceReporter,
    ComplianceStatus,
)
from vinzy_engine.compliance.schema_migration import (
    SchemaMigrationGenerator,
    MigrationOpType,
    SchemaSnapshot,
)
from vinzy_engine.compliance.key_evolution import (
    KeyFormatEvolver,
    KeyFormat,
    MigrationAction,
)
from vinzy_engine.compliance.revenue_recognition import (
    RevenueRecognizer,
    RecognitionMethod,
    RevenueStatus,
)
from vinzy_engine.compliance.recovery import (
    ComplianceRecoveryEngine,
    ViolationType,
    RecoveryAction,
    RecoveryStatus,
)


# ═══════════════════════════════════════════════════════════════════════
# FraudDetector
# ═══════════════════════════════════════════════════════════════════════

class TestFraudDetector:

    def test_no_fraud_normal_usage(self):
        detector = FraudDetector()
        event = UsageEvent(license_id="lic-1", ip_address="1.2.3.4", machine_id="m1")
        signals = detector.analyze(event)
        assert signals == []

    def test_velocity_ip_abuse(self):
        detector = FraudDetector(velocity_window_seconds=3600, velocity_ip_threshold=3)
        now = time.time()
        signals = []
        for i in range(5):
            event = UsageEvent(
                license_id="lic-1",
                ip_address=f"10.0.0.{i}",
                timestamp=now,
            )
            signals.extend(detector.analyze(event))
        assert any(s.fraud_type == FraudType.VELOCITY_ABUSE for s in signals)

    def test_velocity_machine_abuse(self):
        detector = FraudDetector(velocity_machine_threshold=2)
        now = time.time()
        signals = []
        for i in range(5):
            event = UsageEvent(
                license_id="lic-1",
                machine_id=f"machine-{i}",
                timestamp=now,
            )
            signals.extend(detector.analyze(event))
        assert any(s.fraud_type == FraudType.VELOCITY_ABUSE for s in signals)

    def test_clock_manipulation(self):
        detector = FraudDetector(clock_drift_tolerance_seconds=1.0)
        now = time.time()
        # First event at now
        detector.analyze(UsageEvent(license_id="lic-1", timestamp=now))
        # Second event 1 hour in the past
        signals = detector.analyze(UsageEvent(license_id="lic-1", timestamp=now - 3600))
        assert any(s.fraud_type == FraudType.CLOCK_MANIPULATION for s in signals)

    def test_burst_abuse(self):
        detector = FraudDetector(burst_window_seconds=60.0, burst_threshold=5)
        now = time.time()
        signals = []
        for i in range(10):
            signals.extend(detector.analyze(
                UsageEvent(license_id="lic-1", timestamp=now, metric="call")
            ))
        assert any(s.fraud_type == FraudType.BURST_ABUSE for s in signals)

    def test_cloning_detection(self):
        detector = FraudDetector()
        now = time.time()
        # Two licenses with identical usage patterns
        for metric in ["api_call", "token_use", "model_load"] * 5:
            detector.analyze(UsageEvent(license_id="lic-A", metric=metric, value=10.0, timestamp=now))
            detector.analyze(UsageEvent(license_id="lic-B", metric=metric, value=10.0, timestamp=now))

        signals = detector.check_cloning(["lic-A", "lic-B"], min_overlap=0.5)
        assert len(signals) >= 1
        assert signals[0].fraud_type == FraudType.PATTERN_CLONING

    def test_get_signals_filtered(self):
        detector = FraudDetector(velocity_ip_threshold=1)
        now = time.time()
        for i in range(3):
            detector.analyze(UsageEvent(license_id="lic-1", ip_address=f"10.0.0.{i}", timestamp=now))

        all_signals = detector.get_signals()
        assert len(all_signals) >= 1

        filtered = detector.get_signals(fraud_type=FraudType.VELOCITY_ABUSE)
        assert all(s.fraud_type == FraudType.VELOCITY_ABUSE for s in filtered)

    def test_resolve_signal(self):
        detector = FraudDetector(velocity_ip_threshold=1)
        now = time.time()
        for i in range(3):
            detector.analyze(UsageEvent(license_id="lic-1", ip_address=f"10.0.0.{i}", timestamp=now))

        signals = detector.get_signals(unresolved_only=True)
        assert len(signals) >= 1
        detector.resolve_signal(signals[0])
        assert signals[0].resolved is True

    def test_stats(self):
        detector = FraudDetector()
        detector.analyze(UsageEvent(license_id="lic-1"))
        stats = detector.stats
        assert stats["total_events_analyzed"] == 1
        assert stats["tracked_licenses"] == 1

    def test_clear(self):
        detector = FraudDetector()
        detector.analyze(UsageEvent(license_id="lic-1"))
        detector.clear()
        assert detector.stats["tracked_licenses"] == 0

    def test_signal_to_dict(self):
        signal = FraudSignal(
            license_id="lic-1",
            fraud_type=FraudType.VELOCITY_ABUSE,
            severity=FraudSeverity.HIGH,
            confidence=0.85,
        )
        d = signal.to_dict()
        assert d["fraud_type"] == "velocity_abuse"
        assert d["severity"] == "high"
        assert d["confidence"] == 0.85


# ═══════════════════════════════════════════════════════════════════════
# InvestigationEngine
# ═══════════════════════════════════════════════════════════════════════

class TestInvestigationEngine:

    def test_open_investigation(self):
        engine = InvestigationEngine()
        report = engine.open_investigation("lic-1")
        assert report.license_id == "lic-1"
        assert report.status == InvestigationStatus.OPEN
        assert report.severity_score == 0.0

    def test_add_evidence(self):
        engine = InvestigationEngine()
        report = engine.open_investigation("lic-1")
        item = engine.add_evidence(
            report.id, EvidenceType.ANOMALY, "test", "Test anomaly", severity_weight=2.0,
        )
        assert item is not None
        assert report.status == InvestigationStatus.INVESTIGATING
        assert report.severity_score == 2.0

    def test_add_anomaly_evidence(self):
        engine = InvestigationEngine()
        report = engine.open_investigation("lic-1")
        item = engine.add_anomaly_evidence(report.id, {
            "anomaly_type": "usage_spike", "severity": "high",
        })
        assert item is not None
        assert item.severity_weight == 2.0

    def test_add_fraud_evidence(self):
        engine = InvestigationEngine()
        report = engine.open_investigation("lic-1")
        item = engine.add_fraud_evidence(report.id, {
            "fraud_type": "velocity_abuse", "severity": "critical",
        })
        assert item is not None
        assert item.severity_weight == 5.0

    def test_severity_scoring_and_action(self):
        engine = InvestigationEngine()
        report = engine.open_investigation("lic-1")
        # Add evidence to reach 3.0 (restrict)
        engine.add_evidence(report.id, EvidenceType.MANUAL, "t", "d", severity_weight=3.0)
        assert report.recommended_action == "restrict"

        # Add more to reach 6.0 (suspend)
        engine.add_evidence(report.id, EvidenceType.MANUAL, "t", "d", severity_weight=3.0)
        assert report.recommended_action == "suspend"

        # Add more to reach 9.0 (revoke + auto-escalate)
        engine.add_evidence(report.id, EvidenceType.MANUAL, "t", "d", severity_weight=3.0)
        assert report.recommended_action == "revoke"
        assert report.status == InvestigationStatus.ESCALATED

    def test_escalate(self):
        engine = InvestigationEngine()
        report = engine.open_investigation("lic-1")
        assert engine.escalate(report.id, note="Needs review")
        assert report.status == InvestigationStatus.ESCALATED

    def test_resolve(self):
        engine = InvestigationEngine()
        report = engine.open_investigation("lic-1")
        assert engine.resolve(report.id, "admin", note="Resolved")
        assert report.status == InvestigationStatus.RESOLVED

    def test_dismiss(self):
        engine = InvestigationEngine()
        report = engine.open_investigation("lic-1")
        assert engine.dismiss(report.id, reason="False positive")
        assert report.status == InvestigationStatus.DISMISSED

    def test_get_investigations_for_license(self):
        engine = InvestigationEngine()
        engine.open_investigation("lic-1")
        engine.open_investigation("lic-1")
        engine.open_investigation("lic-2")

        reports = engine.get_investigations_for_license("lic-1")
        assert len(reports) == 2

    def test_list_investigations(self):
        engine = InvestigationEngine()
        r1 = engine.open_investigation("lic-1")
        r2 = engine.open_investigation("lic-2")
        engine.add_evidence(r1.id, EvidenceType.MANUAL, "t", "d", severity_weight=5.0)

        results = engine.list_investigations(min_severity=3.0)
        assert len(results) == 1
        assert results[0].id == r1.id

    def test_add_evidence_to_resolved_fails(self):
        engine = InvestigationEngine()
        report = engine.open_investigation("lic-1")
        engine.resolve(report.id, "admin")
        item = engine.add_evidence(report.id, EvidenceType.MANUAL, "t", "d")
        assert item is None

    def test_stats(self):
        engine = InvestigationEngine()
        engine.open_investigation("lic-1")
        stats = engine.stats
        assert stats["total_created"] == 1
        assert stats["active_investigations"] == 1

    def test_report_to_dict(self):
        engine = InvestigationEngine()
        report = engine.open_investigation("lic-1")
        d = report.to_dict()
        assert d["license_id"] == "lic-1"
        assert d["status"] == "open"


# ═══════════════════════════════════════════════════════════════════════
# ComplianceReporter
# ═══════════════════════════════════════════════════════════════════════

class TestComplianceReporter:

    def test_compliant_license(self):
        reporter = ComplianceReporter()
        entry = reporter.assess_license({
            "license_id": "lic-1",
            "machines_limit": 5,
            "machines_used": 3,
            "status": "active",
        })
        assert entry.is_compliant
        assert entry.status == ComplianceStatus.COMPLIANT

    def test_machine_overuse_warning(self):
        reporter = ComplianceReporter()
        entry = reporter.assess_license({
            "license_id": "lic-1",
            "machines_limit": 5,
            "machines_used": 6,
            "status": "active",
        })
        assert entry.status == ComplianceStatus.WARNING
        assert not entry.usage_within_limits

    def test_machine_overuse_violation(self):
        reporter = ComplianceReporter()
        entry = reporter.assess_license({
            "license_id": "lic-1",
            "machines_limit": 5,
            "machines_used": 20,
            "status": "active",
        })
        assert entry.status == ComplianceStatus.VIOLATION

    def test_anomaly_warning(self):
        reporter = ComplianceReporter(anomaly_warning_threshold=2)
        entry = reporter.assess_license({
            "license_id": "lic-1",
            "machines_limit": 5,
            "machines_used": 3,
            "anomaly_count": 3,
        })
        assert entry.status == ComplianceStatus.WARNING

    def test_fraud_violation(self):
        reporter = ComplianceReporter(fraud_violation_threshold=2)
        entry = reporter.assess_license({
            "license_id": "lic-1",
            "machines_limit": 5,
            "machines_used": 3,
            "fraud_signal_count": 5,
        })
        assert entry.status == ComplianceStatus.VIOLATION

    def test_usage_record_violation(self):
        reporter = ComplianceReporter()
        entry = reporter.assess_license({
            "license_id": "lic-1",
            "machines_limit": 5,
            "machines_used": 3,
            "usage_records": [
                {"metric": "api_calls", "value": 1500, "limit": 1000},
            ],
        })
        assert not entry.usage_within_limits

    def test_suspended_under_review(self):
        reporter = ComplianceReporter()
        entry = reporter.assess_license({
            "license_id": "lic-1",
            "machines_limit": 5,
            "machines_used": 3,
            "status": "suspended",
        })
        assert entry.status == ComplianceStatus.UNDER_REVIEW

    def test_generate_report(self):
        reporter = ComplianceReporter()
        report = reporter.generate_report([
            {"license_id": "lic-1", "machines_limit": 5, "machines_used": 3, "status": "active"},
            {"license_id": "lic-2", "machines_limit": 5, "machines_used": 20, "status": "active"},
            {"license_id": "lic-3", "machines_limit": 5, "machines_used": 3, "status": "suspended"},
        ])
        assert report.total_licenses == 3
        assert report.compliant_count == 1
        assert report.violation_count == 1
        assert report.review_count == 1
        assert 0.0 < report.compliance_rate < 1.0

    def test_report_summary(self):
        reporter = ComplianceReporter()
        report = reporter.generate_report([
            {"license_id": "lic-1", "machines_limit": 5, "machines_used": 3},
        ])
        assert "compliance_rate" in report.summary

    def test_get_reports(self):
        reporter = ComplianceReporter()
        reporter.generate_report([{"license_id": "lic-1"}])
        reporter.generate_report([{"license_id": "lic-2"}])
        assert len(reporter.get_reports()) == 2

    def test_get_latest_report(self):
        reporter = ComplianceReporter()
        assert reporter.get_latest_report() is None
        reporter.generate_report([{"license_id": "lic-1"}])
        assert reporter.get_latest_report() is not None

    def test_report_to_dict(self):
        reporter = ComplianceReporter()
        report = reporter.generate_report([{"license_id": "lic-1"}])
        d = report.to_dict()
        assert "compliance_rate" in d
        assert "entries" in d


# ═══════════════════════════════════════════════════════════════════════
# SchemaMigrationGenerator
# ═══════════════════════════════════════════════════════════════════════

class TestSchemaMigrationGenerator:

    def test_no_changes(self):
        gen = SchemaMigrationGenerator()
        schema = {"users": {"columns": {"id": {"type": "String"}, "name": {"type": "String"}}}}
        old = gen.create_snapshot(schema)
        new = gen.create_snapshot(schema)
        plan = gen.diff(old, new)
        assert plan.is_empty

    def test_add_table(self):
        gen = SchemaMigrationGenerator()
        old = gen.create_snapshot({})
        new = gen.create_snapshot({
            "users": {"columns": {"id": {"type": "String"}, "name": {"type": "String"}}},
        })
        plan = gen.diff(old, new)
        assert not plan.is_empty
        assert plan.operations[0].op_type == MigrationOpType.ADD_TABLE
        assert plan.operations[0].table_name == "users"

    def test_drop_table(self):
        gen = SchemaMigrationGenerator()
        old = gen.create_snapshot({"users": {"columns": {"id": {"type": "String"}}}})
        new = gen.create_snapshot({})
        plan = gen.diff(old, new)
        assert plan.operations[0].op_type == MigrationOpType.DROP_TABLE

    def test_add_column(self):
        gen = SchemaMigrationGenerator()
        old = gen.create_snapshot({"users": {"columns": {"id": {"type": "String"}}}})
        new = gen.create_snapshot({"users": {"columns": {"id": {"type": "String"}, "email": {"type": "String"}}}})
        plan = gen.diff(old, new)
        add_ops = [o for o in plan.operations if o.op_type == MigrationOpType.ADD_COLUMN]
        assert len(add_ops) == 1
        assert add_ops[0].column_name == "email"

    def test_drop_column(self):
        gen = SchemaMigrationGenerator()
        old = gen.create_snapshot({"users": {"columns": {"id": {"type": "String"}, "email": {"type": "String"}}}})
        new = gen.create_snapshot({"users": {"columns": {"id": {"type": "String"}}}})
        plan = gen.diff(old, new)
        drop_ops = [o for o in plan.operations if o.op_type == MigrationOpType.DROP_COLUMN]
        assert len(drop_ops) == 1
        assert drop_ops[0].column_name == "email"

    def test_alter_column_type(self):
        gen = SchemaMigrationGenerator()
        old = gen.create_snapshot({"users": {"columns": {"id": {"type": "Integer"}}}})
        new = gen.create_snapshot({"users": {"columns": {"id": {"type": "String"}}}})
        plan = gen.diff(old, new)
        alter_ops = [o for o in plan.operations if o.op_type == MigrationOpType.ALTER_COLUMN]
        assert len(alter_ops) == 1

    def test_to_alembic_script(self):
        gen = SchemaMigrationGenerator()
        old = gen.create_snapshot({})
        new = gen.create_snapshot({"users": {"columns": {"id": {"type": "String"}}}})
        plan = gen.diff(old, new)
        script = plan.to_alembic_script("001_initial")
        assert "def upgrade():" in script
        assert "def downgrade():" in script
        assert "create_table" in script

    def test_schema_checksum(self):
        gen = SchemaMigrationGenerator()
        s1 = gen.create_snapshot({"users": {"columns": {"id": {"type": "String"}}}})
        s2 = gen.create_snapshot({"users": {"columns": {"id": {"type": "String"}}}})
        assert s1.checksum == s2.checksum

        s3 = gen.create_snapshot({"users": {"columns": {"id": {"type": "Integer"}}}})
        assert s1.checksum != s3.checksum

    def test_migration_op_to_dict(self):
        from vinzy_engine.compliance.schema_migration import MigrationOp
        op = MigrationOp(op_type=MigrationOpType.ADD_TABLE, table_name="users")
        d = op.to_dict()
        assert d["op_type"] == "add_table"

    def test_history(self):
        gen = SchemaMigrationGenerator()
        old = gen.create_snapshot({})
        new = gen.create_snapshot({"t": {"columns": {"id": {"type": "String"}}}})
        gen.diff(old, new)
        assert len(gen.get_history()) == 1


# ═══════════════════════════════════════════════════════════════════════
# KeyFormatEvolver
# ═══════════════════════════════════════════════════════════════════════

class TestKeyFormatEvolver:

    def _make_key(self, prefix="ZUL", version_char="A"):
        # Simulate key: PRD-VXXXX-XXXXX-XXXXX-XXXXX-XXXXX-HHHHH-HHHHH
        return f"{prefix}-{version_char}BCDE-FGHIJ-KLMNO-PQRST-UVWXY-ZABCD-EFGHI"

    def test_analyze_v0_key(self):
        evolver = KeyFormatEvolver(current_version=1)
        key = self._make_key(version_char="A")  # A = index 0 in base32
        info = evolver.analyze_key(key)
        assert info.detected_format == KeyFormat.V0
        assert info.hmac_version == 0
        assert info.is_valid_structure is True
        assert info.needs_migration is True

    def test_analyze_v1_key(self):
        evolver = KeyFormatEvolver(current_version=1)
        key = self._make_key(version_char="B")  # B = index 1 in base32
        info = evolver.analyze_key(key)
        assert info.detected_format == KeyFormat.V1
        assert info.hmac_version == 1
        assert info.needs_migration is False

    def test_analyze_invalid_key(self):
        evolver = KeyFormatEvolver()
        info = evolver.analyze_key("invalid")
        assert info.is_valid_structure is False

    def test_create_migration_plan_no_action(self):
        evolver = KeyFormatEvolver(current_version=1)
        key = self._make_key(version_char="B")
        plan = evolver.create_migration_plan([
            {"license_id": "lic-1", "raw_key": key, "key_hash": "hash1"},
        ], target_version=1)
        assert plan.total == 1
        assert plan.entries[0].action == MigrationAction.NO_ACTION

    def test_create_migration_plan_re_sign(self):
        evolver = KeyFormatEvolver(current_version=1)
        key = self._make_key(version_char="A")
        plan = evolver.create_migration_plan([
            {"license_id": "lic-1", "raw_key": key, "key_hash": "hash1"},
        ], target_version=1)
        assert plan.total == 1
        assert plan.entries[0].action == MigrationAction.RE_SIGN

    def test_create_migration_plan_deprecate(self):
        evolver = KeyFormatEvolver(current_version=1)
        plan = evolver.create_migration_plan([
            {"license_id": "lic-1", "raw_key": "", "key_hash": "hash1"},
        ])
        assert plan.entries[0].action == MigrationAction.DEPRECATE

    def test_mark_migrated(self):
        evolver = KeyFormatEvolver()
        key = self._make_key()
        plan = evolver.create_migration_plan([{"license_id": "lic-1", "raw_key": key}])
        entry = plan.entries[0]
        evolver.mark_migrated(entry)
        assert entry.migrated is True
        assert plan.completed == 1

    def test_stats(self):
        evolver = KeyFormatEvolver(current_version=1)
        evolver.analyze_key(self._make_key())
        stats = evolver.stats
        assert stats["total_analyzed"] == 1
        assert stats["current_version"] == 1


# ═══════════════════════════════════════════════════════════════════════
# RevenueRecognizer
# ═══════════════════════════════════════════════════════════════════════

class TestRevenueRecognizer:

    def test_immediate_recognition(self):
        rec = RevenueRecognizer()
        entry = rec.record_sale("lic-1", "cust-1", "TSC", 99.99, method=RecognitionMethod.IMMEDIATE)
        assert entry.status == RevenueStatus.RECOGNIZED
        assert entry.recognized_amount_usd == 99.99
        assert entry.deferred_amount_usd == 0.0

    def test_deferred_recognition(self):
        rec = RevenueRecognizer()
        entry = rec.record_sale("lic-1", "cust-1", "TSC", 365.0, method=RecognitionMethod.DEFERRED, period_days=365)
        assert entry.status == RevenueStatus.PENDING
        assert entry.deferred_amount_usd == 365.0

    def test_recognize_deferred_partial(self):
        rec = RevenueRecognizer()
        entry = rec.record_sale("lic-1", "cust-1", "TSC", 100.0, method=RecognitionMethod.DEFERRED, period_days=100)
        # Simulate 50 days elapsed
        updated = rec.recognize_deferred(as_of=entry.period_start + (50 * 86400))
        assert updated == 1
        assert entry.status == RevenueStatus.DEFERRED_PARTIAL
        assert 45.0 <= entry.recognized_amount_usd <= 55.0

    def test_recognize_deferred_full(self):
        rec = RevenueRecognizer()
        entry = rec.record_sale("lic-1", "cust-1", "TSC", 100.0, method=RecognitionMethod.DEFERRED, period_days=1)
        updated = rec.recognize_deferred(as_of=entry.period_start + 200000)
        assert updated == 1
        assert entry.status == RevenueStatus.RECOGNIZED

    def test_usage_based_recognition(self):
        rec = RevenueRecognizer()
        entry = rec.record_sale("lic-1", "cust-1", "TSC", 200.0, method=RecognitionMethod.USAGE_BASED)
        updated = rec.recognize_usage("lic-1", 0.5)
        assert updated == 1
        assert entry.recognized_amount_usd == 100.0

    def test_refund(self):
        rec = RevenueRecognizer()
        entry = rec.record_sale("lic-1", "cust-1", "TSC", 50.0)
        assert rec.refund(entry.id) is True
        assert entry.status == RevenueStatus.REFUNDED

    def test_generate_report(self):
        rec = RevenueRecognizer()
        rec.record_sale("lic-1", "cust-1", "TSC", 100.0)
        rec.record_sale("lic-2", "cust-2", "ZUL", 200.0)
        report = rec.generate_report()
        assert report.total_revenue_usd == 300.0
        assert report.entry_count == 2
        assert "TSC" in report.by_product

    def test_get_entries_for_license(self):
        rec = RevenueRecognizer()
        rec.record_sale("lic-1", "cust-1", "TSC", 100.0)
        rec.record_sale("lic-1", "cust-1", "TSC", 50.0)
        entries = rec.get_entries_for_license("lic-1")
        assert len(entries) == 2

    def test_stats(self):
        rec = RevenueRecognizer()
        rec.record_sale("lic-1", "cust-1", "TSC", 100.0)
        stats = rec.stats
        assert stats["total_entries"] == 1
        assert stats["total_recognized_usd"] == 100.0

    def test_entry_to_dict(self):
        rec = RevenueRecognizer()
        entry = rec.record_sale("lic-1", "cust-1", "TSC", 100.0)
        d = entry.to_dict()
        assert d["amount_usd"] == 100.0
        assert d["method"] == "immediate"


# ═══════════════════════════════════════════════════════════════════════
# ComplianceRecoveryEngine
# ═══════════════════════════════════════════════════════════════════════

class TestComplianceRecoveryEngine:

    def test_scan_clean_license(self):
        engine = ComplianceRecoveryEngine()
        violations = engine.scan_license({
            "license_id": "lic-1",
            "customer_id": "cust-1",
            "machines_limit": 5,
            "machines_used": 3,
            "status": "active",
        })
        assert violations == []

    def test_scan_machine_overuse(self):
        engine = ComplianceRecoveryEngine(machine_overuse_rate_per_machine_usd=10.0)
        violations = engine.scan_license({
            "license_id": "lic-1",
            "customer_id": "cust-1",
            "machines_limit": 5,
            "machines_used": 8,
        })
        assert len(violations) == 1
        assert violations[0].violation_type == ViolationType.MACHINE_OVERUSE
        assert violations[0].estimated_revenue_loss_usd == 30.0  # 3 excess * $10

    def test_scan_expired_usage(self):
        engine = ComplianceRecoveryEngine(expired_usage_daily_rate_usd=5.0)
        violations = engine.scan_license({
            "license_id": "lic-1",
            "customer_id": "cust-1",
            "machines_limit": 5,
            "machines_used": 3,
            "is_expired": True,
            "status": "active",
            "days_overdue": 10,
        })
        assert len(violations) == 1
        assert violations[0].violation_type == ViolationType.EXPIRED_USAGE
        assert violations[0].estimated_revenue_loss_usd == 50.0

    def test_scan_unauthorized_features(self):
        engine = ComplianceRecoveryEngine()
        violations = engine.scan_license({
            "license_id": "lic-1",
            "customer_id": "cust-1",
            "machines_limit": 5,
            "machines_used": 3,
            "features_entitled": ["basic", "api"],
            "features_used": ["basic", "api", "premium", "white_label"],
        })
        feature_violations = [v for v in violations if v.violation_type == ViolationType.FEATURE_UNAUTHORIZED]
        assert len(feature_violations) == 1

    def test_scan_usage_limit_exceeded(self):
        engine = ComplianceRecoveryEngine()
        violations = engine.scan_license({
            "license_id": "lic-1",
            "customer_id": "cust-1",
            "machines_limit": 5,
            "machines_used": 3,
            "usage_records": [{"metric": "api_calls", "value": 1500, "limit": 1000}],
        })
        assert any(v.violation_type == ViolationType.USAGE_LIMIT_EXCEEDED for v in violations)

    def test_generate_recovery_tasks(self):
        engine = ComplianceRecoveryEngine()
        violations = engine.scan_license({
            "license_id": "lic-1",
            "customer_id": "cust-1",
            "machines_limit": 5,
            "machines_used": 8,
        })
        tasks = engine.generate_recovery_tasks(violations)
        assert len(tasks) == 1
        assert tasks[0].status == RecoveryStatus.PENDING
        assert tasks[0].recoverable_amount_usd > 0

    def test_complete_task(self):
        engine = ComplianceRecoveryEngine()
        violations = engine.scan_license({
            "license_id": "lic-1", "customer_id": "c1",
            "machines_limit": 5, "machines_used": 10,
        })
        tasks = engine.generate_recovery_tasks(violations)
        assert engine.complete_task(tasks[0].id, recovered_amount=25.0, note="Paid")
        assert tasks[0].status == RecoveryStatus.COMPLETED
        assert tasks[0].recovered_amount_usd == 25.0

    def test_waive_task(self):
        engine = ComplianceRecoveryEngine()
        violations = engine.scan_license({
            "license_id": "lic-1", "customer_id": "c1",
            "machines_limit": 5, "machines_used": 10,
        })
        tasks = engine.generate_recovery_tasks(violations)
        assert engine.waive_task(tasks[0].id, reason="Customer goodwill")
        assert tasks[0].status == RecoveryStatus.WAIVED

    def test_get_pending_tasks(self):
        engine = ComplianceRecoveryEngine()
        violations = engine.scan_license({
            "license_id": "lic-1", "customer_id": "c1",
            "machines_limit": 5, "machines_used": 10,
        })
        engine.generate_recovery_tasks(violations)
        pending = engine.get_pending_tasks()
        assert len(pending) == 1

    def test_get_violations_for_license(self):
        engine = ComplianceRecoveryEngine()
        engine.scan_license({
            "license_id": "lic-1", "customer_id": "c1",
            "machines_limit": 5, "machines_used": 10,
        })
        viol = engine.get_violations_for_license("lic-1")
        assert len(viol) >= 1

    def test_stats(self):
        engine = ComplianceRecoveryEngine()
        violations = engine.scan_license({
            "license_id": "lic-1", "customer_id": "c1",
            "machines_limit": 5, "machines_used": 10,
        })
        engine.generate_recovery_tasks(violations)
        stats = engine.stats
        assert stats["total_violations"] >= 1
        assert stats["total_tasks"] >= 1
        assert stats["pending_tasks"] >= 1

    def test_clear(self):
        engine = ComplianceRecoveryEngine()
        engine.scan_license({
            "license_id": "lic-1", "customer_id": "c1",
            "machines_limit": 5, "machines_used": 10,
        })
        engine.clear()
        assert engine.stats["total_violations"] == 0
