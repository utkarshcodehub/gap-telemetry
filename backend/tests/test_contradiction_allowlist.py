"""
Tests for the absence allowlist (core/evidence/absence.py).

CONTRADICTED is the only verdict that could wrong an honest person, so these
tests are mostly about what the system REFUSES to conclude. The rejections are the
design; the two admissions are the exception.

Pure unit tests.
"""

from __future__ import annotations

import pytest

from core.evidence.absence import (
    ABSENCE_ALLOWLIST,
    ABSENCE_MIN_CHANNEL_COVERAGE,
    ABSENCE_MIN_REPOS_WITH_CHANNEL,
    absence_is_evidence,
    can_be_contradicted,
    explain,
    rule_for,
)
from core.evidence.channels import CHANNELS, Channel
from core.evidence.model import SkillEvidence, Verdict, verdict

PLENTY = dict(coverage_value=1.0, authored_repo_count=20)
AMPLE = dict(repos_with_channel=20, channel_coverage=1.0)


# --------------------------------------------------------- the default is NO

def test_the_allowlist_is_tiny():
    """If this grows casually, the safety property is gone. Any addition should be
    a deliberate decision with a recorded rationale."""
    assert len(ABSENCE_ALLOWLIST) <= 4, (
        f"allowlist has grown to {sorted(ABSENCE_ALLOWLIST)} -- each entry must "
        f"satisfy all three admission criteria in the module docstring"
    )


@pytest.mark.parametrize("skill", [
    "MySQL", "MongoDB", "PostgreSQL", "Redis",      # manifest-only: we SAMPLE manifests
    "React", "Angular", "Vue.js",                   # manifest-only
    "CI/CD",                                        # normal to use at work only
    "Kubernetes",                                   # config lives in a separate repo
    "Python", "TypeScript", "Java",                 # already positively detected
    "System Design", "Agile", "REST API",           # not artifact-verifiable at all
])
def test_most_skills_can_never_be_contradicted(skill):
    assert can_be_contradicted(skill) is False
    assert absence_is_evidence(skill, found=False, **AMPLE) is False


def test_an_unknown_skill_can_never_be_contradicted():
    """Fails closed: a skill the allowlist has never heard of is not eligible."""
    assert can_be_contradicted("Some Future Framework") is False


def test_database_skills_are_excluded_for_a_concrete_reason():
    """The sampling problem, stated as a test.

    We read every tree entry but at most MAX_MANIFESTS_PER_REPO manifests per repo.
    A database driver can therefore sit in a requirements file we never opened, so
    its absence is uninformative however many repos we scanned.
    """
    for skill in ("MySQL", "MongoDB", "PostgreSQL"):
        spec = CHANNELS[skill]
        assert spec.channels == {Channel.MANIFEST}, (
            f"{skill} is manifest-only, which is why it cannot be contradicted"
        )
        assert can_be_contradicted(skill) is False


# ------------------------------------------------------------ the admissions

@pytest.mark.parametrize("skill", ["Docker", "Terraform"])
def test_allowlisted_skills_are_file_tree_detectable(skill):
    """Admission criterion 1: the evidence must live in the tree, which we read
    completely, not in a manifest, which we sample."""
    assert Channel.FILE_TREE in CHANNELS[skill].channels
    assert can_be_contradicted(skill) is True
    assert rule_for(skill) is not None


def test_docker_absence_counts_when_we_looked_hard_enough():
    assert absence_is_evidence("Docker", found=False, **AMPLE) is True


def test_finding_the_skill_is_never_counter_evidence():
    assert absence_is_evidence("Docker", found=True, **AMPLE) is False


# ------------------------------------------------- "we did not look hard enough"

def test_too_few_repos_is_not_enough_to_accuse():
    assert absence_is_evidence(
        "Docker", found=False,
        repos_with_channel=ABSENCE_MIN_REPOS_WITH_CHANNEL - 1,
        channel_coverage=1.0,
    ) is False


def test_thin_channel_coverage_is_not_enough_to_accuse():
    """Many repos listed but few actually read must not look like a search."""
    assert absence_is_evidence(
        "Docker", found=False, repos_with_channel=20,
        channel_coverage=ABSENCE_MIN_CHANNEL_COVERAGE - 0.05,
    ) is False
    assert absence_is_evidence(
        "Docker", found=False, repos_with_channel=20, channel_coverage=None,
    ) is False


def test_thresholds_start_strict():
    """A missed contradiction costs one absent insight; a false one tells an honest
    student they look like a liar. So these begin high and loosen only on data."""
    assert ABSENCE_MIN_REPOS_WITH_CHANNEL >= 5
    assert ABSENCE_MIN_CHANNEL_COVERAGE >= 0.6


# --------------------------------------------------------- defence in depth

def test_verdict_enforces_the_allowlist_even_if_counter_evidence_is_forced():
    """A caller setting counter_evidence by hand must not bypass the allowlist."""
    forced = SkillEvidence("MySQL", counter_evidence=True, authorship_share=0.9)
    assert verdict(forced, **PLENTY) is Verdict.UNVERIFIABLE

    allowed = SkillEvidence("Docker", counter_evidence=True, authorship_share=0.9)
    assert verdict(allowed, **PLENTY) is Verdict.CONTRADICTED


# ---------------------------------------------------------------- the message

def test_the_explanation_names_the_artifact_and_offers_the_remedy():
    """An accusation without a remedy is indefensible. The attestation path exists
    so a candidate whose Docker experience is at work has a truthful answer."""
    msg = explain("Docker", repos_with_channel=23)
    assert "Dockerfile" in msg
    assert "23 repositories" in msg
    assert "private" in msg.lower(), "must point at the attestation route"


def test_no_explanation_for_a_skill_that_cannot_be_contradicted():
    assert explain("MySQL", repos_with_channel=23) == ""


def test_every_allowlist_entry_explains_itself():
    for skill, rule in ABSENCE_ALLOWLIST.items():
        assert rule.expected_artifact, skill
        assert len(rule.rationale) > 40, f"{skill} needs a real rationale"
