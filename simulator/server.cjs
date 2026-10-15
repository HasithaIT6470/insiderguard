const http = require('node:http')
const fs = require('node:fs')
const path = require('node:path')
const port = Number(process.env.SIMULATOR_PORT || 5175)
const apiPort = Number(process.env.INSIDERGUARD_API_PORT || 8000)
if (![port, apiPort].every(p => Number.isInteger(p) && p > 0 && p <= 65535)) throw new Error('Invalid port')
const files = { '/': ['index.html', 'text/html'], '/app.js': ['app.js', 'text/javascript'],
  '/scenarios.js': ['scenarios.js', 'text/javascript'], '/styles.css': ['styles.css', 'text/css'] }
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname
  if (pathname.startsWith('/api/')) {
    const headers = {}
    for (const name of ['authorization', 'content-type', 'content-length']) if (req.headers[name]) headers[name] = req.headers[name]
    const proxy = http.request({ hostname: '127.0.0.1', port: apiPort, path: req.url, method: req.method, headers }, upstream => {
      res.writeHead(upstream.statusCode, { 'Content-Type': upstream.headers['content-type'] || 'application/json',
        'Cache-Control': 'no-store', ...(upstream.headers['content-disposition'] ? { 'Content-Disposition': upstream.headers['content-disposition'] } : {}) })
      upstream.pipe(res)
    })
    proxy.setTimeout(120000, () => proxy.destroy(new Error('API request timed out')))
    proxy.on('error', () => { if (!res.headersSent) { res.writeHead(502, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ detail: 'InsiderGuard API is unavailable. Start InsiderGuard and try again.' })) } else res.destroy() })
    req.on('aborted', () => proxy.destroy())
    req.pipe(proxy)
    return
  }
  if (!['GET', 'HEAD'].includes(req.method) || !files[pathname]) { res.writeHead(404); res.end('Not found'); return }
  const [filename, type] = files[pathname]
  res.writeHead(200, { 'Content-Type': `${type}; charset=utf-8`, 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer' })
  if (req.method === 'HEAD') res.end()
  else fs.createReadStream(path.join(__dirname, filename)).pipe(res)
})
server.listen(port, '127.0.0.1', () => console.log(`Activity simulator: http://localhost:${port} → InsiderGuard API :${apiPort}`))
