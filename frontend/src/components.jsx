// Presentational components. State lives in App.jsx; these just render.

const TIER_META = {
  critical: { compound: 'S', color: 'var(--soft)', label: 'Critical' },
  important: { compound: 'M', color: 'var(--medium)', label: 'Important' },
  nice_to_have: { compound: 'H', color: 'var(--hard)', label: 'Nice to have' },
};

export function readinessColor(score) {
  return score >= 70 ? 'var(--green)' : score >= 40 ? 'var(--medium)' : 'var(--soft)';
}

export function ReadinessGauge({ report }) {
  const score = report.readiness_score;
  const color = readinessColor(score);
  const SEGMENTS = 24;
  const lit = Math.round((score / 100) * SEGMENTS);

  return (
    <section className="panel">
      <h2>Readiness — {report.role}</h2>
      <div className="gauge-row">
        <div>
          <svg viewBox="0 0 200 120" width="220" role="img" aria-label={`Readiness ${score} out of 100`}>
            {Array.from({ length: SEGMENTS }, (_, i) => {
              const angle = Math.PI * (1 - i / (SEGMENTS - 1));
              const x1 = 100 + Math.cos(angle) * 70;
              const y1 = 105 - Math.sin(angle) * 70;
              const x2 = 100 + Math.cos(angle) * 88;
              const y2 = 105 - Math.sin(angle) * 88;
              return (
                <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
                      stroke={i < lit ? color : 'var(--line)'}
                      strokeWidth="5" strokeLinecap="round" />
              );
            })}
          </svg>
          <div className="gauge-num" style={{ color }}>{score}<small> / 100</small></div>
          <div className="gauge-label">demand-weighted market coverage</div>
        </div>
        <div className="gauge-facts">
          <div className="fact"><b>{report.total_market_skills}</b><span>skills in the market basket for this role</span></div>
          <div className="fact"><b>{report.strengths.length}</b><span>market-relevant strengths on your profile</span></div>
          <div className="fact"><b>{report.gaps.filter(g => g.tier === 'critical').length}</b><span>critical gaps blocking the biggest demand mass</span></div>
          {report.notes.map((n, i) => <div className="fact" key={i}><span>◈ {n}</span></div>)}
        </div>
      </div>
    </section>
  );
}

export function GapBoard({ gaps }) {
  const tiers = ['critical', 'important', 'nice_to_have'];
  return (
    <section className="panel">
      <h2>Skill gaps · demand share of postings</h2>
      {tiers.map((tier) => {
        const items = gaps.filter((g) => g.tier === tier);
        if (!items.length) return null;
        const meta = TIER_META[tier];
        return (
          <div className="tier" key={tier}>
            <div className="tier-head">
              <span className={`compound ${meta.compound}`}>{meta.compound}</span>
              <h3 style={{ color: meta.color }}>{meta.label}</h3>
              <span className="count">{items.length} skills</span>
            </div>
            {items.map((g) => (
              <div className="skill-row" key={g.canonical}>
                <div><span className="name">{g.canonical}</span><span className="cat">{g.category.replace(/_/g, ' ')}</span></div>
                <div className="bar"><i style={{ width: `${g.demand_pct}%`, background: meta.color }} /></div>
                <span className="pct">{g.demand_pct}%</span>
              </div>
            ))}
          </div>
        );
      })}
    </section>
  );
}

const EVIDENCE_BADGE = {
  resume: { cls: 'resume', text: 'resume' },
  github: { cls: 'github', text: 'github' },
  'resume+github': { cls: 'both', text: 'resume + github' },
};

