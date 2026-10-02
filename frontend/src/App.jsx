import { useEffect, useRef, useState } from 'react';
import { analyze, fetchRoles, getRoadmap, saveAnalysis } from './api';
import { GapBoard, GitHubEvidencePanel, ReadinessGauge, RoadmapTimeline, StrengthsPanel } from './components';
import HistoryPanel from './HistoryPanel';
import RoleFitPage from './RoleFitPage';
import { applyTheme, getInitialTheme } from './theme';

// There is deliberately NO hardcoded fallback role list.
//
// There used to be one, seeded as the initial state with invented posting counts
// ("Product Manager · 76 postings" — not even a role this system can analyse).
// It rendered before /roles resolved and persisted forever if the backend was
// unreachable, so the very first thing a user saw was fabricated market data,
// and picking one of those names 404s on /market/{role}. Every posting count in
// this UI must come from the database or not be shown at all.
//
// `null` means "not loaded yet", `[]` means "loaded, and the market is empty" —
// two different states that need two different messages.

/**
 * States which market the demand numbers describe and what data backs them.
 *
 * Not decoration. The corpus mixes an archival Q4 2020 sample with a live feed,
 * and the two differ materially — the 2020 data contains no LLM, RAG or MLOps
 * postings, because that market did not exist yet. A percentage shown without
 * its provenance invites the reader to assume it is current. Every string here
 * comes from the server (see backend/core/market/sources.py); this component
 * asserts nothing of its own.
 */
function MarketProvenance({ market, provenance }) {
  if (!market || !provenance.length) return null;
  const total = provenance.reduce((n, p) => n + p.postings, 0);
  return (
    <p className="provenance">
      <b>{market}</b> market · {total.toLocaleString()} postings ·{' '}
      {provenance.map((p, i) => (
        <span key={p.source}>
          {i > 0 && ' + '}
          {p.postings.toLocaleString()} {p.label}
          {p.live ? '' : ` (${p.vintage})`}
        </span>
      ))}
    </p>
  );
}

