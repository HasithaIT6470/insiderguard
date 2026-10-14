import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import 'bootstrap/dist/css/bootstrap.min.css'
import App from './App.jsx'
import './styles.css'
import { Chart as ChartJS } from 'chart.js'

document.documentElement.setAttribute('data-bs-theme', 'light')
ChartJS.defaults.color = '#596579'
ChartJS.defaults.borderColor = '#e1e5eb'
ChartJS.defaults.plugins.legend.labels.color = '#344054'
ChartJS.defaults.plugins.tooltip.backgroundColor = '#101215'
ChartJS.defaults.plugins.tooltip.titleColor = '#f1f3f6'
ChartJS.defaults.plugins.tooltip.bodyColor = '#dce1e8'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
