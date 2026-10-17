import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Ban, ClipboardList, FileWarning, Plus, RefreshCw, Save, Search, ShieldCheck, SlidersHorizontal, Trash2, Upload, X } from 'lucide-react'
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
    <section className="card dash-panel">
      <div className="dash-panel-heading"><div><h2>Import telemetry</h2><p>CSV and JSON event files</p></div><Upload size={20} aria-hidden="true" /></div>
      <p className="small text-muted">
        Fields: timestamp, user_id, event_type (auth, file_access, download, denied_access, device, honeytoken), resource,
        resource_type, device_id, result, volume_mb. Synthetic data only.
      </p>
      <form className="telemetry-import-form" onSubmit={submit}>
        <div><label htmlFor="event-file" className="form-label small">Event file</label><input id="event-file" type="file" className="form-control form-control-sm" accept=".csv,.json" disabled={busy} onChange={(e) => { setFile(e.target.files[0]); setResult(null); setError(null) }} /></div>
        <button className="btn btn-sm btn-primary telemetry-command" disabled={!file || busy}><Upload size={16} aria-hidden="true" />{busy ? 'Importing...' : 'Import events'}</button>
      </form>
      {result && <div className={`alert ${result.rejected ? 'alert-warning' : 'alert-success'} mt-3 mb-0`} role="status"><strong>Import completed</strong><div>Accepted {result.accepted} events, rejected {result.rejected}. Scores updated for {result.affected_users.length} users.</div></div>}
      {error && <div className="alert alert-danger py-2 mt-3 mb-0" role="alert">{error.message}</div>}
      {errRows.length > 0 && (
        <details className="mt-2" open>
          <summary className="small">Validation errors ({errRows.length}{result?.errors_truncated ? '+' : ''})</summary>
          <ul className="small mb-0" style={{ maxHeight: 160, overflowY: 'auto' }}>
            {errRows.map((r) => <li key={r.row}>Row {r.row}: {r.errors.map((e) => `${e.field} – ${e.message}`).join('; ')}</li>)}
          </ul>
        </details>
      )}
    </section>
  )
}

