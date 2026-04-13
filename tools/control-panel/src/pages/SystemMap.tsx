import {
  ReactFlow,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
  BackgroundVariant,
  type Node,
  type Edge,
  type NodeTypes,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

/* ── Custom Nodes ── */

function BrainNode({ data }: NodeProps) {
  return (
    <div className="node-brain">
      {data.label as string}
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function CategoryNode({ data }: NodeProps) {
  return (
    <div className="node-category">
      <Handle type="target" position={Position.Top} />
      {data.label as string}
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function FeatureNode({ data }: NodeProps) {
  const status = data.status as string
  const statusLabel = data.statusLabel as string
  return (
    <div className={`node-feature ${status}`}>
      <Handle type="target" position={Position.Top} />
      <div>{data.label as string}</div>
      <div className="node-status">{statusLabel}</div>
    </div>
  )
}

function DashboardNode({ data }: NodeProps) {
  return (
    <div className="node-dashboard">
      <Handle type="target" position={Position.Top} />
      <div>{data.label as string}</div>
      <div className="node-always">always on</div>
    </div>
  )
}

function RoadmapCard({ data }: NodeProps) {
  const items = data.items as { text: string; done: boolean; active?: boolean; sub?: string }[]
  const fillClass = data.fillClass as string
  const doneCount = items.filter(i => i.done).length
  const pct = Math.round((doneCount / items.length) * 100)
  return (
    <div className="roadmap-card">
      <div className="rc-header">
        <h4>{data.label as string}</h4>
        <span className="rc-count">{doneCount}/{items.length}</span>
      </div>
      <div className="rc-progress">
        <div className={`rc-progress-fill ${fillClass}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="rc-items">
        {items.map((item, i) => (
          <div key={i} className={`rc-item ${item.done ? 'done' : ''} ${item.active ? 'active' : ''}`}>
            <div className={`rc-dot ${item.done ? 'rc-dot-done' : item.active ? 'rc-dot-active' : 'rc-dot-todo'}`} />
            <span className="rc-label">{item.text}</span>
            {item.sub && <span className="rc-sublabel">{item.sub}</span>}
          </div>
        ))}
      </div>
    </div>
  )
}

const nodeTypes: NodeTypes = {
  brain: BrainNode,
  category: CategoryNode,
  feature: FeatureNode,
  dashboard: DashboardNode,
  roadmapCard: RoadmapCard,
}

/* ── Layout ── */

const nodes: Node[] = [
  // Level 0
  { id: 'system', type: 'brain', position: { x: 900, y: 0 }, data: { label: 'WTYJ System' } },

  // Level 1
  { id: 'agent', type: 'category', position: { x: 650, y: 150 }, data: { label: 'Agent' } },
  { id: 'dashboard', type: 'dashboard', position: { x: 1700, y: 142 }, data: { label: 'Dashboard' } },

  // Level 2
  { id: 'channels', type: 'category', position: { x: 250, y: 300 }, data: { label: 'Channels' } },
  { id: 'capabilities', type: 'category', position: { x: 950, y: 300 }, data: { label: 'Capabilities' } },
  { id: 'escalation', type: 'category', position: { x: 1530, y: 300 }, data: { label: 'Escalation' } },

  // Level 3 — Channel groups
  { id: 'ch-meta', type: 'category', position: { x: 120, y: 460 }, data: { label: 'Meta' } },
  { id: 'ch-email', type: 'feature', position: { x: 370, y: 460 }, data: { label: 'Email', status: 'built', statusLabel: 'Built' } },
  { id: 'ch-x', type: 'feature', position: { x: 490, y: 460 }, data: { label: 'X / Twitter', status: 'built', statusLabel: 'Built' } },

  // Level 3 — Capability groups
  { id: 'cap-booking', type: 'category', position: { x: 830, y: 460 }, data: { label: 'Booking' } },
  { id: 'cap-payment', type: 'feature', position: { x: 1000, y: 460 }, data: { label: 'Payment', status: 'planned', statusLabel: 'In Dev' } },
  { id: 'cap-inventory', type: 'feature', position: { x: 1130, y: 460 }, data: { label: 'Inventory', status: 'missing', statusLabel: 'Needed' } },
  { id: 'cap-content', type: 'feature', position: { x: 1260, y: 460 }, data: { label: 'Content', status: 'archived', statusLabel: 'Archived' } },

  // Level 3 — Escalation
  { id: 'esc-dashboard', type: 'feature', position: { x: 1420, y: 460 }, data: { label: 'Dashboard Alert', status: 'built', statusLabel: 'Built' } },
  { id: 'esc-whatsapp', type: 'feature', position: { x: 1570, y: 460 }, data: { label: 'Owner WhatsApp', status: 'missing', statusLabel: 'Needed' } },
  { id: 'esc-email', type: 'feature', position: { x: 1720, y: 460 }, data: { label: 'Owner Email', status: 'missing', statusLabel: 'Needed' } },

  // Level 4 — Meta channels
  { id: 'ch-whatsapp', type: 'feature', position: { x: 0, y: 620 }, data: { label: 'WhatsApp', status: 'built', statusLabel: 'Built' } },
  { id: 'ch-instagram', type: 'feature', position: { x: 130, y: 620 }, data: { label: 'Instagram', status: 'built', statusLabel: 'Built' } },
  { id: 'ch-facebook', type: 'feature', position: { x: 260, y: 620 }, data: { label: 'Facebook', status: 'built', statusLabel: 'Built' } },

  // Level 4 — Booking modes
  { id: 'cap-filter', type: 'feature', position: { x: 760, y: 620 }, data: { label: 'Filter / Buffer', status: 'built', statusLabel: 'Built' } },
  { id: 'cap-fullbook', type: 'feature', position: { x: 910, y: 620 }, data: { label: 'Full Booking', status: 'built', statusLabel: 'Built' } },

  // ── Roadmap cards (left side, spaced out) ──
  { id: 'rm-1', type: 'roadmapCard', position: { x: -800, y: -80 }, data: {
    label: 'Phase 1 — Social Agent + Data', fillClass: 'rc-fill-done',
    items: [
      { text: 'WhatsApp Q&A + booking orchestrator', done: true, sub: 'B067–089' },
      { text: 'Content agent + graphics + auto-posting', done: true, sub: 'B092–098' },
      { text: 'IG / FB / X DM integration via Zernio', done: true, sub: 'B130–170' },
      { text: 'Email IMAP polling + SMTP + OAuth', done: true, sub: 'B077' },
      { text: 'Full booking flow (holds, calendar, payment)', done: true, sub: 'B070' },
      { text: 'Operator dashboard + escalation system', done: true, sub: 'B099' },
      { text: 'Docker multi-client containers', done: true, sub: 'B142–152' },
      { text: 'client.json data-driven config', done: true, sub: 'B133–138' },
      { text: 'Feature toggles (booking, payment, terminology)', done: true, sub: 'B141' },
      { text: 'Cross-channel customer linking', done: true, sub: 'B178' },
    ],
  }},
  { id: 'rm-2', type: 'roadmapCard', position: { x: -800, y: 520 }, data: {
    label: 'Phase 2 — Modular Architecture', fillClass: 'rc-fill-active',
    items: [
      { text: 'Channel adapter pattern (pluggable channels)', done: true, sub: 'B186' },
      { text: 'Sender registry dispatch', done: true, sub: 'B187' },
      { text: 'Conversation state machine (pending/open/resolved)', done: true, sub: 'B188' },
      { text: 'Email poller adapter extraction', done: true, sub: 'B189' },
      { text: 'Content pipeline archived (feature-gated)', done: true, sub: 'B190' },
      { text: 'HD Azure Realty — first paying client', done: false, active: true, sub: 'Milestone H' },
      { text: 'CI/CD pipeline (GitHub Actions)', done: false, sub: 'Milestone G' },
      { text: 'Staging environment (ports 9001–9003)', done: false, sub: 'Milestone G' },
      { text: 'Automated backups (VPS + SQLite)', done: false, sub: 'Milestone G' },
      { text: 'Uptime monitoring (UptimeRobot)', done: false, sub: 'Milestone G' },
      { text: 'Owner WhatsApp escalation route', done: false, sub: 'Consulta Despertares + HD Azure' },
      { text: 'Owner email escalation route', done: false, sub: 'all clients' },
      { text: 'Dashboard reply-from-dashboard', done: false, sub: 'replace Gmail' },
      { text: 'Dashboard UX (setup wizard + theme)', done: false, active: true, sub: 'operator UX' },
    ],
  }},
  { id: 'rm-3', type: 'roadmapCard', position: { x: -800, y: 1380 }, data: {
    label: 'Security — Before First Client', fillClass: 'rc-fill-active',
    items: [
      { text: 'Strong dashboard passwords', done: false, sub: 'replace 123/456' },
      { text: 'Login rate limiting (5/min per IP)', done: false, sub: 'brute force' },
      { text: 'Session token TTL (24h expiry)', done: false, sub: 'currently never' },
      { text: 'Login audit logging', done: false, sub: 'who + when' },
      { text: 'Workspace code login (no client dropdown)', done: true, sub: 'info leak fix' },
    ],
  }},
  { id: 'rm-4', type: 'roadmapCard', position: { x: -800, y: 1780 }, data: {
    label: 'Phase 3 — Advanced Features', fillClass: 'rc-fill-future',
    items: [
      { text: 'RAG knowledge base (Ada-style doc ingestion)', done: false, sub: 'scale beyond FAQ' },
      { text: 'Inventory / listings data model', done: false, sub: 'real estate / car dealers' },
      { text: 'Shared booking state machine extraction', done: false, sub: 'dedup email + WA' },
      { text: 'Website form channel (hosted booking page)', done: false, sub: 'no-website clients' },
      { text: 'Telegram channel via Zernio', done: false, sub: 'webhook supported' },
      { text: 'Stripe Connect / Mollie Connect payments', done: false, sub: 'real money flow' },
      { text: 'Content pipeline reactivation', done: false, sub: 'social media posting' },
      { text: 'Open-window availability model', done: false, sub: 'salons, clinics' },
      { text: 'White-label per-client branding', done: false, sub: 'dashboard + emails' },
    ],
  }},
]

const edges: Edge[] = [
  // System → Level 1
  { id: 'e-0a', source: 'system', target: 'agent', type: 'smoothstep' },
  { id: 'e-0d', source: 'system', target: 'dashboard', type: 'smoothstep' },

  // Agent → Level 2
  { id: 'e-1', source: 'agent', target: 'channels', type: 'smoothstep' },
  { id: 'e-2', source: 'agent', target: 'capabilities', type: 'smoothstep' },
  { id: 'e-3', source: 'agent', target: 'escalation', type: 'smoothstep' },

  // Channels → Level 3
  { id: 'e-c1', source: 'channels', target: 'ch-meta', type: 'smoothstep' },
  { id: 'e-c2', source: 'channels', target: 'ch-email', type: 'smoothstep' },
  { id: 'e-c3', source: 'channels', target: 'ch-x', type: 'smoothstep' },

  // Meta → Level 4
  { id: 'e-m1', source: 'ch-meta', target: 'ch-whatsapp', type: 'smoothstep' },
  { id: 'e-m2', source: 'ch-meta', target: 'ch-instagram', type: 'smoothstep' },
  { id: 'e-m3', source: 'ch-meta', target: 'ch-facebook', type: 'smoothstep' },

  // Capabilities → Level 3
  { id: 'e-p1', source: 'capabilities', target: 'cap-booking', type: 'smoothstep' },
  { id: 'e-p2', source: 'capabilities', target: 'cap-payment', type: 'smoothstep' },
  { id: 'e-p3', source: 'capabilities', target: 'cap-inventory', type: 'smoothstep' },
  { id: 'e-p4', source: 'capabilities', target: 'cap-content', type: 'smoothstep' },

  // Booking → Level 4
  { id: 'e-b1', source: 'cap-booking', target: 'cap-filter', type: 'smoothstep' },
  { id: 'e-b2', source: 'cap-booking', target: 'cap-fullbook', type: 'smoothstep' },

  // Escalation → Level 3
  { id: 'e-s1', source: 'escalation', target: 'esc-dashboard', type: 'smoothstep' },
  { id: 'e-s2', source: 'escalation', target: 'esc-whatsapp', type: 'smoothstep' },
  { id: 'e-s3', source: 'escalation', target: 'esc-email', type: 'smoothstep' },
]

/* ── Component ── */

export default function SystemMap() {
  const [n, , onNodesChange] = useNodesState(nodes)
  const [e, , onEdgesChange] = useEdgesState(edges)

  return (
    <div className="system-map">
      <ReactFlow
        nodes={n}
        edges={e}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag
        zoomOnScroll
        minZoom={0.3}
        maxZoom={2}
      >
        <Controls showInteractive={false} />
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#e7e5e4" />
      </ReactFlow>
    </div>
  )
}
