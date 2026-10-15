import { useState } from 'react'
import { api } from './api'
import { CaseDialog } from './cases.jsx'

export const EMPLOYEE_FIELDS = [
  ['full_name', 'Full name', 160], ['email', 'Email', 254], ['phone', 'Phone', 20],
  ['job_title', 'Job title', 160], ['supervisor_name', 'Supervisor name', 160],
  ['supervisor_email', 'Supervisor email', 254], ['supervisor_phone', 'Supervisor phone', 20],
  ['employment_status', 'Employment status'], ['start_date', 'Start date'],
  ['location', 'Location', 160], ['contact_notes', 'Contact notes', 4000],
]
export const EMPLOYMENT_STATUSES = ['active', 'on_leave', 'contractor', 'offboarded']
export const DIRECTORY_TEMPLATE = 'user_id,full_name,email,phone,job_title,supervisor_name,supervisor_email,supervisor_phone,employment_status,start_date,location\r\n'
export const employmentLabel = value => value.replaceAll('_', ' ')

export function EmployeeForm({ profile, userId, department, departments = {}, suggestions = [], onComplete, onCancel }) {
  const [values, setValues] = useState(() => Object.fromEntries([['user_id', profile?.user_id || userId || ''], ...EMPLOYEE_FIELDS.map(([key]) => [key, profile?.[key] || (key === 'employment_status' ? 'active' : '')])]))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [confirm, setConfirm] = useState(false)
  const submit = async event => {
    event.preventDefault()
    setBusy(true); setError(null)
    try {
      const { user_id, ...body } = values
      if (profile) await api.updateEmployee(profile.user_id, body)
      else await api.createEmployee({ user_id, ...body })
      onComplete()
    } catch (e) { setError(e.message) } finally { setBusy(false); setConfirm(false) }
  }
  return <form onSubmit={submit} className="employee-form">
    <div className="row g-3">
      <label className="col-md-6">Log user ID<input className="form-control" value={values.user_id} required maxLength={64} pattern={'[A-Za-z0-9_.@\\-]+'} list="missing-profile-ids" readOnly={!!profile || !!userId} onChange={e => setValues({ ...values, user_id: e.target.value })} /><datalist id="missing-profile-ids">{suggestions.map(id => <option key={id} value={id} />)}</datalist></label>
      <label className="col-md-6">Department (from logs)<input className="form-control" readOnly value={department || departments[values.user_id.trim()] || 'No activity yet'} /></label>
      {EMPLOYEE_FIELDS.map(([key, label, max]) => <label key={key} className={key === 'contact_notes' ? 'col-12' : 'col-md-6'}>{label}
        {key === 'employment_status' ? <select className="form-select" value={values[key]} onChange={e => setValues({ ...values, [key]: e.target.value })}>{EMPLOYMENT_STATUSES.map(status => <option key={status} value={status}>{employmentLabel(status)}</option>)}</select>
          : key === 'contact_notes' ? <textarea className="form-control" maxLength={max} value={values[key]} onChange={e => setValues({ ...values, [key]: e.target.value })} />
            : <input className="form-control" type={key === 'start_date' ? 'date' : key.endsWith('email') ? 'email' : key.endsWith('phone') ? 'tel' : 'text'} maxLength={max} value={values[key]} onChange={e => setValues({ ...values, [key]: e.target.value })} />}
      </label>)}
    </div>
    {error && <p role="alert" className="alert alert-danger mt-3">{error}</p>}
    {profile && <label className="d-block mt-3"><input type="checkbox" checked={confirm} onChange={e => setConfirm(e.target.checked)} /> Confirm these changes to personal information</label>}
    <div className="d-flex justify-content-end gap-2 mt-3"><button type="button" className="btn btn-outline-secondary" disabled={busy} onClick={onCancel}>Cancel</button><button className="btn btn-primary" disabled={busy || (!!profile && !confirm)}>{busy ? 'Saving…' : profile ? 'Save changes' : 'Create profile'}</button></div>
  </form>
}

export function EmployeeDialog(props) {
  return <CaseDialog title={props.profile ? 'Edit employee profile' : 'Add employee profile'} onClose={props.onCancel}><EmployeeForm {...props} /></CaseDialog>
}
