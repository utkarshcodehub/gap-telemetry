// Presentational components. State lives in App.jsx; these just render.

const TIER_META = {
  critical: { compound: 'S', color: 'var(--soft)', label: 'Critical' },
  important: { compound: 'M', color: 'var(--medium)', label: 'Important' },
  nice_to_have: { compound: 'H', color: 'var(--hard)', label: 'Nice to have' },
};

export function ReadinessGauge({ report }) {
  const score = report.readiness_score;
  const color = score >= 70 ? 'var(--green)' : score >= 40 ? 'var(--medium)' : 'var(--soft)';
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

export function RoadmapTimeline({ roadmap }) {
  return (
    <section className="panel">
      <h2>Learning roadmap
        <span className="engine-tag"> engine: {roadmap.engine === 'groq' ? 'Groq · LLaMA 3.3-70b' : 'rule-based fallback'}</span>
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
