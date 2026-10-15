import { useState } from 'react'
import { Activity, FlaskConical, Play, RefreshCw, ShieldAlert, Users } from 'lucide-react'
import { BarElement, CategoryScale, Chart as ChartJS, Legend, LinearScale, Tooltip } from 'chart.js'
import { Bar } from 'react-chartjs-2'
import { api } from '../api'
import { useAuth } from '../App.jsx'
import { Status, fmt, useLoad } from '../components.jsx'

ChartJS.register(BarElement, CategoryScale, LinearScale, Tooltip, Legend)
export const MODE_LABEL = { rule_only: 'Rule-Only', anomaly_only: 'Anomaly-Only', hybrid: 'Hybrid' }
const MODE_COLOR = { rule_only: '#8290a5', anomaly_only: '#2563eb', hybrid: '#249e83' }
const pct = value => value == null ? 'Unavailable' : `${(value * 100).toFixed(1)}%`
const latency = value => value == null ? 'Not detected' : `${value} min`
const number = value => Number(value || 0).toLocaleString()
const METRICS = [
  ['Precision', 'precision', pct], ['Recall', 'recall', pct],
  ['F1-score', 'f1', value => value == null ? 'Unavailable' : value.toFixed(3)],
  ['False-positive rate', 'false_positive_rate', pct], ['False-negative rate', 'false_negative_rate', pct],
  ['Scenarios detected', null, value => `${value.scenarios_detected} / ${value.scenarios_total}`],
  ['Median detection latency', 'median_detection_latency_minutes', latency],
  ['Mean detection latency', 'mean_detection_latency_minutes', latency],
]

