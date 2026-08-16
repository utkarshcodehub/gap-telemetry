import { useEffect, useRef, useState } from 'react';
import { analyze, fetchRoles, getRoadmap, saveAnalysis } from './api';
import { GapBoard, GitHubEvidencePanel, ReadinessGauge, RoadmapTimeline, StrengthsPanel } from './components';
import HistoryPanel from './HistoryPanel';
import RoleFitPage from './RoleFitPage';
import { applyTheme, getInitialTheme } from './theme';

const FALLBACK_ROLES = [
  { role: 'Frontend Engineer', postings: 120 },
  { role: 'Backend Engineer', postings: 104 },
  { role: 'Data Analyst', postings: 88 },
  { role: 'Product Manager', postings: 76 },
  { role: 'Full Stack Engineer', postings: 132 },
];

export default function App({ accessToken, userEmail, onSignOut }) {
  const [tab, setTab] = useState('telemetry'); // 'telemetry' | 'rolefit'
  const [roles, setRoles] = useState(FALLBACK_ROLES);
  const [role, setRole] = useState(FALLBACK_ROLES[0].role);
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
  const [githubStatus, setGithubStatus] = useState('');

  useEffect(() => { applyTheme(theme); }, [theme]);

  useEffect(() => {
    fetchRoles()
      .then((r) => {
        const list = Array.isArray(r) && r.length ? r : FALLBACK_ROLES;
        setRoles(list);
        // Keep the current selection only if it's still a valid option in
        // the freshly-fetched list — otherwise the <select>'s value points
        // at a role that no longer has a matching <option> (stale fallback
        // name vs. real seeded roles), which renders blank and sends a
        // role /analyze has no market data for.
        setRole((current) => (list.some((r) => r.role === current) ? current : list[0].role));
      })
      .catch(() => {
        setRoles(FALLBACK_ROLES);
        setRole((current) => (FALLBACK_ROLES.some((r) => r.role === current) ? current : FALLBACK_ROLES[0].role));
        setError(
          'Backend unreachable. Start it with: uvicorn app.main:app (from backend/), ' +
          'and seed data with the synthetic generator.');
      });
  }, []);

  async function onAnalyze() {
    setBusy(true); setError(''); setResult(null); setRoadmap(null); setSaveStatus(''); setGithubStatus('');
    try {
      const data = await analyze({
        role, resumeText: resumeText.trim() || null, resumeFile,
        githubUsername: github.trim() || null, accessToken,
      });
      setResult(data);
      setGithubStatus(data.github_status || '');
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
            <select id="role" value={role || roles[0]?.role || ''} onChange={(e) => setRole(e.target.value)}>
              {roles.map((r) => <option key={r.role} value={r.role}>{r.role} · {r.postings} postings</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="gh">GitHub username (optional)</label>
            <input id="gh" type="text" placeholder="e.g. utkarshcodehub" value={github} onChange={(e) => setGithub(e.target.value)} />
            {githubStatus && githubStatus !== 'not_requested' && (
              <div className={`gh-status ${githubStatus.startsWith('ok') ? 'ok' : 'warn'}`}>
                {githubStatus.startsWith('ok') ? `✓ GitHub: ${githubStatus} — see "GitHub evidence" below` : `⚠ GitHub: ${githubStatus}`}
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
