import { spawn } from 'node:child_process'
import http from 'node:http'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')

let docsProcess = null
let docsReadyPromise = null

function waitForDocsServer(maxMs = 120_000) {
  const deadline = Date.now() + maxMs

  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get('http://127.0.0.1:3000/docs/', (res) => {
        res.resume()
        if (res.statusCode && res.statusCode >= 200 && res.statusCode < 400) {
          resolve()
          return
        }
        if (Date.now() > deadline) {
          reject(new Error(`Documentation server returned HTTP ${res.statusCode}`))
          return
        }
        setTimeout(attempt, 500)
      })
      req.on('error', () => {
        if (Date.now() > deadline) {
          reject(new Error('Documentation server did not become ready in time'))
          return
        }
        setTimeout(attempt, 500)
      })
      req.setTimeout(2_000, () => req.destroy())
    }
    attempt()
  })
}

function ensureDocsServer() {
  if (docsReadyPromise) {
    return docsReadyPromise
  }

  console.log('[docs] Starting Docusaurus (opened from Documentation link)…')
  docsProcess = spawn('npm', ['run', 'docs:dev'], {
    cwd: frontendRoot,
    shell: true,
    stdio: 'inherit',
    env: process.env,
  })

  docsProcess.on('exit', (code) => {
    if (code !== 0 && code !== null) {
      console.error(`[docs] Docusaurus exited with code ${code}`)
    }
    docsProcess = null
    docsReadyPromise = null
  })

  docsReadyPromise = waitForDocsServer()
    .then(() => {
      console.log('[docs] Docusaurus is ready at /docs/')
    })
    .catch((error) => {
      if (docsProcess) {
        docsProcess.kill('SIGTERM')
        docsProcess = null
      }
      docsReadyPromise = null
      throw error
    })

  return docsReadyPromise
}

function proxyToDocs(req, res) {
  const proxyReq = http.request(
    {
      hostname: '127.0.0.1',
      port: 3000,
      path: req.url,
      method: req.method,
      headers: {
        ...req.headers,
        host: '127.0.0.1:3000',
      },
    },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode ?? 502, proxyRes.headers)
      proxyRes.pipe(res)
    },
  )
  proxyReq.on('error', (error) => {
    if (!res.headersSent) {
      res.statusCode = 502
      res.end(`Documentation proxy error: ${error.message}`)
    }
  })
  req.pipe(proxyReq)
}

function stopDocsServer() {
  if (docsProcess) {
    docsProcess.kill('SIGTERM')
    docsProcess = null
  }
  docsReadyPromise = null
}

/** Start Docusaurus only when /docs is requested (e.g. Documentation menu link). */
export default function lazyDocusaurus() {
  return {
    name: 'lazy-docusaurus',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (!req.url?.startsWith('/docs')) {
          next()
          return
        }
        ensureDocsServer()
          .then(() => proxyToDocs(req, res))
          .catch((error) => {
            res.statusCode = 503
            res.end(`Documentation server unavailable: ${error.message}`)
          })
      })

      return () => stopDocsServer()
    },
  }
}
