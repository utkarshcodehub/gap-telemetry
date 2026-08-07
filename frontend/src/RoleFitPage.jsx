import { useEffect, useRef, useState } from 'react';
import { fetchListings, fetchListing, checkRoleFit } from './api';

// ── Verdict color mapping ──
const VERDICT_COLORS = {
  'Strong Fit': '#2ee6a6',
  'Good Fit': '#4dc9ff',
  'Partial Fit': '#ffc53d',
  'Needs Work': '#ff4d5e',
};

// ── Listing card in the grid (mirrors the real portal's card layout) ──
function ListingCard({ listing, onClick }) {
  return (
    <div className="tpo-card" onClick={onClick} role="button" tabIndex={0}
         onKeyDown={e => e.key === 'Enter' && onClick()}>
      <div className="tpo-card-logo">
        {listing.company.substring(0, 3).toUpperCase()}
      </div>
      <div className="tpo-card-body">
        <div className="tpo-card-meta">
          <span className="tpo-company">{listing.company}</span>
        </div>
        <h3 className="tpo-card-title">{listing.title}</h3>
        <div className="tpo-tags">
          <span className="tpo-tag">{listing.job_type}</span>
          <span className="tpo-tag">{listing.location}</span>
        </div>
        <div className="tpo-stipend">{listing.stipend}</div>
      </div>
    </div>
  );
}

// ── Match result card (the new thing — what appears after "Check Role Fit") ──
function MatchResultCard({ result }) {
  const color = VERDICT_COLORS[result.verdict] || '#8b95a3';
  const pct = result.match_pct;
  const circumference = 2 * Math.PI * 54;
  const filled = (pct / 100) * circumference;

  return (
    <div className="fit-result">
      <div className="fit-header">
        <div className="fit-gauge">
          <svg viewBox="0 0 120 120" width="120" height="120">
            <circle cx="60" cy="60" r="54" fill="none" stroke="#27303c" strokeWidth="8" />
            <circle cx="60" cy="60" r="54" fill="none" stroke={color} strokeWidth="8"
                    strokeDasharray={`${filled} ${circumference}`}
                    strokeLinecap="round"
                    transform="rotate(-90 60 60)" />
          </svg>
          <div className="fit-gauge-label">
            <span className="fit-pct" style={{ color }}>{pct}%</span>
          </div>
        </div>
        <div className="fit-verdict-block">
          <div className="fit-verdict" style={{ color }}>{result.verdict}</div>
          <div className="fit-subtitle">Role Fit · {result.listing_title} @ {result.company}</div>
        </div>
      </div>

      <p className="fit-explanation">{result.explanation}</p>

      <div className="fit-details">
        {result.matched_skills.length > 0 && (
          <div className="fit-section">
            <h4 className="fit-section-title fit-match">✓ Skills you have</h4>
            <div className="fit-chips">
              {result.matched_skills.map(s => (
                <span key={s} className="fit-chip fit-chip-match">{s}</span>
              ))}
            </div>
          </div>
        )}
        {result.missing_skills.length > 0 && (
          <div className="fit-section">
            <h4 className="fit-section-title fit-miss">✗ Skills to build</h4>
            <div className="fit-chips">
              {result.missing_skills.map(s => (
                <span key={s} className="fit-chip fit-chip-miss">{s}</span>
              ))}
            </div>
          </div>
        )}
        {result.unmatched_tags.length > 0 && (
          <div className="fit-section">
            <h4 className="fit-section-title fit-unclear">? Not confidently matched</h4>
            <div className="fit-chips">
              {result.unmatched_tags.map(s => (
                <span key={s} className="fit-chip fit-chip-unclear">{s}</span>
              ))}
            </div>
            <p className="fit-note">These are general traits from the listing, not specific technical skills — they don't affect your score.</p>
          </div>
        )}
      </div>

      {result.academic_marks_used.length > 0 && (
        <div className="fit-academic">
          Academic marks ({result.academic_marks_used.map(m => `${m}%`).join(', ')}) contributed{' '}
          <strong style={{ color: result.academic_adjustment >= 0 ? '#2ee6a6' : '#ff4d5e' }}>
            {result.academic_adjustment >= 0 ? '+' : ''}{result.academic_adjustment} pts
          </strong>{' '}
          to your score — a minor factor alongside the skill match.
        </div>
      )}
    </div>
  );
}

