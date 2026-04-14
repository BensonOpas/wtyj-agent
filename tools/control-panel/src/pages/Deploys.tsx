import { useState, useEffect } from 'react'

interface QueuedEntry {
  sha: string; short_sha: string; brief: number | null; subject: string; queued_at: string
}
interface AcknowledgedBrief {
  sha: string; short_sha: string; brief: number | null; subject: string; queued_at: string
}
interface InProgress {
  deploy_sha: string; deploy_short_sha: string; deploy_brief: number | null;
  deploy_subject: string; started_at: string; acknowledged_briefs: AcknowledgedBrief[]
}
interface HistoryEntry {
  sha: string; short_sha: string; brief: number | null; subject: string;
  deployed_at: string; duration_s: number; status: string; deployed_via_sha: string
}
interface DeployState {
  queued: QueuedEntry[]
  in_progress: InProgress | null
  history: HistoryEntry[]
}

function timeAgo(iso: string): string {
  const sec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  return `${Math.floor(sec / 86400)}d ago`
}

function nextOffHoursWindow(): string {
  const now = new Date()
  const next = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(),
                                  now.getUTCDate() + 1, 0, 0, 0))
  const ms = next.getTime() - now.getTime()
  const hrs = Math.floor(ms / 3600000)
  const mins = Math.floor((ms % 3600000) / 60000)
  return `${hrs}h ${mins}m`
}

export default function Deploys() {
  const [state, setState] = useState<DeployState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [triggering, setTriggering] = useState(false)

  const fetchState = () => {
    fetch('/api/deploys/state')
      .then(r => r.json())
      .then(d => { setState(d); setError(null) })
      .catch(e => setError(String(e)))
  }

  useEffect(() => {
    fetchState()
    const i = setInterval(fetchState, 30000)
    return () => clearInterval(i)
  }, [])

  const triggerDeploy = () => {
    setTriggering(true)
    fetch('/api/deploys/trigger', { method: 'POST' })
      .then(r => r.json())
      .then(() => setTimeout(fetchState, 2000))
      .finally(() => setTriggering(false))
  }

  if (error) return <div className="deploys-page"><div className="dp-error">Error: {error}</div></div>
  if (!state) return <div className="deploys-page">Loading...</div>

  return (
    <div className="deploys-page">
      <div className="dp-header">
        <h2>Deploys</h2>
        <button className="dp-trigger" onClick={triggerDeploy} disabled={triggering}>
          {triggering ? 'Triggering...' : 'Deploy queued now'}
        </button>
      </div>

      <section className="dp-section">
        <h3>Currently deploying</h3>
        {state.in_progress ? (
          <div className="dp-inprogress">
            <span className="dp-brief">Brief {state.in_progress.deploy_brief ?? '—'}</span>
            <span className="dp-sha">{state.in_progress.deploy_short_sha}</span>
            <span className="dp-subject">{state.in_progress.deploy_subject}</span>
            <span className="dp-elapsed">started {timeAgo(state.in_progress.started_at)}</span>
          </div>
        ) : (
          <div className="dp-empty">Idle</div>
        )}
      </section>

      <section className="dp-section">
        <h3>Queue ({state.queued.length} waiting) — auto-deploys in {nextOffHoursWindow()} (next off-hours window)</h3>
        {state.queued.length === 0 ? (
          <div className="dp-empty">Queue empty</div>
        ) : (
          <div className="dp-list">
            {state.queued.map(q => (
              <div key={q.sha} className="dp-row dp-queued">
                <span className="dp-brief">Brief {q.brief ?? '—'}</span>
                <span className="dp-sha">{q.short_sha}</span>
                <span className="dp-subject">{q.subject}</span>
                <span className="dp-time">queued {timeAgo(q.queued_at)}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="dp-section">
        <h3>Recent deploys</h3>
        {state.history.length === 0 ? (
          <div className="dp-empty">No deploys yet</div>
        ) : (
          <div className="dp-list">
            {state.history.map((h, i) => (
              <div key={`${h.sha}-${i}`} className={`dp-row dp-${h.status}`}>
                <span className="dp-brief">Brief {h.brief ?? '—'}</span>
                <span className="dp-sha">{h.short_sha}</span>
                <span className="dp-subject">{h.subject}</span>
                <span className={`dp-status dp-status-${h.status}`}>{h.status}</span>
                <span className="dp-time">{timeAgo(h.deployed_at)} ({h.duration_s}s)</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
