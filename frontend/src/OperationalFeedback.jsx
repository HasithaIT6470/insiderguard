import { ArcElement, BarElement, CategoryScale, Chart as ChartJS, Legend, LinearScale, Tooltip } from 'chart.js'
import { Bar, Doughnut } from 'react-chartjs-2'
import { api } from './api'
import { OUTCOME_COLOR, OUTCOME_LABEL, Status, useLoad } from './components.jsx'

ChartJS.register(ArcElement, BarElement, CategoryScale, LinearScale, Tooltip, Legend)
const precision = value => value == null ? 'Unavailable' : `${(value * 100).toFixed(1)}%`
const NOTE = 'Recall and F1 cannot be derived from analyst verdicts because missed attacks are never reviewed. Recall/F1 are only available from the labelled lab evaluation.'

export default function OperationalFeedback() {
  const query = useLoad(() => api.evaluationFeedback())
  const data = query.data
  const fp = data?.top_indicators?.false_positive || []
  const benign = data?.top_indicators?.benign_explained || []
  const names = [...new Set([...fp, ...benign].map(i => i.name))]
    .sort((a, b) => [...fp, ...benign].filter(i => i.name === b).reduce((s, i) => s + i.count, 0)
      - [...fp, ...benign].filter(i => i.name === a).reduce((s, i) => s + i.count, 0) || a.localeCompare(b)).slice(0, 10)
  return <section className="card dash-panel operational-feedback" aria-labelledby="operational-title">
    <div className="dash-panel-heading"><div><h2 id="operational-title">Operational feedback (analyst verdicts)</h2><p>Reviewed cases, separate from the labelled lab results</p></div>
      <button className="btn btn-sm btn-outline-secondary" aria-label="Refresh operational feedback" disabled={query.loading} onClick={query.reload}>Refresh</button>
    </div>
    <Status loading={query.loading} error={query.error}>
      {!data?.closed_with_outcome ? <div className="dash-empty"><h3 className="h6">No analyst verdicts yet</h3><p>Close a case with an outcome and a closing note to see operational feedback here.</p>
        {!!data?.legacy_closed && <p>{data.legacy_closed} closed cases have no recorded outcome.</p>}
      </div> : <>
        <div className="dash-metrics" aria-label="Operational feedback summary">
          <article className="card dash-metric"><span>Alert precision</span><strong className="dash-metric-value">{precision(data.alert_precision)}</strong><span className="small text-muted" title={data.precision_formula}>True positives / all closed cases with an outcome</span></article>
          <article className="card dash-metric"><span>Closed with outcome</span><strong className="dash-metric-value">{data.closed_with_outcome}</strong></article>
          <article className="card dash-metric"><span>Closed without outcome</span><strong className="dash-metric-value">{data.legacy_closed}</strong></article>
          <article className="card dash-metric"><span>Median time to close</span><strong className="dash-metric-value">{data.median_time_to_close_hours == null ? 'Unavailable' : `${data.median_time_to_close_hours} h`}</strong><span className="small text-muted">From assignment to resolution; {data.time_to_close_sample_count || 0} measured cases</span></article>
        </div>
        <div className="evaluation-charts">
          <div><h3 className="h6">Current case outcomes</h3><div className="evaluation-chart"><Doughnut role="img" aria-label="Analyst verdict outcomes"
            data={{ labels: Object.values(OUTCOME_LABEL), datasets: [{ data: Object.keys(OUTCOME_LABEL).map(o => data.counts_by_outcome?.[o] || 0), backgroundColor: Object.keys(OUTCOME_LABEL).map(o => OUTCOME_COLOR[o]), borderWidth: 2 }] }}
            options={{ maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }} /></div></div>
          <div><h3 className="h6">Indicators in false positives and benign cases</h3><div className="evaluation-chart">{names.length ? <Bar role="img" aria-label="Indicators in false positives"
            data={{ labels: names, datasets: [
              { label: 'False positive', data: names.map(name => fp.find(i => i.name === name)?.count || 0), backgroundColor: OUTCOME_COLOR.false_positive },
              { label: 'Benign/explained', data: names.map(name => benign.find(i => i.name === name)?.count || 0), backgroundColor: OUTCOME_COLOR.benign_explained },
            ] }} options={{ maintainAspectRatio: false, indexAxis: 'y', scales: { x: { beginAtZero: true, ticks: { precision: 0 } } }, plugins: { legend: { position: 'bottom' } } }} />
            : <p className="text-muted">No false-positive or benign indicators recorded.</p>}</div></div>
        </div>
        <h3 className="h6 mt-3">What-if thresholds on reviewed cases</h3>
        <p className="small text-muted">Uses current peak scores and current outcomes only. This is not a recall estimate or a recommendation to change rules.</p>
        <div className="table-responsive"><table className="table table-sm align-middle mb-0"><thead><tr>{['Threshold', 'Alerts kept', 'True positives kept', 'True positives lost', 'False positives removed', 'Benign removed', 'Resulting precision'].map(h => <th key={h}>{h}</th>)}</tr></thead>
          <tbody>{(data.what_if || []).map(row => <tr key={row.threshold}><th scope="row">{row.threshold}</th>{['alerts_kept', 'true_positives_kept', 'true_positives_lost', 'false_positives_removed', 'benign_removed'].map(k => <td key={k}>{row[k]}</td>)}<td>{precision(row.resulting_precision)}</td></tr>)}</tbody>
        </table></div>
      </>}
      <p className="small text-muted mt-3 mb-0">{data?.note || NOTE}</p>
    </Status>
  </section>
}