export default function App({ accessToken, userEmail, onSignOut }) {
  const [tab, setTab] = useState('telemetry'); // 'telemetry' | 'rolefit'
  const [roles, setRoles] = useState(null);
  const [role, setRole] = useState('');
  // Which market these numbers describe, and what data backs them. Both come
  // from the server — the UI must never assert a provenance claim of its own.
  const [market, setMarket] = useState(null);
  const [provenance, setProvenance] = useState([]);
  const [resumeText, setResumeText] = useState('');
  const [resumeFile, setResumeFile] = useState(null);
  const [github, setGithub] = useState('');

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [roadmap, setRoadmap] = useState(null);
  const [roadmapBusy, setRoadmapBusy] = useState(false);
  const [saveStatus, setSaveStatus] = useState('');
  const fileRef = useRef(null);
  const [theme, setTheme] = useState(getInitialTheme());
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  // Structured, not a string: severity and evidence_used come from the
  // server. Inferring them from a prefix is how an expired token went
  // unnoticed while every analysis quietly fell back to resume-only.
  const [githubStatus, setGithubStatus] = useState(null);

  useEffect(() => { applyTheme(theme); }, [theme]);

  useEffect(() => {
    fetchRoles()
      .then(({ market, roles: list, provenance }) => {
        setMarket(market);
        setProvenance(provenance);
        setRoles(list);
        if (!list.length) {
          setError(
            'No market data in the database. Seed it from backend/ with: ' +
            'python ../scraper/naukri_cc0_ingest.py');
          return;
        }
        // Keep the current selection only if it's still a valid option in the
        // freshly-fetched list — otherwise the <select>'s value points at a role
        // with no matching <option>, which renders blank and sends /analyze a
        // role it has no market data for.
        setRole((current) => (list.some((x) => x.role === current) ? current : list[0].role));
      })
      .catch(() => {
        // Show no roles rather than invented ones: a disabled picker is honest,
        // a populated one built from made-up counts is not.
        setRoles([]);
        setMarket(null);
        setProvenance([]);
        setError(
          'Backend unreachable. Start it from backend/ with: ' +
          'uvicorn app.main:app --reload');
      });
  }, []);

  async function onAnalyze() {
    setBusy(true); setError(''); setResult(null); setRoadmap(null); setSaveStatus(''); setGithubStatus(null);
    try {
      const data = await analyze({
        role, resumeText: resumeText.trim() || null, resumeFile,
        githubUsername: github.trim() || null, accessToken,
      });
      setResult(data);
      setGithubStatus(data.github || null);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function onRoadmap() {
    if (!result) return;
    setRoadmapBusy(true); setError('');
    try {
      const githubSkills = Object.fromEntries(
        result.report.strengths.filter((s) => s.github_repos > 0).map((s) => [s.canonical, s.github_repos]),
      );
      const plan = await getRoadmap({
        role: result.report.role, resumeSkills: result.resume_skills_found,
        githubSkills, accessToken,
      });
      setRoadmap(plan);
    } catch (e) {
      setError(e.message);
    } finally {
      setRoadmapBusy(false);
    }
  }

  async function onSave() {
    if (!result) return;
    setSaveStatus('Saving…');
    try {
      await saveAnalysis({ role: result.report.role, report: result.report, accessToken });
      setSaveStatus('Saved to your account ✓');
      setHistoryRefreshKey((k) => k + 1);
    } catch (e) {
      setSaveStatus(`Couldn't save: ${e.message}`);
    }
  }

  return (
    <>
      <header className="masthead">
        <div className="masthead-left">
          <div className="masthead-logo">GT</div>
          <div>
            <h1>Gap<span>·</span>Telemetry</h1>
            <div className="sub">job-skill gap intelligence · market-weighted</div>
          </div>
        </div>
        <div className="masthead-right">
          <button className="theme-toggle" onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}>
            {theme === 'dark' ? '☀ Light' : '● Dark'}
          </button>
          <div className="user-chip">
            <span className="user-avatar">{userEmail?.[0]?.toUpperCase() ?? 'U'}</span>
            {userEmail}
            <button className="link" onClick={onSignOut}>Sign out</button>
          </div>
        </div>
      </header>

      <div className="nav-tabs">
        <button className={`nav-tab ${tab === 'telemetry' ? 'active' : ''}`} onClick={() => setTab('telemetry')}>
          Gap Telemetry
        </button>
        <button className={`nav-tab ${tab === 'rolefit' ? 'active' : ''}`} onClick={() => setTab('rolefit')}>
          Role Fit
        </button>
      </div>

      {tab === 'rolefit' ? (
        <RoleFitPage accessToken={accessToken} />
      ) : (
      <>
      <section className="panel">
        <h2 style={{ cursor: 'pointer' }} onClick={() => setHistoryOpen((o) => !o)}>
          Saved analyses {historyOpen ? '▾' : '▸'}
        </h2>
        {historyOpen && <HistoryPanel accessToken={accessToken} refreshKey={historyRefreshKey} />}
      </section>

      <section className="panel">
        <h2>Session setup</h2>
        <div className="form-grid">
          <div>
            <label htmlFor="role">Target role</label>
            <select
              id="role"
              value={role}
              disabled={!roles || !roles.length}
              onChange={(e) => setRole(e.target.value)}
            >
              {/* Three distinct states, none of them invented data. */}
              {roles === null && <option value="">Loading roles…</option>}
              {roles !== null && !roles.length && <option value="">No market data</option>}
              {(roles || []).map((r) => (
                <option key={r.role} value={r.role}>
                  {r.role} · {r.postings} postings
                </option>
              ))}
            </select>
            <MarketProvenance market={market} provenance={provenance} />
          </div>
          <div>
            <label htmlFor="gh">GitHub username (optional)</label>
            <input id="gh" type="text" placeholder="e.g. utkarshcodehub" value={github} onChange={(e) => setGithub(e.target.value)} />
            {githubStatus && githubStatus.state !== 'not_requested' && (
              <div className={`gh-status ${githubStatus.severity === 'info' ? 'ok' : 'warn'}`}>
                {githubStatus.evidence_used
                  ? `✓ GitHub: ${githubStatus.message} — see "GitHub evidence" below`
                  : `⚠ No GitHub evidence was used. ${githubStatus.message}`}
              </div>
            )}
          </div>
          <div className="full">
            <label htmlFor="file">Resume PDF</label>
            <div id="file" className={`filedrop ${resumeFile ? 'hasfile' : ''}`} role="button" tabIndex={0}
                 onClick={() => fileRef.current?.click()}
                 onKeyDown={(e) => e.key === 'Enter' && fileRef.current?.click()}>
              {resumeFile ? `✓ ${resumeFile.name}` : 'Click to choose a PDF — or paste resume text below'}
            </div>
            <input ref={fileRef} type="file" accept="application/pdf" hidden
                   onChange={(e) => setResumeFile(e.target.files?.[0] ?? null)} />
          </div>
          <div className="full">
            <label htmlFor="txt">Resume text (used if no PDF chosen)</label>
            <textarea id="txt" value={resumeText} placeholder="Paste your skills / projects section here…"
                      onChange={(e) => setResumeText(e.target.value)} />
          </div>
          <div className="full">
            <button className="primary" disabled={busy || !role || (!resumeFile && !resumeText.trim())} onClick={onAnalyze}>
              {busy ? 'Analyzing…' : 'Run gap analysis'}
            </button>
          </div>
        </div>
        {error && <div className="error">{error}</div>}
      </section>

      {result && (
        <>
          <ReadinessGauge report={result.report} />
          <StrengthsPanel report={result.report} />
          <GitHubEvidencePanel githubStatus={githubStatus} report={result.report} />
          <GapBoard gaps={result.report.gaps} />
          <section className="panel">
            <h2>Next steps</h2>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
              {!roadmap && (
                <button className="ghost" disabled={roadmapBusy} onClick={onRoadmap}>
                  {roadmapBusy ? 'Generating…' : 'Generate learning roadmap'}
                </button>
              )}
              <button className="ghost" onClick={onSave}>Save this analysis</button>
              {saveStatus && <span className="spinner">{saveStatus}</span>}
            </div>
            {roadmapBusy && <p className="spinner" style={{ marginTop: 10 }}>Planning stints from your gap tiers…</p>}
          </section>
          {roadmap && <RoadmapTimeline roadmap={roadmap} />}
        </>
      )}
      </>
      )}
    </>
  );
}