function Honeytokens({ isAdmin }) {
  const { data, loading, error, reload } = useLoad(() => api.honeytokens())
  const [resource, setResource] = useState('')
  const [desc, setDesc] = useState('')
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [state, setState] = useState('')
  const tokens = data || []
  const visible = tokens.filter(h => (!state || (state === 'active' ? h.active : !h.active)) && `${h.resource} ${h.description || ''}`.toLowerCase().includes(query.trim().toLowerCase()))

  const create = async (e) => {
    e.preventDefault()
    setMsg(null)
    setBusy(true)
    try { await api.createHoneytoken(resource, desc || null); setResource(''); setDesc(''); reload() } catch (err) { setMsg(err.message) } finally { setBusy(false) }
  }
  const revoke = async (id) => { setBusy(true); setMsg(null); try { await api.revokeHoneytoken(id); reload() } catch (err) { setMsg(err.message) } finally { setBusy(false) } }

  return (
    <section className="card dash-panel">
      <div className="dash-panel-heading"><div><h2>Honeytoken registry</h2><p>Synthetic decoy resources and their activation state</p></div><button className="btn btn-sm btn-outline-secondary telemetry-icon-button" title="Refresh registry" aria-label="Refresh registry" disabled={loading || busy} onClick={reload}><RefreshCw size={16} /></button></div>
      {isAdmin && (
        <form className="telemetry-register" onSubmit={create}>
          <div><label htmlFor="decoy-resource" className="form-label small">Decoy resource</label><input id="decoy-resource" className="form-control form-control-sm" placeholder="/finance/decoy/payroll_master.xlsx" value={resource} disabled={busy} onChange={(e) => setResource(e.target.value)} required minLength={3} maxLength={512} /></div>
          <div><label htmlFor="decoy-description" className="form-label small">Description</label><input id="decoy-description" className="form-control form-control-sm" placeholder="Synthetic payroll decoy" value={desc} disabled={busy} onChange={(e) => setDesc(e.target.value)} maxLength={256} /></div>
          <button className="btn btn-sm btn-primary telemetry-command" disabled={busy}><Plus size={16} aria-hidden="true" />{busy ? 'Working...' : 'Register decoy'}</button>
        </form>
      )}
      {msg && <div className="alert alert-danger py-2" role="alert">{msg}</div>}
      <Status loading={loading} error={error}>
        <div className="telemetry-registry-summary"><span><strong>{tokens.filter(h => h.active).length}</strong> active decoys</span><span><strong>{tokens.filter(h => !h.active).length}</strong> revoked</span><span>{tokens.length} registered resources</span></div>
        <div className="dash-filters"><div className="dash-search"><Search size={17} aria-hidden="true" /><input className="form-control form-control-sm" aria-label="Search decoys" placeholder="Search resource or description" value={query} onChange={e => setQuery(e.target.value)} /></div><select className="form-select form-select-sm" aria-label="Decoy state" value={state} onChange={e => setState(e.target.value)}><option value="">All states</option><option value="active">Active</option><option value="revoked">Revoked</option></select>{(query || state) && <button className="btn btn-link btn-sm" onClick={() => { setQuery(''); setState('') }}>Clear filters</button>}</div>
        <div className="table-responsive"><table className="table align-middle mb-0">
          <thead><tr><th scope="col">Resource</th><th scope="col">Description</th><th scope="col">State</th><th scope="col">Created (UTC)</th>{isAdmin && <th scope="col"><span className="visually-hidden">Actions</span></th>}</tr></thead>
          <tbody>
            {visible.map((h) => (
              <tr key={h.id}>
                <td className="mono telemetry-resource">{h.resource}</td><td>{h.description || 'No description'}</td>
                <td><span className={`badge ${h.active ? 'bg-success' : 'bg-secondary'}`}>{h.active ? 'active' : 'revoked'}</span></td>
                <td className="small">{fmt(h.created_at)}</td>
                {isAdmin && <td className="text-end">{h.active && <button className="btn btn-sm btn-outline-danger telemetry-command" disabled={busy} onClick={() => revoke(h.id)} aria-label={`Revoke ${h.resource}`}><Ban size={14} aria-hidden="true" />Revoke</button>}</td>}
              </tr>
            ))}
          </tbody>
        </table></div>
        {!visible.length && <div className="dash-empty">{tokens.length ? 'No decoys match these filters.' : 'No decoy resources registered.'}</div>}
      </Status>
    </section>
  )
}

