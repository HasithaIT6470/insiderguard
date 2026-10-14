import { useState } from 'react'
import { BarElement, CategoryScale, Chart as ChartJS, Legend, LinearScale, Tooltip } from 'chart.js'
import { Bar } from 'react-chartjs-2'
import { api } from '../api'
import { Status, fmt, useLoad } from '../components.jsx'

ChartJS.register(BarElement, CategoryScale, LinearScale, Tooltip, Legend)

export const MODE_LABEL = { rule_only: 'Rule-Only', anomaly_only: 'Anomaly-Only', hybrid: 'Hybrid' }
const pct = (x) => `${(x * 100).toFixed(1)}%`

export default function Evaluation() {
  const { data, loading, error, reload } = useLoad(() => api.evaluation().catch((e) => (e.status === 404 ? null : Promise.reject(e))))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const run = async () => {
    setBusy(true); setErr(null)
    try { await api.runEvaluation(); reload() } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const modes = data?.modes
  const chart = modes && {
    labels: ['Precision', 'Recall', 'F1', 'False-positive rate'],
    datasets: Object.entries(modes).map(([m, v], i) => ({
      label: MODE_LABEL[m], data: [v.precision, v.recall, v.f1, v.false_positive_rate],
      backgroundColor: ['#8d99ae', '#3a86ff', '#94bfff'][i],
    })),
  }

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <div>
          <h1 className="h3 mb-0">Detection evaluation</h1>
          <div className="small text-muted">Rule-Only vs Anomaly-Only vs Hybrid on the labelled synthetic data set</div>
        </div>
        <button className="btn btn-primary" onClick={run} disabled={busy}>{busy ? 'Running…' : 'Run evaluation'}</button>
      </div>
      {err && <div className="alert alert-danger">{err}</div>}
      <Status loading={loading} error={error}>
        {!data && <div className="alert alert-info">No evaluation has been run yet.</div>}
        {data && (
          <>
            <div className="small text-muted mb-2">
              Run {fmt(data.created_at)} by {data.run_by} · alert threshold {data.alert_threshold} · unit: {data.unit_of_analysis} ·{' '}
              {data.dataset.evaluated_user_days} user-days ({data.dataset.malicious_user_days} malicious), {data.dataset.scenarios} labelled scenarios.
              Results reflect synthetic data only and should not be read as real-world accuracy.
            </div>
            <div className="row g-3 mb-3">
              <div className="col-lg-7">
                <div className="card p-3 h-100">
                  <table className="table align-middle mb-0">
                    <thead><tr><th>Metric</th>{Object.keys(modes).map((m) => <th key={m} className="text-end">{MODE_LABEL[m]}</th>)}</tr></thead>
                    <tbody>
                      {[
                        ['Precision', 'precision', pct], ['Recall', 'recall', pct], ['F1-score', 'f1', (x) => x.toFixed(3)],
                        ['False-positive rate', 'false_positive_rate', pct], ['False-negative rate', 'false_negative_rate', pct],
                        ['Scenarios detected', null, null],
                        ['Median detection latency', 'median_detection_latency_minutes', (x) => (x == null ? '—' : `${x} min`)],
                        ['Mean detection latency', 'mean_detection_latency_minutes', (x) => (x == null ? '—' : `${x} min`)],
                      ].map(([label, key, f]) => (
                        <tr key={label}>
                          <td>{label}</td>
                          {Object.values(modes).map((v, i) => (
                            <td key={i} className="text-end">{key ? f(v[key]) : `${v.scenarios_detected} / ${v.scenarios_total}`}</td>
                          ))}
                        </tr>
                      ))}
                      <tr className="text-muted small"><td>TP / FP / FN / TN (user-days)</td>{Object.values(modes).map((v, i) => <td key={i} className="text-end">{v.tp} / {v.fp} / {v.fn} / {v.tn}</td>)}</tr>
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="col-lg-5">
                <div className="card p-3 h-100">
                  <Bar data={chart} options={{ scales: { y: { min: 0, max: 1 } }, plugins: { legend: { position: 'bottom' } } }} />
                </div>
              </div>
            </div>
            <div className="card p-3">
              <h2 className="h6">Detection by scenario type (detected / total · median latency)</h2>
              <table className="table table-sm mb-0">
                <thead><tr><th>Scenario</th>{Object.keys(modes).map((m) => <th key={m}>{MODE_LABEL[m]}</th>)}</tr></thead>
                <tbody>
                  {Object.entries(data.by_scenario_type).map(([t, v]) => (
                    <tr key={t}>
                      <td>{t.replaceAll('_', ' ')}</td>
                      {Object.keys(modes).map((m) => (
                        <td key={m} className={v[m].detected === 0 ? 'text-danger' : ''}>
                          {v[m].detected} / {v[m].total}{v[m].median_latency_minutes != null ? ` · ${v[m].median_latency_minutes} min` : ''}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Status>
    </>
  )
}
