import { useState } from 'react'
import { api } from '../api'
import { useAuth } from '../App.jsx'
import { Status, fmt, useLoad } from '../components.jsx'

function ImportCard({ onDone }) {
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (!file) return
    setBusy(true); setError(null); setResult(null)
    try {
      setResult(await api.importEvents(file))
      onDone()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }
  const errRows = error?.detail?.errors || result?.errors || []
  return (
    <div className="card p-3 mb-3">
      <h2 className="h6">Import events (CSV / JSON)</h2>
      <p className="small text-muted">
        Fields: timestamp, user_id, event_type (auth, file_access, download, denied_access, device, honeytoken), resource,
        resource_type, device_id, result, volume_mb. Synthetic data only.
      </p>
      <form className="d-flex gap-2" onSubmit={submit}>
        <input type="file" className="form-control form-control-sm" accept=".csv,.json" onChange={(e) => setFile(e.target.files[0])} aria-label="Event file" />
        <button className="btn btn-sm btn-primary" disabled={!file || busy}>{busy ? 'Importing…' : 'Import'}</button>
      </form>
      {result && <div className="alert alert-success py-2 mt-2 mb-0">Accepted {result.accepted} events, rejected {result.rejected}. Scores updated for {result.affected_users.length} users.</div>}
      {error && <div className="alert alert-danger py-2 mt-2 mb-0">{error.message}</div>}
      {errRows.length > 0 && (
        <details className="mt-2" open>
          <summary className="small">Validation errors ({errRows.length}{result?.errors_truncated ? '+' : ''})</summary>
          <ul className="small mb-0" style={{ maxHeight: 160, overflowY: 'auto' }}>
            {errRows.map((r) => <li key={r.row}>Row {r.row}: {r.errors.map((e) => `${e.field} – ${e.message}`).join('; ')}</li>)}
          </ul>
        </details>
      )}
    </div>
  )
}

