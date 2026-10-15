import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { BarElement, CategoryScale, Chart as ChartJS, Legend, LinearScale, LineElement, PointElement, Tooltip } from 'chart.js'
import { Bar } from 'react-chartjs-2'
import { api } from '../api'
import { AttackChip, AttackChips, CategoryBadge, DISCLAIMER, ScoreBar, Status, STATUS_LABEL, fmt, useLoad } from '../components.jsx'

ChartJS.register(BarElement, CategoryScale, LinearScale, LineElement, PointElement, Tooltip, Legend)

function Breakdown({ items }) {
  return (
    <div className="table-responsive"><table className="table table-sm mb-0">
      <thead><tr><th>Indicator</th><th>Category</th><th>Source</th><th>MITRE ATT&CK</th><th className="text-end">Weight</th></tr></thead>
      <tbody>
        {items.map((b, i) => (
          <tr key={i}>
            <td>
              {b.name}
              {b.detail?.z !== undefined && (
                <div className="small text-muted">
                  observed {b.detail.observed} vs baseline {b.detail.baseline_mean} ± {b.detail.baseline_std} (z = {b.detail.z})
                </div>
              )}
            </td>
            <td>{b.category}</td><td>{b.source}</td><td><AttackChips techniques={b.attack} /></td><td className="text-end fw-semibold">+{b.weight}</td>
          </tr>
        ))}
      </tbody>
    </table></div>
  )
}

function AttackMapping({ attack }) {
  if (!attack) return null
  return <section className="attack-mapping" aria-label="MITRE ATT&CK mapping">
    <h3 className="h6 mt-3">MITRE ATT&CK mapping</h3>
    <p className="small text-muted">Mapping is analyst context derived from indicator type; it does not affect the score and is not proof a technique was used.</p>
    {(attack.tactics || []).map(tactic => <div key={tactic.id} className="mb-3">
      <h4 className="h6">{tactic.name}</h4>
      <ul className="list-unstyled mb-0">{(tactic.techniques || []).map(id => {
        const technique = (attack.techniques || []).find(t => t.id === id)
        return technique && <li key={id} className="mb-2">
          <AttackChip technique={technique} /> <span>{technique.name}</span>
          <div className="small text-muted">Confidence: {technique.confidence || 'unknown'} · Indicators: {(technique.indicators || []).join(', ')}</div>
          {technique.rationale && <div className="small text-muted">{technique.rationale}</div>}
        </li>
      })}</ul>
    </div>)}
    {!attack.techniques?.length && <p className="small text-muted">No mapped techniques.</p>}
    <p className="small text-muted">ATT&CK v{attack.attack_version} · {attack.attribution}</p>
  </section>
}

