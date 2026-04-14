import { useState, useEffect, useRef } from 'react'

interface Subtask {
  id: string
  title: string
  done: boolean
}

interface Task {
  id: string
  title: string
  description: string
  createdAt: string
  priority: Priority
  subtasks: Subtask[]
  collapsed: boolean
}

type Priority = 'urgent' | 'important' | 'normal'
type Col = 'todo' | 'inProgress' | 'done'
type Workspace = 'sr' | 'jr'

interface Columns {
  todo: Task[]
  inProgress: Task[]
  done: Task[]
}

interface TaskData {
  sr: Columns
  jr: Columns
}

const COL_LABELS: Record<Col, string> = {
  todo: 'To Do',
  inProgress: 'In Progress',
  done: 'Done',
}

const PRIORITY_LABELS: Record<Priority, string> = {
  urgent: 'Urgent',
  important: 'Important',
  normal: 'Normal',
}

const COLS: Col[] = ['todo', 'inProgress', 'done']
const PRIORITIES: Priority[] = ['urgent', 'important', 'normal']

function sortByPriority(tasks: Task[]): Task[] {
  const order: Record<Priority, number> = { urgent: 0, important: 1, normal: 2 }
  return [...tasks].sort((a, b) => order[a.priority || 'normal'] - order[b.priority || 'normal'])
}