function Honeytokens({ isAdmin }) {
  const { data, loading, error, reload } = useLoad(() => api.honeytokens())
  const [resource, setResource] = useState('')
  const [desc, setDesc] = useState('')
  const [msg, setMsg] = useState(null)

  const create = async (e) => {
    e.preventDefault()
    setMsg(null)
    try { await api.createHoneytoken(resource, desc || null); setResource(''); setDesc(''); reload() } catch (err) { setMsg(err.message) }
  }
  const revoke = async (id) => { try { await api.revokeHoneytoken(id); reload() } catch (err) { setMsg(err.message) } }

  return (
    <div className="card p-3 mb-3">
      <h2 className="h6">Honeytoken / decoy registry</h2>
      <p className="small text-muted">Decoys must contain synthetic data only. Any access to an active decoy raises a highest-weight indicator.</p>
      {isAdmin && (
        <form className="row g-2 mb-3" onSubmit={create}>
          <div className="col-md-6"><input className="form-control form-control-sm" placeholder="/finance/decoy/payroll_master.xlsx" value={resource} onChange={(e) => setResource(e.target.value)} required minLength={3} maxLength={512} aria-label="Decoy resource" /></div>
          <div className="col-md-4"><input className="form-control form-control-sm" placeholder="Description" value={desc} onChange={(e) => setDesc(e.target.value)} maxLength={256} aria-label="Description" /></div>
          <div className="col-md-2"><button className="btn btn-sm btn-primary w-100">Register</button></div>
        </form>
      )}
      {msg && <div className="alert alert-danger py-2">{msg}</div>}
      <Status loading={loading} error={error}>
        <table className="table table-sm align-middle mb-0">
          <thead><tr><th>Resource</th><th>Description</th><th>State</th><th>Created</th>{isAdmin && <th />}</tr></thead>
          <tbody>
            {(data || []).map((h) => (
              <tr key={h.id}>
                <td className="mono">{h.resource}</td><td>{h.description}</td>
                <td><span className={`badge ${h.active ? 'bg-success' : 'bg-secondary'}`}>{h.active ? 'active' : 'revoked'}</span></td>
                <td className="small">{fmt(h.created_at)}</td>
                {isAdmin && <td className="text-end">{h.active && <button className="btn btn-sm btn-outline-danger" onClick={() => revoke(h.id)}>Revoke</button>}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </Status>
    </div>
  )
}

function Rules({ isAdmin }) {
  const { data, loading, error, reload } = useLoad(() => api.rules())
  const [edits, setEdits] = useState({})
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true); setMsg(null)
    try {
      const r = await api.updateRules(Object.fromEntries(Object.entries(edits).map(([k, v]) => [k, Number(v)])))
      setMsg({ ok: true, text: `Updated ${Object.keys(r.changed).length} rule(s); all users re-scored.` })
      setEdits({}); reload()
    } catch (err) { setMsg({ ok: false, text: err.message }) } finally { setBusy(false) }
  }
  return (
    <div className="card p-3 mb-3">
      <div className="d-flex justify-content-between">
        <h2 className="h6">Rule thresholds &amp; weights</h2>
        {isAdmin && <button className="btn btn-sm btn-primary" disabled={!Object.keys(edits).length || busy} onClick={save}>{busy ? 'Saving…' : 'Save changes'}</button>}
      </div>
      {msg && <div className={`alert py-2 alert-${msg.ok ? 'success' : 'danger'}`}>{msg.text}</div>}
      <Status loading={loading} error={error}>
        <div style={{ maxHeight: 360, overflowY: 'auto' }}>
          <table className="table table-sm align-middle mb-0">
            <thead><tr><th>Parameter</th><th>Description</th><th style={{ width: 110 }}>Value</th></tr></thead>
            <tbody>
              {(data || []).map((r) => (
                <tr key={r.key}>
                  <td className="mono">{r.key}</td><td className="small">{r.description}</td>
                  <td>
                    <input type="number" step="any" min="0" className="form-control form-control-sm" disabled={!isAdmin} aria-label={r.key}
                      value={edits[r.key] ?? r.value} onChange={(e) => setEdits({ ...edits, [r.key]: e.target.value })} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Status>
    </div>
  )
}

function AdminTables() {
  const errs = useLoad(() => api.parseErrors())
  const audit = useLoad(() => api.audit())
  return (
    <div className="row g-3">
      <div className="col-lg-6">
        <div className="card p-3">
          <h2 className="h6">Parsing errors (administrator)</h2>
          <Status loading={errs.loading} error={errs.error}>
            <div style={{ maxHeight: 280, overflowY: 'auto' }}>
              <table className="table table-sm mb-0"><tbody>
                {(errs.data || []).map((e) => <tr key={e.id}><td className="small text-nowrap">{fmt(e.created_at)}</td><td className="small">row {e.row}: {e.errors.map((x) => `${x.field} ${x.message}`).join('; ')}</td></tr>)}
                {errs.data?.length === 0 && <tr><td className="text-muted">None logged.</td></tr>}
              </tbody></table>
            </div>
          </Status>
        </div>
      </div>
      <div className="col-lg-6">
        <div className="card p-3">
          <h2 className="h6">Audit log</h2>
          <Status loading={audit.loading} error={audit.error}>
            <div style={{ maxHeight: 280, overflowY: 'auto' }}>
              <table className="table table-sm mb-0"><tbody>
                {(audit.data || []).map((a) => <tr key={a.id}><td className="small text-nowrap">{fmt(a.timestamp)}</td><td className="small">{a.actor} · {a.action}{a.target ? ` · ${a.target}` : ''}</td></tr>)}
              </tbody></table>
            </div>
          </Status>
        </div>
      </div>
    </div>
  )
}

export default function Telemetry() {
  const { auth } = useAuth()
  const isAdmin = auth.role === 'admin'
  const [key, setKey] = useState(0)
  return (
    <>
      <h1 className="h3 mb-3">Telemetry &amp; honeytoken management</h1>
      {!isAdmin && <div className="alert alert-info py-2">Read-only view. Importing events, registering decoys and editing rules require the administrator role.</div>}
      <div className="row g-3">
        <div className="col-lg-6">
          {isAdmin && <ImportCard onDone={() => setKey((k) => k + 1)} />}
          <Honeytokens isAdmin={isAdmin} key={`h${key}`} />
        </div>
        <div className="col-lg-6"><Rules isAdmin={isAdmin} /></div>
      </div>
      {isAdmin && <AdminTables key={`a${key}`} />}
    </>
  )
}