// ── Listing detail view (mirrors the real portal's detail page) ──
function ListingDetail({ listing, accessToken, onBack }) {
  const [resumeText, setResumeText] = useState('');
  const [resumeFile, setResumeFile] = useState(null);
  const [marks, setMarks] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const fileRef = useRef(null);

  async function onCheck() {
    setBusy(true); setError(''); setResult(null);
    try {
      const data = await checkRoleFit({
        listingId: listing.id,
        resumeText: resumeText.trim() || null,
        resumeFile,
        academicMarks: marks.trim() || null,
        accessToken,
      });
      setResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <button className="tpo-back" onClick={onBack}>← Back to listings</button>

      <div className="tpo-detail-card">
        <div className="tpo-detail-header">
          <div className="tpo-detail-logo">
            {listing.company.substring(0, 3).toUpperCase()}
          </div>
          <div>
            <h2 className="tpo-detail-title">{listing.title}</h2>
            <div className="tpo-detail-company">{listing.company} • {listing.location}</div>
            <div className="tpo-tags" style={{ marginTop: 8 }}>
              <span className="tpo-tag">{listing.job_type}</span>
              <span className="tpo-tag">{listing.experience_level}</span>
              <span className="tpo-tag">{listing.stipend}</span>
            </div>
          </div>
        </div>

        <div className="tpo-detail-section">
          <h3>Required Skills</h3>
          <div className="tpo-skill-tags">
            {listing.required_skills.map(s => (
              <span key={s} className="tpo-skill-tag">{s}</span>
            ))}
          </div>
        </div>

        <div className="tpo-detail-section">
          <h3>Eligible Branches</h3>
          <div className="tpo-tags">
            {listing.eligible_branches.map(b => (
              <span key={b} className="tpo-tag">{b}</span>
            ))}
          </div>
        </div>
      </div>

      <div className="tpo-fit-panel">
        <h3 className="tpo-fit-heading">⟐ Check Role Fit</h3>
        <p className="tpo-fit-sub">Compare your profile against this listing's requirements</p>

        <div className="tpo-fit-form">
          <div>
            <label>Resume PDF</label>
            <div className={`tpo-filedrop ${resumeFile ? 'has' : ''}`}
                 onClick={() => fileRef.current?.click()} role="button" tabIndex={0}
                 onKeyDown={e => e.key === 'Enter' && fileRef.current?.click()}>
              {resumeFile ? `✓ ${resumeFile.name}` : 'Click to choose PDF'}
            </div>
            <input ref={fileRef} type="file" accept="application/pdf" hidden
                   onChange={e => setResumeFile(e.target.files?.[0] ?? null)} />
          </div>
          <div>
            <label>Academic marks (optional)</label>
            <input type="text" placeholder="e.g. 94.6, 84.3"
                   value={marks} onChange={e => setMarks(e.target.value)} />
          </div>
          <div className="tpo-fit-full">
            <label>Or paste resume text</label>
            <textarea rows={4} placeholder="Paste your skills / projects section here…"
                      value={resumeText} onChange={e => setResumeText(e.target.value)} />
          </div>
          <div className="tpo-fit-full">
            <button className="tpo-fit-btn" disabled={busy || (!resumeFile && !resumeText.trim())}
                    onClick={onCheck}>
              {busy ? 'Computing…' : 'Check Role Fit'}
            </button>
          </div>
        </div>

        {error && <div className="tpo-error">{error}</div>}
      </div>

      {result && <MatchResultCard result={result} />}
    </div>
  );
}

// ── Main page: grid → detail drill-in ──
export default function RoleFitPage({ accessToken }) {
  const [listings, setListings] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchListings()
      .then(setListings)
      .catch(() => setError('Could not load listings — is the backend running?'));
  }, []);

  async function onSelect(listing) {
    try {
      const full = await fetchListing(listing.id);
      setDetail(full);
      setSelected(listing.id);
    } catch (e) {
      setError(e.message);
    }
  }

  if (selected && detail) {
    return (
      <ListingDetail
        listing={detail}
        accessToken={accessToken}
        onBack={() => { setSelected(null); setDetail(null); }}
      />
    );
  }

  return (
    <div>
      <h2 className="tpo-page-title">Recommended Jobs</h2>
      {error && <div className="tpo-error">{error}</div>}
      <div className="tpo-grid">
        {listings.map(l => (
          <ListingCard key={l.id} listing={l} onClick={() => onSelect(l)} />
        ))}
      </div>
    </div>
  );
}
