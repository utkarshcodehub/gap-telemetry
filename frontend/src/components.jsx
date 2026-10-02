// Presentational components. State lives in App.jsx; these just render.

const TIER_META = {
  critical: { compound: 'S', color: 'var(--soft)', label: 'Critical' },
  important: { compound: 'M', color: 'var(--medium)', label: 'Important' },
  nice_to_have: { compound: 'H', color: 'var(--hard)', label: 'Nice to have' },
};

export function readinessColor(score) {
  return score >= 70 ? 'var(--green)' : score >= 40 ? 'var(--medium)' : 'var(--soft)';
}

/**
 * The headline gauge: VERIFIED readiness filled, CLAIMED marked on the same arc.
 *
 * The gap between them is the product, so it is drawn rather than described. The
 * legacy `resume | github` union score is deliberately NOT shown anywhere — it
 * still ships in the API for the report and the regression tests, but a
 * two-number story only reads clearly when there are exactly two numbers, and
 * this page briefly had three.
 *
 * With no GitHub evidence, claimed is shown alone and labelled unverified. That
 * is honest: 0% verified with 0% coverage means "we could not check", which is a
 * different statement from "you scored zero".
 */
export function ReadinessGauge({ report, evidence }) {
  const claimed = evidence ? evidence.claimed_readiness : report.readiness_score;
  const verified = evidence ? evidence.verified_readiness : null;
  const cov = evidence ? evidence.verification_coverage : null;
  const hasEvidence = verified !== null && cov !== null;

  const shown = hasEvidence ? verified : claimed;
  const color = readinessColor(shown);
  const SEGMENTS = 24;
  const lit = Math.round((shown / 100) * SEGMENTS);
  const claimedSeg = Math.round((claimed / 100) * SEGMENTS);
  const gap = Math.round((claimed - shown) * 10) / 10;

  return (
    <section className="panel">
      <h2>Readiness — {report.role}</h2>
      <div className="gauge-row">
        <div>
          <svg viewBox="0 0 200 120" width="220" role="img"
               aria-label={hasEvidence
                 ? `Verified readiness ${verified} of 100, claimed ${claimed}`
                 : `Claimed readiness ${claimed} of 100, unverified`}>
            {Array.from({ length: SEGMENTS }, (_, i) => {
              const angle = Math.PI * (1 - i / (SEGMENTS - 1));
              const x1 = 100 + Math.cos(angle) * 70;
              const y1 = 105 - Math.sin(angle) * 70;
              const x2 = 100 + Math.cos(angle) * 88;
              const y2 = 105 - Math.sin(angle) * 88;
              // Segments between verified and claimed are the gap: drawn faintly
              // in the claimed colour so the shortfall is visible, not implied.
              const inGap = hasEvidence && i >= lit && i < claimedSeg;
              return (
                <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
                      stroke={i < lit ? color : inGap ? color : 'var(--line)'}
                      strokeOpacity={inGap ? 0.28 : 1}
                      strokeWidth="5" strokeLinecap="round" />
              );
            })}
          </svg>
          <div className="gauge-num" style={{ color }}>
            {shown}<small> / 100</small>
          </div>
          <div className="gauge-label">
            {hasEvidence ? 'verified — backed by your own code' : 'claimed — not yet verified'}
          </div>
        </div>
        <div className="gauge-facts">
          {hasEvidence ? (
            <>
              <div className="fact"><b>{claimed}%</b><span>claimed — what your resume asserts</span></div>
              <div className="fact"><b>{gap}pp</b><span>the gap: claims your code does not yet back</span></div>
              <div className="fact"><b>{Math.round(cov * 100)}%</b><span>of your claims we could check at all</span></div>
            </>
          ) : (
            <div className="fact">
              <span>◈ Add your GitHub username to verify these claims against your
              own code. Until then this is a self-report.</span>
            </div>
          )}
          <div className="fact"><b>{report.total_market_skills}</b><span>skills in the market basket for this role</span></div>
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
 * Per-claim verdicts, grouped by what the evidence actually says.
 *
 * The NUMBERS live in ReadinessGauge; this panel is the detail behind them, so it
 * deliberately repeats none of them. Groups are labelled by finding rather than by
 * score, and by-design-unverifiable skills say so explicitly - a candidate must
 * never read "we could not check this" as "this counts against you".
 */
export function EvidenceSummary({ evidence }) {
  if (!evidence || !evidence.assessments.length) return null;

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
        Every claim, checked
        {evidence.repos_analysed > 0 && (
          <span className="engine-tag">{evidence.repos_analysed} repos read</span>
        )}
      </h2>

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
