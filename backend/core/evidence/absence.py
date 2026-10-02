"""
When is absence actually evidence? A deliberately tiny allowlist.

`CONTRADICTED` is the only output of this system that could wrong an honest
person. Everything else either credits them or says "we could not tell". So the
question this module answers is narrow and the default answer is no:

    For which skills does "we read the artifacts and it is not there" genuinely
    mean "they probably do not use it"?

A skill not listed here can NEVER be CONTRADICTED, whatever the evidence looks
like. That is the safe default, and it is where every skill starts.

THE ADMISSION CRITERION, which matters more than the list itself:

1. **The evidence must live in the FILE TREE, not only in a manifest.** We read
   every tree entry but sample at most MAX_MANIFESTS_PER_REPO manifests per repo.
   So for a manifest-only skill, absence may simply mean we never opened the file
   that declared it. A database driver is the clearest example: `mysqlclient` could
   sit in a requirements file we did not fetch, which makes MySQL's absence
   uninformative no matter how many repos we scanned.

2. **The artifact must be effectively unavoidable.** Using Docker without a
   Dockerfile, or Terraform without a `.tf` file, is close to impossible. Using
   MongoDB without any locally-declared driver is entirely possible -- through a
   hosted client, an ORM, or a managed backend.

3. **The artifact must live where we look.** Root or a conventional directory, not
   buried behind a build step or in a sibling infrastructure repository.

Skills failing ANY of the three stay off the list. Most do.

WHAT A CONTRADICTION MEANS TO THE CANDIDATE. Not "you lied". It means: *your public
code does not back this claim, so either add evidence or mark it as private work*
(EA / FR-41). The attestation path exists precisely so that a candidate whose real
Docker experience lives at work has a truthful answer available. That is why the
verdict is survivable -- and why it must stay rare.

Thresholds are named constants, tuned later on Dataset A (EVIDENCE_MODEL section
8.3), starting strict. A missed contradiction costs one absent insight; a false one
tells an honest student they look like a liar.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Repos in which the detecting channel must have been read before absence counts.
#: Below this we simply have not looked in enough places. Deliberately high: on a
#: typical student profile this excludes anyone with only a handful of repos, which
#: is the population most likely to be wronged by a false accusation.
ABSENCE_MIN_REPOS_WITH_CHANNEL = 8

#: Fraction of in-scope repos whose detecting channel must have been retrieved.
#: Guards the case where many repos were listed but few actually read.
ABSENCE_MIN_CHANNEL_COVERAGE = 0.75


@dataclass(frozen=True)
class AbsenceRule:
    #: The artifact a user of this skill would almost certainly have committed.
    expected_artifact: str
    #: Why absence is informative here. Surfaced to the candidate, because an
    #: unexplained accusation is indefensible.
    rationale: str


#: THE ALLOWLIST. Two entries. Both are file-tree detectable, both have an
#: effectively unavoidable artifact, and both live at a conventional path.
#:
#: Candidates considered and REJECTED, with reasons, because the rejections are
#: the substance of this design:
#:
#:   MySQL / MongoDB / PostgreSQL / Redis -- manifest-only. The driver may be in a
#:       requirements file we did not sample, and these services are routinely used
#:       through a hosted client or ORM that never names them locally. Fails (1).
#:   React / Angular / Vue -- manifest-only, same sampling problem. Fails (1).
#:   CI/CD -- file-tree detectable, but using CI at work while keeping personal
#:       repos plain is completely normal. Fails (2).
#:   Kubernetes -- manifests usually live in a separate infrastructure repository
#:       that is not part of the candidate's profile at all. Fails (3).
#:   TypeScript / Python / Java -- language skills are already positively detected
#:       from language statistics, so a contradiction adds nothing a reader could
#:       not already see.
ABSENCE_ALLOWLIST: dict[str, AbsenceRule] = {
    "Docker": AbsenceRule(
        expected_artifact="a Dockerfile or docker-compose file",
        rationale=(
            "Docker cannot be used on a project without a Dockerfile or compose "
            "file committed alongside it. Across every repository we read, none "
            "contains either."
        ),
    ),
    "Terraform": AbsenceRule(
        expected_artifact="a .tf file",
        rationale=(
            "Terraform configuration is .tf files kept in the repository it "
            "provisions. None of the repositories we read contains any."
        ),
    ),
}


def can_be_contradicted(skill: str) -> bool:
    """Default NO. Only an allowlisted skill is ever eligible."""
    return skill in ABSENCE_ALLOWLIST


def rule_for(skill: str) -> AbsenceRule | None:
    return ABSENCE_ALLOWLIST.get(skill)


def absence_is_evidence(
    skill: str,
    *,
    found: bool,
    repos_with_channel: int,
    channel_coverage: float | None,
) -> bool:
    """Is this skill's absence strong enough to support CONTRADICTED?

    Only answers the "would it necessarily have appeared" half. The remaining
    §8.3 gates -- authorship share, overall coverage, non-partial profile -- are
    applied by core.evidence.model.verdict(), so there is one place that decides.
    """
    if found:
        return False
    if not can_be_contradicted(skill):
        return False
    if repos_with_channel < ABSENCE_MIN_REPOS_WITH_CHANNEL:
        return False
    if channel_coverage is None or channel_coverage < ABSENCE_MIN_CHANNEL_COVERAGE:
        return False
    return True


def explain(skill: str, repos_with_channel: int) -> str:
    """Candidate-facing explanation.

    ORDER IS DELIBERATE: the legitimate explanation comes first (voice rule 1,
    docs/PLAN.md section 9.6). The most likely reason a claim lacks public
    evidence is that the work was private or at an employer -- not that it was
    invented. Leading with the finding and burying the remedy reads as an
    accusation with a footnote; leading with the remedy reads as a prompt to add
    evidence, which is what this verdict is actually for.
    """
    rule = ABSENCE_ALLOWLIST.get(skill)
    if rule is None:
        return ""
    return (
        f"If your {skill} experience is from private or work code, mark it as "
        f"private and it will show as attested rather than unsupported. "
        f"Otherwise, adding it to a public project would make it verifiable. "
        f"Why this came up: {rule.rationale} We looked for "
        f"{rule.expected_artifact} across {repos_with_channel} repositories."
    )
