import { ArcElement, BarElement, CategoryScale, Chart as ChartJS, Legend, LinearScale, LineElement, PointElement, Tooltip } from 'chart.js'
import { Bar, Doughnut, Line } from 'react-chartjs-2'

ChartJS.register(ArcElement, BarElement, CategoryScale, Legend, LinearScale, LineElement, PointElement, Tooltip)
const colors = ['#2563eb', '#249e83', '#e0aa32', '#d9480f', '#8290a5', '#b00020']
export function UserChart({ title, values = {}, kind = 'bar', datasets, labels }) {
  const Chart = kind === 'doughnut' ? Doughnut : kind === 'line' ? Line : Bar
  const data = { labels: labels || Object.keys(values), datasets: datasets || [{ label: title, data: Object.values(values), backgroundColor: kind === 'line' ? '#2563eb' : colors, borderColor: '#2563eb', tension: 0.2 }] }
  return <section className="dash-panel p-3"><h2 className="h6">{title}</h2><div style={{ height: 210 }}><Chart aria-label={title} role="img" data={data} options={{ maintainAspectRatio: false, plugins: { legend: { display: kind === 'doughnut' || !!datasets, position: 'bottom' } }, ...(kind !== 'doughnut' ? { scales: { y: { beginAtZero: true } } } : {}) }} /></div></section>
}
