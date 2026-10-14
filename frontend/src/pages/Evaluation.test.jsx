import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { api } from '../api'
import Evaluation from './Evaluation.jsx'

vi.mock('../api', () => ({ api: { evaluation: vi.fn(), runEvaluation: vi.fn() } }))
vi.mock('react-chartjs-2', () => ({ Bar: props => <div role="img" aria-label={props['aria-label']} /> }))

const metrics = { precision: .8, recall: .9, f1: .847, false_positive_rate: .01, false_negative_rate: .1, scenarios_detected: 2, scenarios_total: 3, median_detection_latency_minutes: 0, mean_detection_latency_minutes: 2, tp: 9, fp: 1, fn: 1, tn: 89 }
const result = {
  created_at: '2026-10-01T10:00:00', run_by: 'analyst', alert_threshold: 25,
  unit_of_analysis: 'user-day', dataset: { users_evaluated: 10, evaluated_user_days: 100, malicious_user_days: 10, scenarios: 3 },
  modes: { rule_only: metrics, anomaly_only: metrics, hybrid: metrics },
  by_scenario_type: { decoy_access: { rule_only: { detected: 0, total: 1, median_latency_minutes: null }, anomaly_only: { detected: 1, total: 1, median_latency_minutes: 0 }, hybrid: { detected: 1, total: 1, median_latency_minutes: 2 } } },
}

beforeEach(() => {
  vi.clearAllMocks()
  api.evaluation.mockResolvedValue(result)
  api.runEvaluation.mockResolvedValue(result)
})

it('renders separate performance and error charts and filters scenarios', async () => {
  render(<Evaluation />)
  await screen.findByText('Metrics comparison')
  expect(screen.getByRole('img', { name: 'Precision, recall and F1-score comparison' })).toBeInTheDocument()
  expect(screen.getByRole('img', { name: 'False-positive and false-negative rate comparison' })).toBeInTheDocument()
  expect(screen.getByText('Not detected')).toBeInTheDocument()
  expect(screen.getAllByText('0 min').length).toBeGreaterThan(0)
  fireEvent.change(screen.getByLabelText('Search scenario types'), { target: { value: 'missing' } })
  expect(screen.getByText('No scenario types match your search.')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Search scenario types'), { target: { value: 'decoy' } })
  expect(screen.getByText('decoy access')).toBeInTheDocument()
})

it('can run the first evaluation from the empty state and refresh results', async () => {
  api.evaluation.mockRejectedValueOnce({ status: 404 }).mockResolvedValue(result)
  render(<Evaluation />)
  await screen.findByText('No evaluation results yet')
  fireEvent.click(screen.getByRole('button', { name: 'Run evaluation' }))
  await screen.findByText('Metrics comparison')
  expect(api.runEvaluation).toHaveBeenCalledTimes(1)
  expect(api.evaluation).toHaveBeenCalledTimes(2)
})

it('retains displayed results and restores run controls after a failed run', async () => {
  api.runEvaluation.mockRejectedValueOnce(new Error('No labelled events found'))
  render(<Evaluation />)
  await screen.findByText('Metrics comparison')
  fireEvent.click(screen.getByRole('button', { name: 'Run evaluation' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('No labelled events found')
  expect(screen.getByText('Metrics comparison')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByRole('button', { name: 'Run evaluation' })).toBeEnabled())
})