export function StrengthsPanel({ report }) {
  if (!report.strengths.length) return null;
  const sorted = [...report.strengths].sort((a, b) => b.demand_pct - a.demand_pct);
  return (
    <section className="panel">
      <h2>Strengths the market is paying for</h2>
      {sorted.map((s) => {
        const badge = EVIDENCE_BADGE[s.evidence] ?? EVIDENCE_BADGE.resume;
        return (
          <div className="skill-row" key={s.canonical}>
            <div>
              <span className="name">{s.canonical}</span>
              <span className="cat">{s.category.replace(/_/g, ' ')}{s.github_repos > 0 && ` · ${s.github_repos} repo${s.github_repos > 1 ? 's' : ''}`}</span>
            </div>
            <div className="bar"><i style={{ width: `${s.demand_pct}%`, background: 'var(--green)' }} /></div>
            <span className={`badge ${badge.cls}`}>{badge.text}</span>
          </div>
        );
      })}
      {report.hidden_strengths.length > 0 && (
        <div className="hidden-call">
          <b>Hidden strengths:</b> {report.hidden_strengths.map((h) => h.canonical).join(', ')} —
          evidenced in your GitHub repos but missing from your resume. Add them with project links.
        </div>
      )}
    </section>
  );
}

export function GitHubEvidencePanel({ githubStatus, report }) {
  if (!githubStatus || githubStatus.state === 'not_requested') return null;

  // A fetch that did not happen must say so loudly, and must say that the
  // readiness score above was therefore computed from resume claims alone.
  // Reporting this as a quiet "skipped" line is the failure this replaces.
  if (!githubStatus.evidence_used) {
    return (
      <section className="panel">
        <h2>GitHub evidence <span className="engine-tag">not available</span></h2>
        <div className="error">
          <b>No GitHub evidence was used in the score above.</b>
          <div style={{ marginTop: 6, fontWeight: 400 }}>{githubStatus.message}</div>
        </div>
      </section>
    );
  }

  const hiddenNames = new Set(report.hidden_strengths.map((h) => h.canonical));
  const contributed = report.strengths.filter((s) => s.evidence === 'github' || s.evidence === 'resume+github');
  const repoCount = githubStatus.repos_analysed ?? '?';

  return (
    <section className="panel">
      <h2>GitHub evidence <span className="engine-tag">{repoCount} public repos scanned</span></h2>
      {contributed.length === 0 ? (
        <p className="history-empty">No skills beyond your resume were found in your public repos — either everything overlaps with your resume, or your repos don't showcase market-relevant skills yet.</p>
      ) : (
        <>
          <p style={{ marginBottom: 10, fontSize: 13, color: 'var(--muted)' }}>
            {hiddenNames.size > 0
              ? `${hiddenNames.size} skill${hiddenNames.size > 1 ? 's were' : ' was'} found only in your repos, not your resume:`
              : 'Skills your repos confirmed (already on your resume too):'}
          </p>
          {contributed.map((s) => {
            const isNew = hiddenNames.has(s.canonical);
            return (
              <div className="skill-row" key={s.canonical}>
                <div>
                  <span className="name">{s.canonical}</span>
                  <span className="cat">{s.category.replace(/_/g, ' ')} · {s.github_repos} repo{s.github_repos > 1 ? 's' : ''}</span>
                </div>
                <div className="bar"><i style={{ width: `${s.demand_pct}%`, background: isNew ? 'var(--cyan)' : 'var(--green)' }} /></div>
                <span className={`badge ${isNew ? 'github' : 'both'}`}>{isNew ? 'new · github only' : 'confirmed'}</span>
              </div>
            );
          })}
        </>
      )}
    </section>
  );
}

