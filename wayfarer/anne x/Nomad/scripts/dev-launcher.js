#!/usr/bin/env node
const { spawn } = require('child_process')
const fs = require('fs')
const path = require('path')

const BASE = path.resolve(__dirname, '..')
const FRONTEND_DIR = path.join(BASE, 'frontend')
const LOG_DIR = path.join(BASE, 'logs')
if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true })

function prefixStream(prefix, stream, writeStream) {
  stream.on('data', (chunk) => {
    const lines = String(chunk).split(/\n/)
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].length === 0) continue
      const out = `[${prefix}] ${lines[i]}\n`
      process.stdout.write(out)
      if (writeStream) writeStream.write(out)
    }
  })
}

function startBackend() {
  // Prefer venv python if available
  const venvPython = path.join(BASE, '.venv', 'bin', 'python')
  const pythonCmd = fs.existsSync(venvPython) ? venvPython : 'python'
  const args = ['-m', 'uvicorn', 'src.nomad.main:app', '--reload', '--port', '8000']
  const outLog = fs.createWriteStream(path.join(LOG_DIR, 'uvicorn.log'), { flags: 'a' })
  const child = spawn(pythonCmd, args, { cwd: BASE })
  prefixStream('backend', child.stdout, outLog)
  prefixStream('backend', child.stderr, outLog)
  child.on('exit', (code, signal) => {
    console.log(`[backend] exited code=${code} signal=${signal}`)
    outLog.end()
  })
  return child
}

function startFrontend() {
  const outLog = fs.createWriteStream(path.join(LOG_DIR, 'frontend.log'), { flags: 'a' })
  // Use npm start in frontend
  const child = spawn(process.platform === 'win32' ? 'npm.cmd' : 'npm', ['start'], { cwd: FRONTEND_DIR })
  prefixStream('frontend', child.stdout, outLog)
  prefixStream('frontend', child.stderr, outLog)
  child.on('exit', (code, signal) => {
    console.log(`[frontend] exited code=${code} signal=${signal}`)
    outLog.end()
  })
  return child
}

console.log('Starting Nomad dev launcher...')
const backend = startBackend()
const frontend = startFrontend()

function shutdown() {
  console.log('Shutting down Nomad dev launcher...')
  try {
    if (frontend && !frontend.killed) frontend.kill('SIGTERM')
  } catch (e) {}
  try {
    if (backend && !backend.killed) backend.kill('SIGTERM')
  } catch (e) {}
  process.exit(0)
}

process.on('SIGINT', shutdown)
process.on('SIGTERM', shutdown)

// If any child dies unexpectedly, exit so the developer can notice/repair
backend.on('exit', (code) => {
  if (code !== 0) process.exit(code || 1)
})
frontend.on('exit', (code) => {
  if (code !== 0) process.exit(code || 1)
})
