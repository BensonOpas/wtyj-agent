import { useState, useEffect } from 'react'

interface Toggle {
  name: string
  on: boolean
}

interface Client {
  name: string
  status: string
  statusLabel: string
  mode: string
  channels: Toggle[]
  capabilities: Toggle[]
  escalation: Toggle[]
}

export default function Clients() {
  const [clients, setClients] = useState<Client[]>([])

  useEffect(() => {
    fetch('/api/clients').then((r) => r.json()).then(setClients)
    const interval = setInterval(() => {
      fetch('/api/clients').then((r) => r.json()).then((fresh) => {
        setClients((prev) => {
          if (JSON.stringify(prev) !== JSON.stringify(fresh)) return fresh
          return prev
        })
      })
    }, 3000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="clients-page">
      <h2>Clients</h2>
      <div className="client-grid">
        {clients.map((client) => (
          <div key={client.name} className="client-card">
            <h3>{client.name}</h3>
            <div className={`client-status ${client.status}`}>
              {client.statusLabel}
            </div>

            <div className="client-section">
              <div className="client-section-title">Mode</div>
              <div className="client-mode">{client.mode}</div>
            </div>

            <div className="client-section">
              <div className="client-section-title">Channels</div>
              <div className="client-tags">
                {client.channels.map((ch) => (
                  <span key={ch.name} className={`client-tag ${ch.on ? 'on' : 'off'}`}>
                    {ch.name}
                  </span>
                ))}
              </div>
            </div>

            <div className="client-section">
              <div className="client-section-title">Capabilities</div>
              <div className="client-tags">
                {client.capabilities.map((cap) => (
                  <span key={cap.name} className={`client-tag ${cap.on ? 'on' : 'off'}`}>
                    {cap.name}
                  </span>
                ))}
              </div>
            </div>

            <div className="client-section">
              <div className="client-section-title">Escalation</div>
              <div className="client-tags">
                {client.escalation.map((esc) => (
                  <span key={esc.name} className={`client-tag ${esc.on ? 'on' : 'off'}`}>
                    {esc.name}
                  </span>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
