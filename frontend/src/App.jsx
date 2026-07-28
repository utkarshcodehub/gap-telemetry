import { useEffect, useRef, useState } from 'react';
import { analyze, fetchRoles, getRoadmap, saveAnalysis } from './api';
import { GapBoard, ReadinessGauge, RoadmapTimeline, StrengthsPanel } from './components';

export default function App({ accessToken, userEmail, onSignOut }) {
  const [roles, setRoles] = useState([]);
  const [role, setRole] = useState('');
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

  useEffect(() => {
    fetchRoles()
      .then((r) => { setRoles(r); if (r.length) setRole(r[0].role); })
      .catch(() => setError(
        'Backend unreachable. Start it with: uvicorn app.main:app (from backend/), ' +
        'and seed data with the synthetic generator.'));
  }, []);

  async function onAnalyze() {
    setBusy(true); setError(''); setResult(null); setRoadmap(null); setSaveStatus('');
    try {
      const data = await analyze({
        role, resumeText: resumeText.trim() || null, resumeFile,
        githubUsername: github.trim() || null, accessToken,
      });
      setResult(data);
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
    } catch (e) {
      setSaveStatus(`Couldn't save: ${e.message}`);
    }
  }

  return (
    <>
      <header className="masthead">
        <div className="masthead-left">
          <h1>Gap<span>·</span>Telemetry</h1>
          <span className="sub">job-skill gap intelligence · market-weighted</span>
        </div>
        <div className="user-chip">
          {userEmail}
          <button className="link" onClick={onSignOut}>Sign out</button>
        </div>
      </header>

      <section className="panel">
        <h2>Session setup</h2>
        <div className="form-grid">
          <div>
            <label htmlFor="role">Target role</label>
            <select id="role" value={role} onChange={(e) => setRole(e.target.value)}>
              {roles.map((r) => <option key={r.role} value={r.role}>{r.role} · {r.postings} postings</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="gh">GitHub username (optional)</label>
            <input id="gh" type="text" placeholder="e.g. utkarshcodehub" value={github} onChange={(e) => setGithub(e.target.value)} />
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
  );
}
