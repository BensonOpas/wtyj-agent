const express = require('express')
const cors = require('cors')
const fs = require('fs')
const path = require('path')

const app = express()
app.use(cors())
app.use(express.json())

const DATA_DIR = path.join(__dirname, 'data')
const TASKS_FILE = path.join(DATA_DIR, 'tasks.json')

if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true })
if (!fs.existsSync(TASKS_FILE)) {
  fs.writeFileSync(TASKS_FILE, JSON.stringify({
    sr: { todo: [], inProgress: [], done: [] },
    jr: { todo: [], inProgress: [], done: [] },
  }, null, 2))
}

app.get('/api/tasks', (_req, res) => {
  const data = JSON.parse(fs.readFileSync(TASKS_FILE, 'utf8'))
  res.json(data)
})

app.post('/api/tasks', (req, res) => {
  fs.writeFileSync(TASKS_FILE, JSON.stringify(req.body, null, 2))
  res.json({ ok: true })
})

// Clients API
const CLIENTS_FILE = path.join(DATA_DIR, 'clients.json')

app.get('/api/clients', (_req, res) => {
  const data = JSON.parse(fs.readFileSync(CLIENTS_FILE, 'utf8'))
  res.json(data)
})

app.post('/api/clients', (req, res) => {
  fs.writeFileSync(CLIENTS_FILE, JSON.stringify(req.body, null, 2))
  res.json({ ok: true })
})

// Docs API
const REPO_ROOT = path.join(__dirname, '..', '..')

app.get('/api/docs', (_req, res) => {
  const files = []

  // wtyj/docs/
  const docsDir = path.join(REPO_ROOT, 'wtyj', 'docs')
  if (fs.existsSync(docsDir)) {
    fs.readdirSync(docsDir)
      .filter(f => f.endsWith('.md'))
      .forEach(f => files.push({ name: f.replace('.md', ''), path: 'wtyj/docs/' + f, category: 'Docs' }))
  }

  // Core planning files from briefs/
  const planning = ['roadmap.md', 'infra.md', 'master_plan.md', 'system_state.md', 'marina_lessons.md']
  planning.forEach(f => {
    const fp = path.join(REPO_ROOT, 'wtyj', 'briefs', f)
    if (fs.existsSync(fp)) {
      files.push({ name: f.replace('.md', ''), path: 'wtyj/briefs/' + f, category: 'Planning' })
    }
  })

  // Root
  if (fs.existsSync(path.join(REPO_ROOT, 'CLAUDE.md'))) {
    files.push({ name: 'CLAUDE', path: 'CLAUDE.md', category: 'Root' })
  }

  res.json(files)
})

app.get('/api/docs/read', (req, res) => {
  const filePath = req.query.path
  if (!filePath || filePath.includes('..')) return res.status(400).send('Bad path')
  const fullPath = path.join(REPO_ROOT, filePath)
  if (!fs.existsSync(fullPath)) return res.status(404).send('Not found')
  res.type('text/plain').send(fs.readFileSync(fullPath, 'utf8'))
})

// Deploys: SSH to VPS to read queue state
app.get('/api/deploys/state', (_req, res) => {
  const { exec } = require('child_process')
  exec(
    'ssh root@108.61.192.52 "cat /root/wtyj_deploy_queue.json 2>/dev/null || echo \'{}\'"',
    { timeout: 5000 },
    (err, stdout) => {
      if (err) return res.status(500).json({ error: err.message })
      try {
        const parsed = JSON.parse(stdout || '{}')
        res.json({
          queued: parsed.queued || [],
          in_progress: parsed.in_progress || null,
          history: parsed.history || [],
        })
      } catch (e) {
        res.status(500).json({ error: 'parse failed', raw: stdout })
      }
    }
  )
})

app.post('/api/deploys/trigger', (_req, res) => {
  const { exec } = require('child_process')
  exec(
    'gh workflow run scheduled-deploy.yml -R BensonOpas/wtyj-agent',
    { timeout: 8000 },
    (err, stdout, stderr) => {
      if (err) return res.status(500).json({ error: err.message, stderr })
      res.json({ ok: true, message: 'Triggered scheduled-deploy workflow' })
    }
  )
})

const PORT = 3001
app.listen(PORT, () => {
  console.log(`Control Panel API on http://localhost:${PORT}`)
})
