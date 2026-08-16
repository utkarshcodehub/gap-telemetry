import { useEffect, useState } from 'react';
import { deleteSavedAnalysis, getSavedAnalysis, listSavedAnalyses } from './api';
import { GapBoard, ReadinessGauge, StrengthsPanel, readinessColor } from './components';

export default function HistoryPanel({ accessToken, refreshKey }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [openId, setOpenId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailBusy, setDetailBusy] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  useEffect(() => {
    setLoading(true); setError('');
    listSavedAnalyses({ accessToken })
      .then(setItems)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [refreshKey]);

  async function onToggleOpen(id) {
    if (openId === id) { setOpenId(null); setDetail(null); return; }
    setOpenId(id); setDetail(null); setDetailBusy(true); setError('');
    try {
      const full = await getSavedAnalysis(id, { accessToken });
      setDetail(full);
    } catch (e) {
      setError(e.message);
    } finally {
      setDetailBusy(false);
    }
  }

  async function onConfirmDelete(id) {
    setDeleteBusy(true);
    try {
      await deleteSavedAnalysis(id, { accessToken });
      setItems((prev) => prev.filter((a) => a.id !== id));
      if (openId === id) { setOpenId(null); setDetail(null); }
      setPendingDeleteId(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setDeleteBusy(false);
    }
  }

  if (loading) return <p className="spinner">Loading saved analyses…</p>;
  if (error) return <div className="error">{error}</div>;
  if (!items.length) return <p className="history-empty">No saved analyses yet — run an analysis and click "Save this analysis".</p>;

  return (
    <div className="history-list">
      {items.map((a) => (
        <div key={a.id} className="history-item">
          <div className="history-row" onClick={() => onToggleOpen(a.id)} role="button" tabIndex={0}>
            <span className="history-role">{a.role}</span>
            <span className="history-score" style={{ color: readinessColor(a.readiness_score) }}>
              {a.readiness_score} / 100
            </span>
            <span className="history-date">{new Date(a.created_at).toLocaleDateString()}</span>
            <span className="history-caret">{openId === a.id ? '▾' : '▸'}</span>
          </div>

          {pendingDeleteId === a.id ? (
            <div className="history-confirm">
              <span>Delete this analysis?</span>
              <button className="danger" disabled={deleteBusy} onClick={() => onConfirmDelete(a.id)}>
                {deleteBusy ? 'Deleting…' : 'Yes, delete'}
              </button>
              <button className="ghost" disabled={deleteBusy} onClick={() => setPendingDeleteId(null)}>Cancel</button>
            </div>
          ) : (
            <div className="history-actions">
              <button className="ghost" onClick={() => setPendingDeleteId(a.id)}>Delete</button>
            </div>
          )}

          {openId === a.id && (
            <div className="history-detail">
              {detailBusy && <p className="spinner">Loading report…</p>}
              {detail && detail.id === a.id && (
                <>
                  <ReadinessGauge report={detail.report} />
                  <StrengthsPanel report={detail.report} />
                  <GapBoard gaps={detail.report.gaps} />
                </>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
