import { useState, useRef, useEffect, useCallback } from 'react'
import Markdown from 'react-markdown'

interface DocFile {
  name: string
  path: string
  category: string
}

const COLORS = ['#1c1917', '#dc2626', '#2563eb', '#16a34a', '#ea580c', '#7c3aed']
const WIDTHS = [2, 5, 10]

export default function Workspace() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const historyRef = useRef<ImageData[]>([])
  const redoRef = useRef<ImageData[]>([])
  const [isDrawing, setIsDrawing] = useState(false)
  const [color, setColor] = useState('#1c1917')
  const [width, setWidth] = useState(2)
  const [eraser, setEraser] = useState(false)
  const [, forceUpdate] = useState(0)

  const [docsOpen, setDocsOpen] = useState(false)
  const [docs, setDocs] = useState<DocFile[]>([])
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null)
  const [docContent, setDocContent] = useState('')

  useEffect(() => {
    fetch('/api/docs').then((r) => r.json()).then(setDocs)
  }, [])

  useEffect(() => {
    if (!selectedDoc) { setDocContent(''); return }
    fetch(`/api/docs/read?path=${encodeURIComponent(selectedDoc)}`)
      .then((r) => r.text())
      .then(setDocContent)
  }, [selectedDoc])

  const setupCanvas = useCallback(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return
    const rect = container.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    canvas.width = rect.width * dpr
    canvas.height = rect.height * dpr
    canvas.style.width = rect.width + 'px'
    canvas.style.height = rect.height + 'px'
    const ctx = canvas.getContext('2d')!
    ctx.scale(dpr, dpr)
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, rect.width, rect.height)
    historyRef.current = []
    redoRef.current = []
    saveState()
  }, [])

  useEffect(() => {
    setupCanvas()
    window.addEventListener('resize', setupCanvas)
    return () => window.removeEventListener('resize', setupCanvas)
  }, [setupCanvas, docsOpen])

  const saveState = () => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    historyRef.current.push(ctx.getImageData(0, 0, canvas.width, canvas.height))
    if (historyRef.current.length > 50) historyRef.current.shift()
    redoRef.current = []
    forceUpdate((n) => n + 1)
  }

  const restoreState = (state: ImageData) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    ctx.putImageData(state, 0, 0)
  }

  const undo = useCallback(() => {
    if (historyRef.current.length <= 1) return
    const current = historyRef.current.pop()!
    redoRef.current.push(current)
    restoreState(historyRef.current[historyRef.current.length - 1])
    forceUpdate((n) => n + 1)
  }, [])

  const redo = useCallback(() => {
    if (redoRef.current.length === 0) return
    const state = redoRef.current.pop()!
    historyRef.current.push(state)
    restoreState(state)
    forceUpdate((n) => n + 1)
  }, [])

  const clear = () => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const dpr = window.devicePixelRatio || 1
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, canvas.width / dpr, canvas.height / dpr)
    saveState()
  }

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'z') {
        e.preventDefault()
        if (e.shiftKey) redo()
        else undo()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [undo, redo])

  const getPoint = (e: React.MouseEvent) => {
    const rect = canvasRef.current!.getBoundingClientRect()
    return { x: e.clientX - rect.left, y: e.clientY - rect.top }
  }

  const startDraw = (e: React.MouseEvent) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const p = getPoint(e)
    ctx.beginPath()
    ctx.moveTo(p.x, p.y)
    ctx.strokeStyle = eraser ? '#ffffff' : color
    ctx.lineWidth = eraser ? width * 4 : width
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    setIsDrawing(true)
  }

  const draw = (e: React.MouseEvent) => {
    if (!isDrawing) return
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const p = getPoint(e)
    ctx.lineTo(p.x, p.y)
    ctx.stroke()
  }

  const endDraw = () => {
    if (!isDrawing) return
    setIsDrawing(false)
    saveState()
  }

  return (
    <div className="workspace">
      <div className={`wb-main ${docsOpen ? 'with-docs' : ''}`}>
        <div className="wb-toolbar">
          <div className="wb-group">
            <button
              className={`wb-tool ${!eraser ? 'active' : ''}`}
              onClick={() => setEraser(false)}
            >
              Pen
            </button>
            <button
              className={`wb-tool ${eraser ? 'active' : ''}`}
              onClick={() => setEraser(true)}
            >
              Eraser
            </button>
          </div>

          <div className="wb-sep" />

          <div className="wb-group">
            {COLORS.map((c) => (
              <button
                key={c}
                className={`wb-color ${color === c && !eraser ? 'active' : ''}`}
                style={{ background: c }}
                onClick={() => {
                  setColor(c)
                  setEraser(false)
                }}
              />
            ))}
          </div>

          <div className="wb-sep" />

          <div className="wb-group">
            {WIDTHS.map((w) => (
              <button
                key={w}
                className={`wb-width ${width === w ? 'active' : ''}`}
                onClick={() => setWidth(w)}
              >
                <span
                  className="wb-width-dot"
                  style={{ width: w + 4, height: w + 4 }}
                />
              </button>
            ))}
          </div>

          <div className="wb-sep" />

          <div className="wb-group">
            <button className="wb-tool" onClick={undo}>
              Undo
            </button>
            <button className="wb-tool" onClick={redo}>
              Redo
            </button>
            <button className="wb-tool" onClick={clear}>
              Clear
            </button>
          </div>

          <div style={{ flex: 1 }} />

          <button
            className={`wb-tool ${docsOpen ? 'active' : ''}`}
            onClick={() => setDocsOpen(!docsOpen)}
          >
            Docs
          </button>
        </div>

        <div className="wb-canvas-wrap" ref={containerRef}>
          <canvas
            ref={canvasRef}
            onMouseDown={startDraw}
            onMouseMove={draw}
            onMouseUp={endDraw}
            onMouseLeave={endDraw}
            style={{ cursor: eraser ? 'cell' : 'crosshair' }}
          />
        </div>
      </div>

      {docsOpen && (
        <div className="docs-panel">
          <div className="docs-header">
            <select
              className="docs-select"
              value={selectedDoc || ''}
              onChange={(e) => setSelectedDoc(e.target.value || null)}
            >
              <option value="">Select a document...</option>
              {docs.map((d) => (
                <option key={d.path} value={d.path}>
                  {d.category} / {d.name}
                </option>
              ))}
            </select>
          </div>
          <div className="docs-content">
            {docContent ? (
              <Markdown>{docContent}</Markdown>
            ) : (
              <div className="docs-empty">Select a document to read</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