export default function Tasks() {
  const [ws, setWs] = useState<Workspace>('jr')
  const [data, setData] = useState<TaskData | null>(null)
  const [addingTo, setAddingTo] = useState<Col | null>(null)
  const [title, setTitle] = useState('')
  const [desc, setDesc] = useState('')
  const [dragOver, setDragOver] = useState<Col | null>(null)
  const [filter, setFilter] = useState<Priority | 'all'>('all')
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; col: Col; id: string } | null>(null)
  const [editing, setEditing] = useState<{ col: Col; id: string; title: string; description: string } | null>(null)
  const [addingSubTo, setAddingSubTo] = useState<{ col: Col; id: string } | null>(null)
  const [subTitle, setSubTitle] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const editTitleRef = useRef<HTMLInputElement>(null)
  const subInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    fetch('/api/tasks').then((r) => r.json()).then(setData)
    const interval = setInterval(() => {
      fetch('/api/tasks').then((r) => r.json()).then((fresh) => {
        setData((prev) => {
          if (JSON.stringify(prev) !== JSON.stringify(fresh)) return fresh
          return prev
        })
      })
    }, 3000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    if (addingTo && inputRef.current) inputRef.current.focus()
  }, [addingTo])

  useEffect(() => {
    if (editing && editTitleRef.current) editTitleRef.current.focus()
  }, [editing])

  useEffect(() => {
    if (addingSubTo && subInputRef.current) subInputRef.current.focus()
  }, [addingSubTo])

  useEffect(() => {
    const close = () => setCtxMenu(null)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [])

  const save = (next: TaskData) => {
    setData(next)
    fetch('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(next),
    })
  }

  const addTask = (col: Col) => {
    if (!title.trim() || !data) return
    const task: Task = {
      id: Date.now().toString(),
      title: title.trim(),
      description: desc.trim(),
      createdAt: new Date().toISOString().split('T')[0],
      priority: 'normal',
      subtasks: [],
      collapsed: true,
    }
    const next = structuredClone(data)
    next[ws][col].push(task)
    save(next)
    setTitle('')
    setDesc('')
    setAddingTo(null)
  }

  const deleteTask = (col: Col, id: string) => {
    if (!data) return
    const next = structuredClone(data)
    next[ws][col] = next[ws][col].filter((t) => t.id !== id)
    save(next)
  }

  const setPriority = (col: Col, id: string, priority: Priority) => {
    if (!data) return
    const next = structuredClone(data)
    const task = next[ws][col].find((t) => t.id === id)
    if (task) task.priority = priority
    save(next)
    setCtxMenu(null)
  }

  const openEdit = (col: Col, id: string) => {
    if (!data) return
    const task = data[ws][col].find((t) => t.id === id)
    if (task) setEditing({ col, id, title: task.title, description: task.description })
    setCtxMenu(null)
  }

  const saveEdit = () => {
    if (!editing || !data) return
    const next = structuredClone(data)
    const task = next[ws][editing.col].find((t) => t.id === editing.id)
    if (task) {
      task.title = editing.title.trim() || task.title
      task.description = editing.description.trim()
    }
    save(next)
    setEditing(null)
  }

  const toggleCollapsed = (col: Col, id: string) => {
    if (!data) return
    const next = structuredClone(data)
    const task = next[ws][col].find((t) => t.id === id)
    if (task) task.collapsed = !task.collapsed
    save(next)
  }

  const addSubtask = (col: Col, parentId: string) => {
    if (!subTitle.trim() || !data) return
    const next = structuredClone(data)
    const task = next[ws][col].find((t) => t.id === parentId)
    if (task) {
      task.subtasks = task.subtasks || []
      task.subtasks.push({
        id: Date.now().toString(),
        title: subTitle.trim(),
        done: false,
      })
      task.collapsed = false
    }
    save(next)
    setSubTitle('')
    setAddingSubTo(null)
  }

  const toggleSubtask = (col: Col, parentId: string, subId: string) => {
    if (!data) return
    const next = structuredClone(data)
    const task = next[ws][col].find((t) => t.id === parentId)
    if (task) {
      const sub = (task.subtasks || []).find((s) => s.id === subId)
      if (sub) sub.done = !sub.done
    }
    save(next)
  }

  const deleteSubtask = (col: Col, parentId: string, subId: string) => {
    if (!data) return
    const next = structuredClone(data)
    const task = next[ws][col].find((t) => t.id === parentId)
    if (task) {
      task.subtasks = (task.subtasks || []).filter((s) => s.id !== subId)
    }
    save(next)
  }

  const onDragStart = (e: React.DragEvent, id: string, from: Col) => {
    e.dataTransfer.setData('id', id)
    e.dataTransfer.setData('from', from)
    ;(e.target as HTMLElement).classList.add('dragging')
  }

  const onDragEnd = (e: React.DragEvent) => {
    ;(e.target as HTMLElement).classList.remove('dragging')
  }

  const onDrop = (e: React.DragEvent, to: Col) => {
    e.preventDefault()
    setDragOver(null)
    const id = e.dataTransfer.getData('id')
    const from = e.dataTransfer.getData('from') as Col
    if (from === to || !data) return

    const task = data[ws][from].find((t) => t.id === id)
    if (!task) return

    const next = structuredClone(data)
    next[ws][from] = next[ws][from].filter((t) => t.id !== id)
    next[ws][to].push(task)
    save(next)
  }

  const onContextMenu = (e: React.MouseEvent, col: Col, id: string) => {
    e.preventDefault()
    setCtxMenu({ x: e.clientX, y: e.clientY, col, id })
  }

  if (!data) return <div className="tasks-page">Loading...</div>

  const filterTasks = (tasks: Task[]) => {
    const sorted = sortByPriority(tasks)
    if (filter === 'all') return sorted
    return sorted.filter((t) => (t.priority || 'normal') === filter)
  }

  return (
    <div className="tasks-page">
      <div className="tasks-header">
        <div className="workspace-tabs">
          <button
            className={`workspace-tab ${ws === 'jr' ? 'active' : ''}`}
            onClick={() => setWs('jr')}
          >
            JR
          </button>
          <button
            className={`workspace-tab ${ws === 'sr' ? 'active' : ''}`}
            onClick={() => setWs('sr')}
          >
            SR
          </button>
        </div>
        <div className="filter-bar">
          <button
            className={`filter-btn ${filter === 'all' ? 'active' : ''}`}
            onClick={() => setFilter('all')}
          >
            All
          </button>
          <button
            className={`filter-btn filter-urgent ${filter === 'urgent' ? 'active' : ''}`}
            onClick={() => setFilter('urgent')}
          >
            Urgent
          </button>
          <button
            className={`filter-btn filter-important ${filter === 'important' ? 'active' : ''}`}
            onClick={() => setFilter('important')}
          >
            Important
          </button>
          <button
            className={`filter-btn filter-normal ${filter === 'normal' ? 'active' : ''}`}
            onClick={() => setFilter('normal')}
          >
            Normal
          </button>
        </div>
      </div>

      <div className="kanban">
        {COLS.map((col) => {
          const tasks = filterTasks(data[ws][col])
          return (
            <div
              key={col}
              className={`kanban-column ${dragOver === col ? 'drag-over' : ''}`}
              onDragOver={(e) => {
                e.preventDefault()
                setDragOver(col)
              }}
              onDragLeave={() => setDragOver(null)}
              onDrop={(e) => onDrop(e, col)}
            >
              <div className="column-header">
                <span className="column-title">{COL_LABELS[col]}</span>
                <span className="column-count">{tasks.length}</span>
              </div>

              <div className="kanban-cards">
                {tasks.map((task) => {
                  const subs = task.subtasks || []
                  const doneCount = subs.filter((s) => s.done).length
                  const hasSubs = subs.length > 0
                  const isExpanded = !task.collapsed && hasSubs
                  const isAddingSub = addingSubTo?.col === col && addingSubTo?.id === task.id

                  return (
                    <div
                      key={task.id}
                      className={`kanban-card ${task.priority || 'normal'}`}
                      draggable
                      onDragStart={(e) => onDragStart(e, task.id, col)}
                      onDragEnd={onDragEnd}
                      onContextMenu={(e) => onContextMenu(e, col, task.id)}
                    >
                      <div
                        className={`card-top ${hasSubs ? 'clickable' : ''}`}
                        onClick={() => hasSubs && toggleCollapsed(col, task.id)}
                      >
                        {hasSubs && (
                          <span className="card-expand">
                            {isExpanded ? '▼' : '▶'}
                          </span>
                        )}
                        <div className="card-top-content">
                          <div className="card-title">{task.title}</div>
                          {hasSubs && (
                            <span className="card-progress">
                              {doneCount}/{subs.length}
                            </span>
                          )}
                        </div>
                      </div>

                      {task.description && (
                        <div
                          className={`card-desc ${hasSubs ? 'clickable' : ''}`}
                          onClick={() => hasSubs && toggleCollapsed(col, task.id)}
                        >
                          {task.description}
                        </div>
                      )}

                      {isExpanded && (
                        <div className="subtask-list">
                          {subs.map((sub) => (
                            <div key={sub.id} className={`subtask ${sub.done ? 'done' : ''}`}>
                              <label className="subtask-check">
                                <input
                                  type="checkbox"
                                  checked={sub.done}
                                  onChange={() => toggleSubtask(col, task.id, sub.id)}
                                />
                                <span className="subtask-title">{sub.title}</span>
                              </label>
                              <button
                                className="subtask-delete"
                                onClick={() => deleteSubtask(col, task.id, sub.id)}
                              >
                                &times;
                              </button>
                            </div>
                          ))}
                        </div>
                      )}

                      {isAddingSub ? (
                        <div className="subtask-add-form">
                          <input
                            ref={subInputRef}
                            className="subtask-input"
                            placeholder="Subtask title"
                            value={subTitle}
                            onChange={(e) => setSubTitle(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') addSubtask(col, task.id)
                              if (e.key === 'Escape') { setAddingSubTo(null); setSubTitle('') }
                            }}
                          />
                          <div className="add-card-actions">
                            <button className="btn-add" onClick={() => addSubtask(col, task.id)}>Add</button>
                            <button className="btn-cancel" onClick={() => { setAddingSubTo(null); setSubTitle('') }}>Cancel</button>
                          </div>
                        </div>
                      ) : (
                        <button
                          className="subtask-add-btn"
                          onClick={() => { setAddingSubTo({ col, id: task.id }); toggleCollapsed(col, task.id) }}
                        >
                          + subtask
                        </button>
                      )}

                      <div className="card-footer">
                        <span className="card-date">{task.createdAt}</span>
                        <button
                          className="card-delete"
                          onClick={() => deleteTask(col, task.id)}
                        >
                          &times;
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>

              {addingTo === col ? (
                <div className="add-card-form">
                  <input
                    ref={inputRef}
                    className="add-card-input"
                    placeholder="Task title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && addTask(col)}
                  />
                  <input
                    className="add-card-input"
                    placeholder="Description (optional)"
                    value={desc}
                    onChange={(e) => setDesc(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && addTask(col)}
                  />
                  <div className="add-card-actions">
                    <button className="btn-add" onClick={() => addTask(col)}>
                      Add
                    </button>
                    <button
                      className="btn-cancel"
                      onClick={() => {
                        setAddingTo(null)
                        setTitle('')
                        setDesc('')
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  className="add-card-btn"
                  onClick={() => setAddingTo(col)}
                >
                  + Add task
                </button>
              )}
            </div>
          )
        })}
      </div>

      {ctxMenu && (
        <div
          className="context-menu"
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          {PRIORITIES.map((p) => (
            <button
              key={p}
              className={`ctx-btn ctx-${p}`}
              onClick={() => setPriority(ctxMenu.col, ctxMenu.id, p)}
            >
              <span className={`ctx-dot ${p}`} />
              {PRIORITY_LABELS[p]}
            </button>
          ))}
          <div className="ctx-divider" />
          <button
            className="ctx-btn"
            onClick={() => openEdit(ctxMenu.col, ctxMenu.id)}
          >
            Edit
          </button>
        </div>
      )}

      {editing && (
        <div className="modal-overlay" onClick={() => setEditing(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">Edit task</div>
            <input
              ref={editTitleRef}
              className="add-card-input"
              placeholder="Title"
              value={editing.title}
              onChange={(e) => setEditing({ ...editing, title: e.target.value })}
              onKeyDown={(e) => e.key === 'Enter' && saveEdit()}
            />
            <textarea
              className="add-card-input modal-textarea"
              placeholder="Description (optional)"
              value={editing.description}
              onChange={(e) => setEditing({ ...editing, description: e.target.value })}
              rows={3}
            />
            <div className="add-card-actions">
              <button className="btn-add" onClick={saveEdit}>Save</button>
              <button className="btn-cancel" onClick={() => setEditing(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