function CasePanel({ alertId }) {
  const { data: a, loading, error, reload } = useLoad(() => api.alert(alertId), [alertId])
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [aiMsg, setAiMsg] = useState(null)

  const act = async (fn) => {
    setBusy(true)
    try { await fn(); reload() } finally { setBusy(false) }
  }
  const explain = async () => {
    setBusy(true)
    setAiMsg(null)
    try {
      const r = await api.explain(alertId)
      if (!r.ai_available) setAiMsg('AI explanation unavailable — the deterministic evidence above is unaffected.')
      reload()
    } catch (e) { setAiMsg(e.message) } finally { setBusy(false) }
  }

  return (
    <Status loading={loading} error={error}>
      {a && (
        <div className="card p-3 mb-3">
          <div className="d-flex justify-content-between align-items-start mb-2">
            <div>
              <h2 className="h5 mb-1">Alert #{a.id} · <Link to={`/users/${a.user_id}`}>{a.user_id}</Link> <CategoryBadge category={a.category} /></h2>
              <div className="small text-muted">{a.department} · {fmt(a.start_time)} → {fmt(a.last_time)}</div>
            </div>
            <div className="text-end">
              <div className="small text-muted">Peak risk score</div>
              <div className="kpi">{a.peak_score}</div>
            </div>
          </div>
          <h3 className="h6 mt-2">Score composition (deterministic)</h3>
          <Breakdown items={a.breakdown} />
          <AttackMapping attack={a.attack} />

          <h3 className="h6 mt-3">AI-assisted explanation</h3>
          {a.narrative ? (
            <div className="ai-box p-3 rounded">
              <p className="mb-2">{a.narrative}</p>
              <div className="small text-muted">{a.narrative_disclaimer}</div>
            </div>
          ) : (
            <div className="text-muted small mb-2">
              {a.narrative_status === 'unavailable' ? 'No explanation available (AI service unavailable or not configured).' : 'No explanation requested yet.'}
            </div>
          )}
          {!a.narrative && <button className="btn btn-sm btn-outline-secondary mt-1" disabled={busy} onClick={explain}>Request AI explanation</button>}
          {aiMsg && <div className="small text-warning-emphasis mt-1">{aiMsg}</div>}

          <h3 className="h6 mt-4">Case</h3>
          <div className="d-flex align-items-center gap-2 mb-3">
            <label htmlFor="st" className="small text-muted">Status</label>
            <select id="st" className="form-select form-select-sm w-auto" value={a.status} disabled={busy}
              onChange={(e) => act(() => api.setStatus(a.id, e.target.value))}>
              {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          {a.notes.map((n) => (
            <div key={n.id} className="border-start border-3 ps-2 mb-2">
              <div className="small text-muted">{n.author} · {fmt(n.created_at)}</div>
              <div style={{ whiteSpace: 'pre-wrap' }}>{n.note}</div>
            </div>
          ))}
          <form className="d-flex gap-2" onSubmit={(e) => { e.preventDefault(); if (note.trim()) act(async () => { await api.addNote(a.id, note); setNote('') }) }}>
            <input className="form-control form-control-sm" placeholder="Add investigation note…" value={note} maxLength={4000} onChange={(e) => setNote(e.target.value)} aria-label="Investigation note" />
            <button className="btn btn-sm btn-primary" disabled={busy || !note.trim()}>Add</button>
          </form>
        </div>
      )}
    </Status>
  )
}

export default function RiskDetail({ mode }) {
  const { id } = useParams()
  const alertQ = useLoad(() => (mode === 'alert' ? api.alert(id) : Promise.resolve(null)), [id, mode])
  const userId = mode === 'alert' ? alertQ.data?.user_id : id
  const risk = useLoad(() => (userId ? api.userRisk(userId) : Promise.resolve(null)), [userId])
  const timeline = useLoad(() => (userId ? api.userTimeline(userId) : Promise.resolve([])), [userId])
  const activity = useLoad(() => (userId ? api.userActivity(userId) : Promise.resolve(null)), [userId])
  const r = risk.data

  const chart = (field, label, mean, std, color) => {
    const days = activity.data?.days || []
    const thr = mean !== undefined ? mean + 3 * std : null
    return {
      labels: days.map((d) => d.date.slice(5)),
      datasets: [{ label, data: days.map((d) => d[field]), backgroundColor: days.map((d) => (thr !== null && d[field] > thr ? '#b00020' : color)) }],
    }
  }
  const b = activity.data?.baseline

  return (
    <div className="row g-3">
      <div className="col-lg-7">
        {mode === 'alert' && <CasePanel alertId={id} />}
        <Status loading={risk.loading} error={risk.error}>
          {r && (
            <div className="card p-3 mb-3">
              <div className="d-flex justify-content-between">
                <h2 className="h5">{r.user_id} · {r.department}</h2>
                <CategoryBadge category={r.risk_category} />
              </div>
              <ScoreBar score={r.risk_score} category={r.risk_category} />
              <div className="small text-muted mt-1">Current risk (peak over recent window), as of {fmt(r.as_of)}</div>
              {r.breakdown.length > 0 && <div className="mt-3"><Breakdown items={r.breakdown} /></div>}
              <div className="small text-muted mt-2">{DISCLAIMER}</div>
            </div>
          )}
        </Status>
        <div className="card p-3">
          <h2 className="h6">Evidence timeline</h2>
          <Status loading={timeline.loading} error={timeline.error}>
            <div style={{ maxHeight: 420, overflowY: 'auto' }}>
              <table className="table table-sm mb-0">
                <thead><tr><th>Time</th><th>Indicator</th><th>Source</th><th>Event</th><th>ATT&CK</th><th className="text-end">Weight</th></tr></thead>
                <tbody>
                  {(timeline.data || []).map((t, i) => (
                    <tr key={i}>
                      <td className="small text-nowrap">{fmt(t.time)}</td>
                      <td>{t.indicator}</td>
                      <td><span className={`badge ${t.source === 'honeytoken' ? 'bg-danger' : t.source === 'anomaly' ? 'bg-info text-dark' : 'bg-secondary'}`}>{t.source}</span></td>
                      <td className="small mono">{t.event ? `${t.event.event_type}${t.event.volume_mb ? ` ${t.event.volume_mb}MB` : ''} ${t.event.resource || t.event.device_id || ''}` : '—'}</td>
                      <td><AttackChips techniques={t.attack} /></td>
                      <td className="text-end">{t.weight}</td>
                    </tr>
                  ))}
                  {timeline.data?.length === 0 && <tr><td colSpan={6} className="text-muted text-center py-3">No indicators fired for this user.</td></tr>}
                </tbody>
              </table>
            </div>
          </Status>
        </div>
      </div>

      <div className="col-lg-5">
        <div className="card p-3 mb-3">
          <h2 className="h6">Daily file accesses vs baseline</h2>
          {activity.data && <Bar data={chart('access', 'File accesses', b?.daily_access?.mean, b?.daily_access?.std, '#3a86ff')} options={{ plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }} />}
          {b?.daily_access && <div className="small text-muted">Baseline {b.daily_access.mean} ± {b.daily_access.std}/day · red bars exceed baseline + 3σ</div>}
        </div>
        <div className="card p-3 mb-3">
          <h2 className="h6">Daily download volume (MB) vs baseline</h2>
          {activity.data && <Bar data={chart('download_mb', 'Download MB', b?.daily_download_mb?.mean, b?.daily_download_mb?.std, '#8338ec')} options={{ plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }} />}
          {b?.daily_download_mb && <div className="small text-muted">Baseline {b.daily_download_mb.mean} ± {b.daily_download_mb.std} MB/day</div>}
        </div>
        {r?.baseline && (
          <div className="card p-3">
            <h2 className="h6">Behavioural baseline <span className="badge bg-light text-dark">{r.baseline.status}</span></h2>
            {r.baseline.status === 'established' ? (
              <dl className="row small mb-0">
                <dt className="col-5">Typical login hour</dt><dd className="col-7">{r.baseline.login_hour.mean.toFixed(1)} ± {r.baseline.login_hour.std.toFixed(1)} h</dd>
                <dt className="col-5">Known devices</dt><dd className="col-7 mono">{r.baseline.devices.join(', ') || '—'}</dd>
                <dt className="col-5">Resource types</dt><dd className="col-7">{r.baseline.resource_types.join(', ') || '—'}</dd>
                <dt className="col-5">Learning window</dt><dd className="col-7">{fmt(r.baseline.window_start)} → {fmt(r.baseline.window_end)}</dd>
              </dl>
            ) : (
              <div className="small text-muted">Baseline not yet established — insufficient history. Rule-based detection still applies.</div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