function AddRuleDialog({ onClose, onAdded }) {
  const dialog = useRef(null)
  const [form, setForm] = useState({ key: '', description: '', value: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  useEffect(() => {
    const element = dialog.current
    const previousFocus = document.activeElement
    element.showModal()
    return () => { element.close(); previousFocus?.focus() }
  }, [])
  const submit = async event => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.createRule({ key: form.key.trim(), description: form.description.trim(), value: Number(form.value) })
      onAdded()
      onClose()
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }
  return createPortal(<dialog ref={dialog} className="rule-dialog" aria-labelledby="add-rule-title" onCancel={event => { event.preventDefault(); if (!busy) onClose() }}>
    <div className="dash-panel-heading"><div><h2 id="add-rule-title">Add detection rule</h2><p>Custom numeric parameter</p></div><button className="btn btn-sm btn-outline-secondary telemetry-icon-button" aria-label="Close dialog" title="Close dialog" disabled={busy} onClick={onClose}><X size={17} /></button></div>
    <form onSubmit={submit}>
      <label className="form-label" htmlFor="new-rule-parameter">Parameter</label>
      <input id="new-rule-parameter" className="form-control mb-3" autoFocus required maxLength={48} pattern="[a-z][a-z0-9_]*" placeholder="custom_threshold" value={form.key} disabled={busy} onChange={e => setForm({ ...form, key: e.target.value })} />
      <label className="form-label" htmlFor="new-rule-description">Description</label>
      <textarea id="new-rule-description" className="form-control mb-3" required maxLength={256} rows={3} value={form.description} disabled={busy} onChange={e => setForm({ ...form, description: e.target.value })} />
      <label className="form-label" htmlFor="new-rule-value">Value</label>
      <input id="new-rule-value" className="form-control mb-3" type="number" required min={0} max={1000000} step="any" value={form.value} disabled={busy} onChange={e => setForm({ ...form, value: e.target.value })} />
      <p className="small text-muted">Custom parameters are stored for configuration. They do not trigger alerts until supported by detection logic.</p>
      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      <div className="rule-dialog-actions"><button type="button" className="btn btn-sm btn-outline-secondary" disabled={busy} onClick={onClose}>Cancel</button><button className="btn btn-sm btn-primary telemetry-command" disabled={busy}><Plus size={15} aria-hidden="true" />{busy ? 'Adding...' : 'Add rule'}</button></div>
    </form>
  </dialog>, document.body)
}

function Rules({ isAdmin }) {
  const { data, loading, error, reload } = useLoad(() => api.rules())
  const [edits, setEdits] = useState({})
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [adding, setAdding] = useState(false)
  const remove = async rule => {
    if (!isAdmin || !window.confirm(`Remove parameter "${rule.key}"?`)) return
    setBusy(true)
    setMsg(null)
    try {
      await api.deleteRule(rule.key)
      setEdits(previous => { const next = { ...previous }; delete next[rule.key]; return next })
      setMsg({ ok: true, text: `Removed parameter ${rule.key}.` })
      reload()
    } catch (err) { setMsg({ ok: false, text: err.message }) }
    finally { setBusy(false) }
  }

  const save = async (event) => {
    event.preventDefault()
    if (!isAdmin) return
    if (Object.values(edits).some(value => value === '' || !Number.isFinite(Number(value)) || Number(value) < 0 || Number(value) > 1000000)) {
      setMsg({ ok: false, text: 'Rule values must be numbers between 0 and 1,000,000.' })
      setQuery('')
      return
    }
    setBusy(true); setMsg(null)
    try {
      const r = await api.updateRules(Object.fromEntries(Object.entries(edits).map(([k, v]) => [k, Number(v)])))
      setMsg({ ok: true, text: `Updated ${Object.keys(r.changed).length} parameter(s).` })
      setEdits({}); reload()
    } catch (err) { setMsg({ ok: false, text: err.message }) } finally { setBusy(false) }
  }
  return (
    <section className="card dash-panel">
      <div className="dash-panel-heading"><div><h2>Detection rules</h2><p>Built-in engine settings and custom numeric parameters</p></div>{isAdmin ? <button className="btn btn-sm btn-primary telemetry-command" disabled={busy || loading || Object.keys(edits).length > 0} onClick={() => setAdding(true)}><Plus size={16} aria-hidden="true" />Add rule</button> : <span className="dash-panel-meta">Read-only</span>}</div>
      {isAdmin && adding && <AddRuleDialog onClose={() => setAdding(false)} onAdded={() => { setMsg({ ok: true, text: 'Custom parameter added.' }); reload() }} />}
      {msg && <div className={`alert py-2 alert-${msg.ok ? 'success' : 'danger'}`} role={msg.ok ? 'status' : 'alert'}>{msg.text}</div>}
      <Status loading={loading} error={error}>
        <div className="dash-filters"><div className="dash-search"><Search size={17} aria-hidden="true" /><input className="form-control form-control-sm" value={query} onChange={e => setQuery(e.target.value)} aria-label="Search rules" placeholder="Search parameter or description" /></div></div>
        <form onSubmit={save} noValidate>
        <div className="telemetry-rules-table">
          <table className="table table-sm align-middle mb-0">
            <thead><tr><th>Parameter</th><th>Description</th><th style={{ width: 110 }}>Value</th>{isAdmin && <th><span className="visually-hidden">Actions</span></th>}</tr></thead>
            <tbody>
              {(data || []).map((r) => (
                <tr key={r.key} hidden={!`${r.key} ${r.description}`.toLowerCase().includes(query.trim().toLowerCase())}>
                  <td className="mono">{r.key}</td><td className="small">{r.description}{r.built_in === false && <div className="text-muted mt-1">Custom parameter; not used by the current detector</div>}</td>
                  <td>
                    {isAdmin ? <input type="number" step="any" min="0" max="1000000" required className="form-control form-control-sm" disabled={busy} aria-label={r.key}
                      value={edits[r.key] ?? r.value} onChange={(e) => { const value = e.target.value; setEdits(previous => { const next = { ...previous }; if (value !== '' && Number(value) === r.value) delete next[r.key]; else next[r.key] = value; return next }) }} /> : <span>{r.value}</span>}
                  </td>
                  {isAdmin && <td><button type="button" className="btn btn-sm btn-outline-danger telemetry-icon-button" disabled={busy || r.built_in !== false} aria-label={`Remove ${r.key}`} title={r.built_in !== false ? 'Built-in engine parameters cannot be removed' : `Remove ${r.key}`} onClick={() => remove(r)}><Trash2 size={16} /></button></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!(data || []).some(r => `${r.key} ${r.description}`.toLowerCase().includes(query.trim().toLowerCase())) && <div className="dash-empty">No rules match your search.</div>}
        {isAdmin && <div className="telemetry-rule-actions"><span>{Object.keys(edits).length} unsaved changes</span><div><button type="button" className="btn btn-sm btn-outline-secondary" disabled={!Object.keys(edits).length || busy} onClick={() => setEdits({})}>Discard</button><button className="btn btn-sm btn-primary telemetry-command" disabled={!Object.keys(edits).length || busy}><Save size={15} aria-hidden="true" />{busy ? 'Saving...' : 'Save changes'}</button></div></div>}
        </form>
      </Status>
    </section>
  )
}

function AdminTables() {
  const errs = useLoad(() => api.parseErrors())
  const [draft, setDraft] = useState({ actor: '', start: '', end: '' })
  const [filters, setFilters] = useState({})
  const [filterError, setFilterError] = useState('')
  const audit = useLoad(() => api.audit(filters), [filters])
  const applyFilters = event => {
    event.preventDefault()
    if (draft.start && draft.end && draft.start > draft.end) {
      setFilterError('Start date/time must be before or equal to end date/time.')
      return
    }
    setFilterError('')
    setFilters(Object.fromEntries(Object.entries(draft).filter(([, value]) => value.trim()).map(([key, value]) => [key, key === 'actor' ? value.trim() : `${value}Z`])))
  }
  return (
    <div className="telemetry-logs">
        <section className="card dash-panel">
          <div className="dash-panel-heading"><div><h2>Parsing errors</h2><p>Latest rejected telemetry records</p></div><button className="btn btn-sm btn-outline-secondary telemetry-icon-button" aria-label="Refresh parsing errors" title="Refresh parsing errors" onClick={errs.reload} disabled={errs.loading}><RefreshCw size={16} /></button></div>
          <Status loading={errs.loading} error={errs.error}>
            <div style={{ maxHeight: 280, overflowY: 'auto' }}>
              <table className="table table-sm mb-0"><thead><tr><th scope="col">Recorded (UTC)</th><th scope="col">Validation details</th></tr></thead><tbody>
                {(errs.data || []).map((e) => <tr key={e.id}><td className="small text-nowrap">{fmt(e.created_at)}</td><td className="small">row {e.row}: {e.errors.map((x) => `${x.field} ${x.message}`).join('; ')}</td></tr>)}
                {errs.data?.length === 0 && <tr><td colSpan={2} className="text-muted">None logged.</td></tr>}
              </tbody></table>
            </div>
          </Status>
        </section>
        <section className="card dash-panel">
          <div className="dash-panel-heading"><div><h2>Audit log</h2><p>Latest recorded administrator and analyst activity</p></div><button className="btn btn-sm btn-outline-secondary telemetry-icon-button" aria-label="Refresh audit log" title="Refresh audit log" onClick={audit.reload} disabled={audit.loading}><RefreshCw size={16} /></button></div>
          <form className="d-flex flex-wrap align-items-end gap-2 mb-3" onSubmit={applyFilters}>
            <label className="small">Actor (exact username)<input className="form-control form-control-sm" value={draft.actor} onChange={e => setDraft({ ...draft, actor: e.target.value })} /></label>
            <label className="small">From (UTC)<input type="datetime-local" step="1" className="form-control form-control-sm" value={draft.start} onChange={e => setDraft({ ...draft, start: e.target.value })} /></label>
            <label className="small">To (UTC)<input type="datetime-local" step="1" className="form-control form-control-sm" value={draft.end} onChange={e => setDraft({ ...draft, end: e.target.value })} /></label>
            <button className="btn btn-sm btn-primary" type="submit">Apply audit filters</button>
            <button className="btn btn-sm btn-outline-secondary" type="button" onClick={() => { setDraft({ actor: '', start: '', end: '' }); setFilters({}); setFilterError('') }}>Clear audit filters</button>
          </form>
          {filterError && <div role="alert" className="alert alert-danger">{filterError}</div>}
          <p className="small text-muted">Latest 200 matching entries. Date/time boundaries are inclusive and use UTC.</p>
          <Status loading={audit.loading} error={audit.error}>
            <div style={{ maxHeight: 280, overflowY: 'auto' }}>
              <table className="table table-sm mb-0"><thead><tr><th scope="col">Recorded (UTC)</th><th scope="col">Actor</th><th scope="col">Action / target</th></tr></thead><tbody>
                {(audit.data || []).map((a) => <tr key={a.id}><td className="small text-nowrap">{fmt(a.timestamp)}</td><td>{a.actor}</td><td className="small">{a.action}{a.target ? ` / ${a.target}` : ''}</td></tr>)}
                {audit.data?.length === 0 && <tr><td colSpan={3} className="text-muted">No activity matches these filters.</td></tr>}
              </tbody></table>
            </div>
          </Status>
        </section>
    </div>
  )
}

export default function Telemetry() {
  const { auth } = useAuth()
  const isAdmin = auth.role === 'admin'
  const [key, setKey] = useState(0)
  const [tab, setTab] = useState('registry')
  const tabs = [
    ['registry', 'Honeytoken registry', ShieldCheck],
    ...(isAdmin ? [['import', 'Telemetry import', Upload]] : []),
    ['rules', 'Detection rules', SlidersHorizontal],
    ...(isAdmin ? [['logs', 'Admin logs', ClipboardList]] : []),
  ]
  const activeTab = tabs.some(([id]) => id === tab) ? tab : 'registry'
  return (
    <div className="dash-page telemetry-page">
      <header className="dash-header"><div><h1>Telemetry &amp; honeytokens</h1><p className="text-muted mb-0">Event ingestion, decoy resources and detection configuration</p></div><span className="telemetry-access"><ShieldCheck size={16} aria-hidden="true" />{isAdmin ? 'Administrator access' : 'Read-only access'}</span></header>
      {!isAdmin && <div className="alert alert-info py-2">Read-only view. Importing events, registering decoys and editing rules require the administrator role.</div>}
      <div className="telemetry-tabs" role="tablist" aria-label="Telemetry sections" onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
        event.preventDefault()
        const index = tabs.findIndex(([id]) => id === activeTab)
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length
        setTab(tabs[next][0])
        event.currentTarget.querySelectorAll('[role="tab"]')[next].focus()
      }}>{tabs.map(([id, label, Icon]) => <button key={id} id={`telemetry-tab-${id}`} role="tab" aria-selected={activeTab === id} aria-controls={`telemetry-panel-${id}`} tabIndex={activeTab === id ? 0 : -1} onClick={() => setTab(id)}><Icon size={17} aria-hidden="true" />{label}</button>)}</div>
      <div role="tabpanel" id="telemetry-panel-registry" aria-labelledby="telemetry-tab-registry" hidden={activeTab !== 'registry'}><Honeytokens isAdmin={isAdmin} key={`h${key}`} /></div>
      {isAdmin && <div role="tabpanel" id="telemetry-panel-import" aria-labelledby="telemetry-tab-import" hidden={activeTab !== 'import'}><ImportCard onDone={() => setKey(k => k + 1)} /></div>}
      <div role="tabpanel" id="telemetry-panel-rules" aria-labelledby="telemetry-tab-rules" hidden={activeTab !== 'rules'}><Rules isAdmin={isAdmin} /></div>
      {isAdmin && <div role="tabpanel" id="telemetry-panel-logs" aria-labelledby="telemetry-tab-logs" hidden={activeTab !== 'logs'}><AdminTables key={`a${key}`} /></div>}
      <p className="dash-disclaimer"><FileWarning size={15} aria-hidden="true" />Synthetic data only. Access to an active decoy raises a highest-weight detection indicator.</p>
    </div>
  )
}