export function RoadmapTimeline({ roadmap }) {
  return (
    <section className="panel">
      <h2>Learning roadmap
        <span className="engine-tag"> engine: {roadmap.engine === 'groq' ? 'AI-generated' : 'rule-based fallback'}</span>
      </h2>
      {roadmap.summary && <p style={{ marginBottom: 10 }}>{roadmap.summary}</p>}
      <div className="stints">
        {roadmap.weeks.map((w) => (
          <div className="stint" key={w.week}>
            <div className="stint-num">W{w.week}<small>STINT</small></div>
            <div>
              <h4>{w.theme}</h4>
              <div className="chips">{w.skills.map((s) => <span className="chip" key={s}>{s}</span>)}</div>
              <ul>{w.actions.map((a, i) => <li key={i}>{a}</li>)}</ul>
              {w.project && <div className="project"><b>Build:</b> {w.project}</div>}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}


/**
 * The two readiness numbers, side by side. The GAP between them is the product.
 *
 * Claimed is what the resume asserts; verified is what the candidate's own code
 * backs up. Showing only one would be the thing this project exists to stop.
 * Coverage is shown prominently because a low verified score with low coverage
 * means "we could not check", not "you were exaggerating" - and conflating those
 * is what makes naive verification unfair.
 */
export function EvidenceSummary({ evidence }) {
  if (!evidence) return null;
  const { claimed_readiness: claimed, verified_readiness: verified } = evidence;
  const cov = evidence.verification_coverage;
  const gap = Math.round((claimed - verified) * 10) / 10;

  const byVerdict = {};
  for (const a of evidence.assessments) {
    (byVerdict[a.verdict] = byVerdict[a.verdict] || []).push(a);
  }
  const unver = byVerdict.UNVERIFIABLE || [];
  const byDesign = unver.filter((a) => a.unverifiable_reason === 'by_design');
  const notFound = unver.filter((a) => a.unverifiable_reason !== 'by_design');

  return (
    <section className="panel">
      <h2>
        Claimed vs verified
        <span className="engine-tag">{evidence.repos_analysed} repos read</span>
      </h2>

      <div className="facts">
        <div className="fact"><b>{claimed}%</b><span>claimed readiness — what your resume asserts</span></div>
        <div className="fact"><b>{verified}%</b><span>verified readiness — what your code backs up</span></div>
        <div className="fact"><b>{gap}pp</b><span>the gap: claims your artifacts do not yet support</span></div>
        <div className="fact">
          <b>{cov === null || cov === undefined ? 'n/a' : `${Math.round(cov * 100)}%`}</b>
          <span>of your claims we were able to check at all</span>
        </div>
      </div>

      {evidence.profile_partial && (
        <div className="gh-status warn">
          ⚠ Not every repository could be read, so anything missing below may simply
          be somewhere we did not look.
        </div>
      )}

      <VerdictGroup title="Verified by your code" items={byVerdict.VERIFIED} tone="ok" />
      <VerdictGroup title="Mentioned only in a README" items={byVerdict.WEAK} tone="warn" />
      <VerdictGroup title="Marked as private or work code" items={byVerdict.ATTESTED} tone="warn" />
      <VerdictGroup title="Claimed, not found in your public code" items={notFound} tone="warn" />
      <VerdictGroup
        title="Cannot be verified by code at all — not a mark against you"
        items={byDesign}
        tone="info"
      />

      {evidence.unclaimed_verified_skills.length > 0 && (
        <div className="hidden-strengths">
          <h3>In your code but not on your resume</h3>
          <p className="muted">
            Add these — they are already evidenced, and they are not counted in
            either number above.
          </p>
          <div className="chips">
            {evidence.unclaimed_verified_skills.map((s) => (
              <span key={s} className="chip">{s}</span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function VerdictGroup({ title, items, tone }) {
  if (!items || items.length === 0) return null;
  return (
    <div className={`verdict-group ${tone}`}>
      <h3>{title} <span className="count">{items.length}</span></h3>
      <div className="chips">
        {items
          .slice()
          .sort((a, b) => b.confidence - a.confidence)
          .map((a) => (
            <span key={a.skill} className="chip" title={
              `${a.max_tier ? `evidence tier ${a.max_tier}` : 'no artifact evidence'}`
              + ` · confidence ${a.confidence.toFixed(2)}`
              + ` · ${a.n_repos} repo(s)`
              + (a.in_demand_basket ? '' : " · outside this role's market demand")
            }>
              {a.skill}
              {!a.in_demand_basket && <i className="aside"> (not in demand)</i>}
            </span>
          ))}
      </div>
    </div>
  );
}
