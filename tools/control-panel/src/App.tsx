import { useState } from 'react'
import SystemMap from './pages/SystemMap'
import Clients from './pages/Clients'
import Tasks from './pages/Tasks'
import Workspace from './pages/Workspace'
import Deploys from './pages/Deploys'

type Tab = 'system' | 'tasks' | 'workspace' | 'clients' | 'deploys'

const TAB_LABELS: Record<Tab, string> = {
  system: 'System',
  tasks: 'Tasks',
  workspace: 'Workspace',
  clients: 'Clients',
  deploys: 'Deploys',
}

export default function App() {
  const [tab, setTab] = useState<Tab>('system')

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{flexShrink: 0}}>
            <rect x="1" y="3" width="14" height="10" rx="2" stroke="currentColor" strokeWidth="1.5" fill="none"/>
            <text x="4.5" y="10.5" fill="currentColor" fontSize="7" fontFamily="monospace" fontWeight="bold">&gt;_</text>
          </svg>
          <span className="logo-sub">Control Panel</span>
        </div>
        <nav className="tabs">
          {(Object.keys(TAB_LABELS) as Tab[]).map((t) => (
            <button
              key={t}
              className={`tab ${tab === t ? 'active' : ''}`}
              onClick={() => setTab(t)}
            >
              {TAB_LABELS[t]}
            </button>
          ))}
        </nav>
      </header>
      <main className="main">
        {tab === 'system' && <SystemMap />}
        {tab === 'clients' && <Clients />}
        {tab === 'tasks' && <Tasks />}
        {tab === 'workspace' && <Workspace />}
        {tab === 'deploys' && <Deploys />}
      </main>
    </div>
  )
}