export default function Evaluation() {
  const { auth } = useAuth() || {}
  const { data, loading, error, reload } = useLoad(() => api.evaluation().catch(e => { if (e.status === 404) return null; throw e }))
  const [busy, setBusy] = useState(false)
  const [runError, setRunError] = useState(null)
  const [search, setSearch] = useState('')
  const run = async () => {
    setBusy(true)
    setRunError(null)
    try { await api.runEvaluation(); reload() }
    catch (e) { setRunError(e.message) }
    finally { setBusy(false) }
  }
  const modes = Object.keys(MODE_LABEL).filter(mode => data?.modes?.[mode])
  const chart = metrics => ({ labels: metrics.map(([label]) => label), datasets: modes.map(mode => ({ label: MODE_LABEL[mode], data: metrics.map(([, key]) => data.modes[mode][key] == null ? null : data.modes[mode][key] * 100), backgroundColor: MODE_COLOR[mode], borderRadius: 3, maxBarThickness: 36 })) })
  const chartOptions = { maintainAspectRatio: false, scales: { x: { grid: { display: false } }, y: { min: 0, max: 100, ticks: { callback: value => `${value}%` } } }, plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, padding: 18 } }, tooltip: { callbacks: { label: context => `${context.dataset.label}: ${context.parsed.y.toFixed(1)}%` } } } }
  const scenarios = Object.entries(data?.by_scenario_type || {}).filter(([type]) => type.replaceAll('_', ' ').toLowerCase().includes(search.trim().toLowerCase()))

  return <div className="dash-page evaluation-page">
    <header className="dash-header">
      <div><h1>Detection evaluation</h1><p className="text-muted mb-0">Rule-Only, Anomaly-Only and Hybrid detection comparison</p></div>
      <div className="evaluation-actions">
        <button className="btn btn-outline-light btn-sm evaluation-icon-button" title="Refresh results" aria-label="Refresh results" disabled={busy || loading} onClick={reload}><RefreshCw size={16} /></button>
        {auth?.role === 'admin' ? <button className="btn btn-primary btn-sm" onClick={run} disabled={busy || loading}><Play size={15} aria-hidden="true" />{busy ? 'Running evaluation...' : 'Run evaluation'}</button>
          : <span className="small text-muted">Only administrators can run the evaluation</span>}
      </div>
    </header>
    {runError && <div className="alert alert-danger mb-0" role="alert">{runError}</div>}
    {busy && <p className="text-muted mb-0" role="status">Evaluating the labelled dataset...</p>}
    <Status loading={loading} error={error}>
      {!data && <section className="card dash-panel reports-empty"><FlaskConical size={36} aria-hidden="true" /><h2>No evaluation results yet</h2><p>Run an evaluation against the labelled synthetic dataset to compare detection performance.</p></section>}
      {data && <>
        <section className="evaluation-run-meta" aria-label="Latest evaluation run">
          <span>Last run<strong>{fmt(data.created_at)}</strong></span><span>Run by<strong>{data.run_by || 'Unavailable'}</strong></span><span>Alert threshold<strong>{data.alert_threshold} / 100</strong></span>
        </section>
        <section className="dash-metrics" aria-label="Evaluation dataset">
          {[
            ['Evaluated users', data.dataset.users_evaluated, 'Profiles included in evaluation', Users],
            ['Evaluated user-days', data.dataset.evaluated_user_days, 'After baseline learning windows', Activity],
            ['Malicious user-days', data.dataset.malicious_user_days, 'Labelled positive samples', ShieldAlert],
            ['Labelled scenarios', data.dataset.scenarios, 'Synthetic attack scenarios', FlaskConical],
          ].map(([label, value, detail, Icon]) => <article className="card dash-metric" key={label}><div className="dash-metric-label"><span>{label}</span><Icon size={19} aria-hidden="true" /></div><strong className="dash-metric-value">{number(value)}</strong><span className="text-muted small">{detail}</span></article>)}
        </section>
        <div className="evaluation-charts">
          <section className="card dash-panel"><div className="dash-panel-heading"><div><h2>Detection performance</h2><p>Precision, recall and F1-score</p></div><span className="evaluation-direction">Higher is better</span></div><div className="evaluation-chart"><Bar data={chart([['Precision', 'precision'], ['Recall', 'recall'], ['F1-score', 'f1']])} options={chartOptions} role="img" aria-label="Precision, recall and F1-score comparison" /></div></section>
          <section className="card dash-panel"><div className="dash-panel-heading"><div><h2>Error rates</h2><p>False positives and missed detections</p></div><span className="evaluation-direction">Lower is better</span></div><div className="evaluation-chart"><Bar data={chart([['False-positive rate', 'false_positive_rate'], ['False-negative rate', 'false_negative_rate']])} options={chartOptions} role="img" aria-label="False-positive and false-negative rate comparison" /></div></section>
        </div>
        <section className="card dash-panel">
          <div className="dash-panel-heading"><div><h2>Metrics comparison</h2><p>Unit of analysis: {data.unit_of_analysis}</p></div></div>
          <div className="table-responsive"><table className="table align-middle mb-0 evaluation-table">
            <thead><tr><th scope="col">Metric</th>{modes.map(mode => <th scope="col" key={mode} className="text-end"><span className="evaluation-mode"><i style={{ background: MODE_COLOR[mode] }} />{MODE_LABEL[mode]}</span></th>)}</tr></thead>
            <tbody>{METRICS.map(([label, key, format]) => <tr key={label}><th scope="row">{label}</th>{modes.map(mode => <td className="text-end" key={mode}>{format(key ? data.modes[mode][key] : data.modes[mode])}</td>)}</tr>)}</tbody>
          </table></div>
        </section>
        <section className="card dash-panel">
          <div className="dash-panel-heading"><div><h2>Classification outcomes</h2><p>Counts by evaluated user-day</p></div></div>
          <div className="table-responsive"><table className="table align-middle mb-0 evaluation-table"><thead><tr><th scope="col">Detection mode</th><th scope="col">True positives</th><th scope="col">False positives</th><th scope="col">False negatives</th><th scope="col">True negatives</th></tr></thead><tbody>{modes.map(mode => <tr key={mode}><th scope="row">{MODE_LABEL[mode]}</th>{['tp', 'fp', 'fn', 'tn'].map(key => <td key={key}>{number(data.modes[mode][key])}</td>)}</tr>)}</tbody></table></div>
        </section>
        <section className="card dash-panel">
          <div className="dash-panel-heading"><div><h2>Scenario results</h2><p>Detected / total scenarios, with median detection latency</p></div><input className="form-control form-control-sm evaluation-search" aria-label="Search scenario types" placeholder="Search scenario types" value={search} onChange={e => setSearch(e.target.value)} /></div>
          <div className="table-responsive"><table className="table align-middle mb-0 evaluation-table"><thead><tr><th scope="col">Scenario type</th>{modes.map(mode => <th key={mode} scope="col">{MODE_LABEL[mode]}</th>)}</tr></thead><tbody>{scenarios.map(([type, results]) => <tr key={type}><th className="evaluation-scenario" scope="row">{type.replaceAll('_', ' ')}</th>{modes.map(mode => { const result = results[mode]; return <td key={mode}>{result ? <><strong className={result.detected === 0 ? 'text-danger' : ''}>{result.detected} / {result.total}</strong><span className="evaluation-latency">{latency(result.median_latency_minutes)}</span></> : 'Unavailable'}</td> })}</tr>)}</tbody></table></div>
          {!scenarios.length && <div className="dash-empty">{search ? 'No scenario types match your search.' : 'No scenario results available.'}</div>}
        </section>
        <p className="dash-disclaimer"><ShieldAlert size={15} aria-hidden="true" />Results reflect synthetic data only and should not be read as real-world accuracy.</p>
      </>}
    </Status>
  </div>
}
