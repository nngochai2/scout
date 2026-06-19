import { useState, useEffect, useCallback, useMemo } from 'react'
import FlowEditor from './FlowEditor'

const API = 'http://localhost:8000'

// ─── Types ────────────────────────────────────────────────────────────────────

type Route = 'overview' | 'dashboard' | 'cost' | 'validation' | 'flow' | 'db'
type TriageVerdict = 'investigate' | 'clarify' | 'insufficient_signal' | 'out_of_scope'
type SourceType = 'DOC' | 'DB' | 'CODE' | 'ADO'
type ConfLevel = 'High' | 'Medium' | 'Low' | 'Insufficient'
type ConfKey = 'high' | 'med' | 'low'

interface Evidence { source_type: SourceType; reference: string; passage: string }
interface Triage { verdict: TriageVerdict; summary: string | null; clarifying_question: string | null }
interface Diagnosis { root_cause: string | null; confidence: ConfLevel | null; evidence: Evidence[] }
interface StageCost { input: number; output: number }
interface Ticket {
  id: string; title: string; source_system: string
  triage: Triage | null; diagnosis: Diagnosis | null
  stage_costs: Record<string, StageCost>
  review: { action: string } | null
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function confKey(t: Ticket): ConfKey {
  if (t.triage?.verdict === 'clarify') return 'low'
  const c = t.diagnosis?.confidence
  if (c === 'High') return 'high'
  if (c === 'Medium') return 'med'
  return 'low'
}

function isNeedsInput(t: Ticket) { return t.triage?.verdict === 'clarify' }
function isVisible(t: Ticket) {
  const v = t.triage?.verdict
  return v === 'investigate' || v === 'clarify'
}

function totalTokens(costs: Record<string, StageCost>) {
  return Object.values(costs).reduce((s, c) => s + c.input + c.output, 0)
}

function totalCostUSD(costs: Record<string, StageCost>) {
  const tok = totalTokens(costs)
  return tok * 0.00000025 // haiku-level estimate
}

const SOURCE_ICON: Record<SourceType, string> = { DOC: 'log', DB: 'metric', CODE: 'code', ADO: 'ticket' }

// ─── Icons ────────────────────────────────────────────────────────────────────

function Icon({ name, size = 16, style }: { name: string; size?: number; style?: React.CSSProperties }) {
  const p = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, style }
  const paths: Record<string, React.ReactNode> = {
    scout: <><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/><path d="M11 7.5v7M7.5 11h7"/></>,
    list: <><path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3.5" cy="6" r="1"/><circle cx="3.5" cy="12" r="1"/><circle cx="3.5" cy="18" r="1"/></>,
    split: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M10 4v16"/></>,
    board: <><rect x="3" y="4" width="5" height="16" rx="1.5"/><rect x="9.5" y="4" width="5" height="11" rx="1.5"/><rect x="16" y="4" width="5" height="14" rx="1.5"/></>,
    coins: <><ellipse cx="9" cy="7" rx="6" ry="3"/><path d="M3 7v5c0 1.7 2.7 3 6 3s6-1.3 6-3V7"/><path d="M15 11.5c2.8-.2 6-1.4 6-3.5M21 8v5c0 1.7-2.7 3-6 3"/></>,
    check: <><path d="M20 6 9 17l-5-5"/></>,
    shield: <><path d="M12 3 5 6v5c0 4.2 2.9 7.7 7 8.8 4.1-1.1 7-4.6 7-8.8V6z"/><path d="m9.5 11.5 1.8 1.8 3.4-3.6"/></>,
    x: <><path d="M18 6 6 18M6 6l12 12"/></>,
    sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></>,
    moon: <><path d="M20 14.5A8 8 0 0 1 9.5 4a7 7 0 1 0 10.5 10.5z"/></>,
    arrowR: <><path d="M5 12h14M13 6l6 6-6 6"/></>,
    chevR: <><path d="m9 6 6 6-6 6"/></>,
    chevD: <><path d="m6 9 6 6 6-6"/></>,
    bolt: <><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></>,
    trace: <><path d="M4 6h16M4 6v12M4 18h16"/><circle cx="9" cy="6" r="1.4"/><circle cx="15" cy="12" r="1.4"/><path d="M9 7.4V12h6"/></>,
    commit: <><circle cx="12" cy="12" r="3.2"/><path d="M12 3v5.8M12 15.2V21"/></>,
    log: <><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 9h5M8 13h8M8 17h6"/></>,
    code: <><path d="m9 8-4 4 4 4M15 8l4 4-4 4"/></>,
    metric: <><path d="M4 19V5M4 19h16"/><path d="m7 15 3-4 3 2 4-6"/></>,
    ticket: <><path d="M4 8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2 2 2 0 0 0 0 4 2 2 0 0 1-2 2H6a2 2 0 0 1-2-2 2 2 0 0 0 0-4z" transform="rotate(90 12 12)"/><path d="M10 6v12" strokeDasharray="2 2"/></>,
    clock: <><circle cx="12" cy="12" r="8.5"/><path d="M12 8v4.5l3 1.8"/></>,
    spark: <><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18"/></>,
    menu: <><path d="M3 6h18M3 12h18M3 18h18"/></>,
    pulse: <><path d="M3 12h4l2.5-7 5 14 2.5-7H21"/></>,
    inbox: <><path d="M3 12h5l2 3h4l2-3h5"/><path d="M5 5h14l2 7v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-5z"/></>,
    timer: <><circle cx="12" cy="13" r="8"/><path d="M12 13V9M9 2h6"/></>,
    alert: <><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></>,
    flow: <><circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><path d="M7 12h4l6-5M7 12h4l6 5"/></>,
    db: <><ellipse cx="12" cy="7" rx="8" ry="3.5"/><path d="M4 7v5c0 1.9 3.6 3.5 8 3.5s8-1.6 8-3.5V7"/><path d="M4 12v5c0 1.9 3.6 3.5 8 3.5s8-1.6 8-3.5v-5"/></>,
  }
  return <svg {...p}>{paths[name] ?? null}</svg>
}

// ─── Shared atoms ─────────────────────────────────────────────────────────────

function Conf({ level }: { level: ConfKey }) {
  const label = { high: 'High', med: 'Medium', low: 'Low' }[level]
  return (
    <span className={`conf ${level}`}>
      <span className="dot" />{label}
    </span>
  )
}

function SourceChip({ src }: { src: string }) {
  return <span className="src" title={src}>{src.slice(0, 2).toUpperCase()}</span>
}

// ─── Evidence item ────────────────────────────────────────────────────────────

function EvidenceItem({ ev, first }: { ev: Evidence; first: boolean }) {
  const [open, setOpen] = useState(first && !!ev.passage)
  const icon = SOURCE_ICON[ev.source_type] ?? 'log'
  return (
    <div className="ev">
      <div className="ev-rail"><span className="ev-node"><Icon name={icon} size={13} /></span></div>
      <div className="ev-body">
        <div className="ev-head" onClick={() => ev.passage && setOpen((o) => !o)}>
          <div className="ev-head-text">
            <div className="ev-title">{ev.reference}</div>
            <div className="ev-meta">{ev.source_type}</div>
          </div>
          {ev.passage && <Icon name="chevD" size={15} style={{ color: 'var(--text-3)', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .18s', flex: 'none' }} />}
        </div>
        {ev.passage && open && <pre className="ev-snip mono">{ev.passage}</pre>}
      </div>
    </div>
  )
}

// ─── Detail body (shared by drawer + inline + review) ────────────────────────

function DetailBody({ t }: { t: Ticket }) {
  const verdict = t.triage?.verdict
  const ck = confKey(t)
  const stageTok = totalTokens(t.stage_costs)
  return (
    <>
      {verdict === 'clarify' ? (
        <section className="dt-block question-block">
          <div className="dt-block-head"><Icon name="spark" size={15} /><span>Clarifying question needed</span></div>
          <p className="dt-cause">{t.triage?.summary}</p>
          {t.triage?.clarifying_question && (
            <div className="qbox">
              <div className="qbox-text">{t.triage.clarifying_question}</div>
            </div>
          )}
        </section>
      ) : verdict === 'insufficient_signal' ? (
        <section className="dt-block">
          <div className="dt-block-head"><Icon name="alert" size={15} /><span>Insufficient signal</span></div>
          <p className="dt-cause" style={{ color: 'var(--text-3)' }}>{t.triage?.summary ?? 'Not enough information to investigate.'}</p>
        </section>
      ) : verdict === 'out_of_scope' ? (
        <section className="dt-block">
          <div className="dt-block-head"><Icon name="shield" size={15} /><span>Out of scope</span></div>
          <p className="dt-cause" style={{ color: 'var(--text-3)' }}>{t.triage?.summary}</p>
        </section>
      ) : (
        <section className="dt-block">
          <div className="dt-block-head">
            <Icon name="shield" size={15} /><span>Proposed root cause</span>
            <span style={{ flex: 1 }} />
            {t.diagnosis?.confidence && <Conf level={ck} />}
          </div>
          {t.diagnosis?.root_cause
            ? <p className="dt-cause">{t.diagnosis.root_cause}</p>
            : <p className="dt-cause" style={{ color: 'var(--text-3)' }}>No root cause identified.</p>}
          {t.triage?.summary && (
            <div className="dt-suggest">
              <span className="dt-suggest-label">Triage summary</span>
              <span>{t.triage.summary}</span>
            </div>
          )}
        </section>
      )}

      {t.diagnosis && t.diagnosis.evidence.length > 0 && (
        <section className="dt-block">
          <div className="dt-block-head">
            <Icon name="trace" size={15} /><span>Evidence trail</span>
            <span className="dt-count">{t.diagnosis.evidence.length}</span>
          </div>
          <div className="ev-list">
            {t.diagnosis.evidence.map((ev, i) => <EvidenceItem key={i} ev={ev} first={i === 0} />)}
          </div>
        </section>
      )}

      {Object.keys(t.stage_costs).length > 0 && (
        <section className="dt-block">
          <div className="dt-block-head">
            <Icon name="coins" size={15} /><span>Stage costs</span>
            <span style={{ flex: 1 }} />
            <span className="dt-cost-total">{(stageTok / 1000).toFixed(1)}k tokens</span>
          </div>
          {Object.entries(t.stage_costs).map(([stage, cost]) => (
            <div key={stage} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '3px 0', color: 'var(--text-2)' }}>
              <span>{stage}</span>
              <span className="mono tnum" style={{ color: 'var(--text-3)' }}>{((cost.input + cost.output) / 1000).toFixed(1)}k tok</span>
            </div>
          ))}
        </section>
      )}
    </>
  )
}

// ─── Ticket detail drawer ─────────────────────────────────────────────────────

function TicketDrawer({ t, decision, onClose, onApprove, onDismiss, nav }: {
  t: Ticket; decision: string; onClose: () => void
  onApprove: (id: string) => void; onDismiss: (id: string) => void
  nav: { prev: () => void; next: () => void } | null
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  const decided = decision && decision !== 'proposed'
  const isClarify = t.triage?.verdict === 'clarify'
  return (
    <div className="drawer-scrim" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div className="drawer-head-l">
            <SourceChip src={t.source_system} />
            <span className="mono tk-id">{t.id}</span>
          </div>
          <div className="drawer-head-r">
            {nav && <>
              <button className="icon-btn" onClick={nav.prev} title="Previous"><Icon name="chevR" size={16} style={{ transform: 'rotate(180deg)' }} /></button>
              <button className="icon-btn" onClick={nav.next} title="Next"><Icon name="chevR" size={16} /></button>
            </>}
            <button className="icon-btn" onClick={onClose} title="Close (Esc)"><Icon name="x" size={16} /></button>
          </div>
        </div>
        <div className="drawer-body">
          <h2 className="dt-title big">{t.title}</h2>
          <DetailBody t={t} />
        </div>
        <div className="drawer-foot">
          {!decided ? (
            <>
              <button className="btn dismiss" onClick={() => { onDismiss(t.id); onClose() }}><Icon name="x" size={15} /> Dismiss</button>
              <div style={{ flex: 1 }} />
              {isClarify
                ? <button className="btn accent" onClick={() => { onApprove(t.id); onClose() }}><Icon name="check" size={15} /> Acknowledge</button>
                : <button className="btn approve" onClick={() => { onApprove(t.id); onClose() }}><Icon name="check" size={15} /> Approve</button>}
            </>
          ) : (
            <span className={`decided-chip ${decision === 'approve' ? 'approved' : 'dismissed'} lg`}>
              <Icon name={decision === 'approve' ? 'check' : 'x'} size={15} />
              {decision === 'approve' ? 'Approved' : 'Dismissed'}
            </span>
          )}
        </div>
      </aside>
    </div>
  )
}

// ─── Inline detail (split view) ───────────────────────────────────────────────

function TicketDetailInline({ t, decision, onApprove, onDismiss }: {
  t: Ticket; decision: string
  onApprove: (id: string) => void; onDismiss: (id: string) => void
}) {
  const decided = decision && decision !== 'proposed'
  const isClarify = t.triage?.verdict === 'clarify'
  return (
    <div className="dt-inline">
      <div className="dt-inline-head">
        <SourceChip src={t.source_system} />
        <span className="mono tk-id">{t.id}</span>
        <span style={{ flex: 1 }} />
        {!decided && <Conf level={confKey(t)} />}
      </div>
      <h2 className="dt-title">{t.title}</h2>
      <div className="dt-scroll"><DetailBody t={t} /></div>
      {!decided ? (
        <div className="dt-actions">
          <button className="btn dismiss" onClick={() => onDismiss(t.id)}><Icon name="x" size={15} /> Dismiss</button>
          {isClarify
            ? <button className="btn accent" onClick={() => onApprove(t.id)}><Icon name="check" size={15} /> Acknowledge</button>
            : <button className="btn approve" onClick={() => onApprove(t.id)}><Icon name="check" size={15} /> Approve</button>}
        </div>
      ) : (
        <div className="dt-actions decided">
          <span className={`decided-chip ${decision === 'approve' ? 'approved' : 'dismissed'} lg`}>
            <Icon name={decision === 'approve' ? 'check' : 'x'} size={15} />
            {decision === 'approve' ? 'Approved' : 'Dismissed'}
          </span>
        </div>
      )}
    </div>
  )
}

// ─── Review Mode ──────────────────────────────────────────────────────────────

function ReviewMode({ tickets, decisions, onApprove, onDismiss, onClose }: {
  tickets: Ticket[]; decisions: Record<string, string>
  onApprove: (id: string) => void; onDismiss: (id: string) => void
  onClose: () => void
}) {
  const queue = useMemo(() => tickets.filter((t) => isVisible(t) && !decisions[t.id]), [])
  const [idx, setIdx] = useState(0)
  const [flash, setFlash] = useState<string | null>(null)
  const done = idx >= queue.length
  const t = queue[idx]

  const advance = useCallback((dir: string) => {
    setFlash(dir)
    setTimeout(() => { setIdx((i) => i + 1); setFlash(null) }, 180)
  }, [])

  const approve = useCallback(() => { if (t) { onApprove(t.id); advance('approve') } }, [t, onApprove, advance])
  const dismiss = useCallback(() => { if (t) { onDismiss(t.id); advance('dismiss') } }, [t, onDismiss, advance])

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape') return onClose()
      if (done) return
      if (e.key === 'a' || e.key === 'A') { e.preventDefault(); approve() }
      else if (e.key === 'x' || e.key === 'X') { e.preventDefault(); dismiss() }
      else if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); setIdx((i) => Math.min(i + 1, queue.length)) }
      else if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)) }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [approve, dismiss, onClose, done, queue.length])

  const progress = queue.length ? Math.round((Math.min(idx, queue.length) / queue.length) * 100) : 100

  return (
    <div className="review-scrim">
      <div className="review-top">
        <div className="review-top-l">
          <span className="review-badge"><Icon name="bolt" size={14} /> Review queue</span>
          <span className="review-count mono tnum">{Math.min(idx + (done ? 0 : 1), queue.length)} / {queue.length}</span>
        </div>
        <div className="review-progress"><div className="review-progress-fill" style={{ width: `${progress}%` }} /></div>
        <button className="icon-btn" onClick={onClose} title="Exit (Esc)"><Icon name="x" size={16} /></button>
      </div>

      {done ? (
        <div className="review-done fade-up">
          <div className="review-done-ring"><Icon name="check" size={40} /></div>
          <h2>Queue cleared</h2>
          <p>You reviewed {queue.length} tickets this session.</p>
          <button className="btn accent" onClick={onClose}><Icon name="board" size={15} /> Back to dashboard</button>
        </div>
      ) : (
        <div className={`review-stage ${flash ? 'flash-' + flash : ''}`}>
          <div className="review-card" key={t.id}>
            <div className="review-card-head">
              <SourceChip src={t.source_system} />
              <span className="mono tk-id">{t.id}</span>
              <span style={{ flex: 1 }} />
              <Conf level={confKey(t)} />
            </div>
            <h2 className="review-title">{t.title}</h2>
            <div className="review-card-scroll"><DetailBody t={t} /></div>
          </div>
          <div className="review-actions">
            <button className="rev-act dismiss" onClick={dismiss}>
              <span className="kbd">X</span>
              <span><Icon name="x" size={16} /> Dismiss</span>
            </button>
            <div className="rev-nav"><span className="rev-nav-hint">J/K to skip · Esc to exit</span></div>
            <button className="rev-act approve" onClick={approve}>
              <span>{isNeedsInput(t) ? <><Icon name="check" size={16} /> Acknowledge</> : <><Icon name="check" size={16} /> Approve</>}</span>
              <span className="kbd" style={{ background: 'rgba(0,0,0,.18)', borderColor: 'rgba(0,0,0,.2)', color: '#04130c' }}>A</span>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Board layout ─────────────────────────────────────────────────────────────

function BoardLayout({ tickets, decisions, selected, onOpen }: {
  tickets: Ticket[]; decisions: Record<string, string>; selected: string | null; onOpen: (id: string) => void
}) {
  const cols = [
    { k: 'high' as ConfKey, label: 'High confidence', hint: 'ready to approve' },
    { k: 'med' as ConfKey, label: 'Medium', hint: 'worth a look' },
    { k: 'low' as ConfKey, label: 'Low / needs input', hint: 'evidence gaps' },
  ]
  return (
    <div className="board">
      {cols.map((col) => {
        const items = tickets.filter((t) => confKey(t) === col.k)
        return (
          <div key={col.k} className="board-col">
            <div className="board-col-head">
              <span className={`board-dot ${col.k}`} />
              <span className="board-col-title">{col.label}</span>
              <span className="board-col-n mono tnum">{items.length}</span>
              <span className="board-col-hint">{col.hint}</span>
            </div>
            <div className="board-col-body">
              {items.map((t) => {
                const dec = decisions[t.id]
                const decided = !!dec
                return (
                  <div key={t.id} className={`tk-card ${selected === t.id ? 'active' : ''} ${decided ? 'decided' : ''}`} onClick={() => onOpen(t.id)}>
                    <div className="tk-card-top">
                      <SourceChip src={t.source_system} />
                      <span className="mono tk-id">{t.id}</span>
                      {isNeedsInput(t) && <span className="tk-needs-input">needs input</span>}
                      <span style={{ flex: 1 }} />
                      {decided && <Icon name={dec.startsWith('approve') ? 'check' : 'x'} size={14} style={{ color: dec.startsWith('approve') ? 'var(--high)' : 'var(--text-3)' }} />}
                    </div>
                    <div className="tk-card-title">{t.title}</div>
                    <div className="tk-card-cause">{t.diagnosis?.root_cause ?? t.triage?.summary ?? ''}</div>
                    <div className="tk-card-foot">
                      <Conf level={col.k} />
                      <span className="mono tnum" style={{ fontSize: 11, color: 'var(--text-faint)' }}>{(totalTokens(t.stage_costs) / 1000).toFixed(1)}k tok</span>
                    </div>
                  </div>
                )
              })}
              {items.length === 0 && <div className="board-empty">— none —</div>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Split layout ─────────────────────────────────────────────────────────────

function SplitLayout({ tickets, decisions, selected, onOpen, onApprove, onDismiss }: {
  tickets: Ticket[]; decisions: Record<string, string>; selected: string | null
  onOpen: (id: string) => void; onApprove: (id: string) => void; onDismiss: (id: string) => void
}) {
  const sel = tickets.find((t) => t.id === selected) ?? tickets[0]
  return (
    <div className="split-wrap">
      <div className="split-list">
        {tickets.map((t) => (
          <div key={t.id} className={`split-item ${sel?.id === t.id ? 'on' : ''}`} onClick={() => onOpen(t.id)}>
            <div className="split-item-top">
              <SourceChip src={t.source_system} />
              <span className="mono tk-id">{t.id}</span>
              <span style={{ flex: 1 }} />
              <Conf level={confKey(t)} />
            </div>
            <div className="split-item-title">{t.title}</div>
          </div>
        ))}
      </div>
      <div className="split-detail">
        {sel && <TicketDetailInline t={sel} decision={decisions[sel.id] ?? 'proposed'} onApprove={onApprove} onDismiss={onDismiss} />}
      </div>
    </div>
  )
}

// ─── Tickets View (Triage queue) ──────────────────────────────────────────────

function TicketsView() {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [decisions, setDecisions] = useState<Record<string, string>>({})
  const [layout, setLayout] = useState<'board' | 'split'>('board')
  const [filter, setFilter] = useState<'all' | 'high' | 'review' | 'question'>('all')
  const [selected, setSelected] = useState<string | null>(null)
  const [drawer, setDrawer] = useState<string | null>(null)
  const [reviewing, setReviewing] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const res = await fetch(`${API}/tickets`)
      if (!res.ok) throw new Error(`API ${res.status}`)
      setTickets(await res.json())
      setError(null)
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  async function act(id: string, action: string) {
    await fetch(`${API}/tickets/${encodeURIComponent(id)}/review?action=${action}`, { method: 'POST' })
    setDecisions((d) => ({ ...d, [id]: action }))
  }
  const approve = useCallback((id: string) => {
    const t = tickets.find((x) => x.id === id)
    act(id, t?.triage?.verdict === 'clarify' ? 'acknowledge' : 'approve')
  }, [tickets])
  const dismiss = useCallback((id: string) => act(id, 'dismiss_incorrect'), [])

  const open = useCallback((id: string) => { setSelected(id); setDrawer(id) }, [])

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName?.toLowerCase()
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return
      if ((e.key === 'r' || e.key === 'R') && !reviewing && !drawer) {
        e.preventDefault(); if (pending > 0) setReviewing(true)
      }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [reviewing, drawer])

  const visible = useMemo(() => tickets.filter(isVisible), [tickets])
  const pending = visible.filter((t) => !decisions[t.id]).length

  const counts = useMemo(() => ({
    all: visible.length,
    high: visible.filter((t) => confKey(t) === 'high').length,
    review: visible.filter((t) => t.triage?.verdict === 'investigate' && confKey(t) !== 'high').length,
    question: visible.filter(isNeedsInput).length,
  }), [visible])

  const filtered = useMemo(() => {
    if (filter === 'high') return visible.filter((t) => confKey(t) === 'high')
    if (filter === 'review') return visible.filter((t) => t.triage?.verdict === 'investigate' && confKey(t) !== 'high')
    if (filter === 'question') return visible.filter(isNeedsInput)
    return visible
  }, [visible, filter])

  const drawerTicket = drawer ? tickets.find((t) => t.id === drawer) ?? null : null
  const drawerNav = useMemo(() => {
    if (!drawer) return null
    const ids = filtered.map((t) => t.id)
    const i = ids.indexOf(drawer)
    return {
      prev: () => setDrawer(ids[(i - 1 + ids.length) % ids.length]),
      next: () => setDrawer(ids[(i + 1) % ids.length]),
    }
  }, [drawer, filtered])

  const filterTabs = [
    { k: 'all', label: 'All', n: counts.all },
    { k: 'high', label: 'High confidence', n: counts.high },
    { k: 'review', label: 'Needs a look', n: counts.review },
    { k: 'question', label: 'Needs input', n: counts.question },
  ] as const

  return (
    <div>
      {/* Run header */}
      <div className="run-head">
        <div className="run-head-l">
          <div className="run-title-row">
            <h1 className="run-title">Triage run</h1>
            <span className="run-live"><span className="run-live-dot" />complete</span>
          </div>
          <div className="run-sub mono">{tickets.length} tickets fetched</div>
        </div>
        <div className="run-head-stats">
          <div className="rh-stat"><span className="rh-num mono tnum">{tickets.length}</span><span className="rh-lbl">total</span></div>
          <div className="rh-arrow"><Icon name="arrowR" size={14} /></div>
          <div className="rh-stat"><span className="rh-num mono tnum">{visible.length}</span><span className="rh-lbl">triaged</span></div>
          <div className="rh-divider" />
          <div className="rh-stat"><span className="rh-num mono tnum" style={{ color: 'var(--accent)' }}>{pending}</span><span className="rh-lbl">pending</span></div>
        </div>
        <button className="btn accent review-cta" onClick={() => pending > 0 && setReviewing(true)} disabled={pending === 0}>
          <Icon name="bolt" size={15} /> Review queue <span className="kbd" style={{ marginLeft: 2 }}>R</span>
        </button>
      </div>

      {/* Filter bar */}
      <div className="filterbar">
        <div className="filter-tabs">
          {filterTabs.map((tab) => (
            <button key={tab.k} className={`filter-tab ${filter === tab.k ? 'on' : ''}`} onClick={() => setFilter(tab.k)}>
              {tab.label}<span className="filter-n mono tnum">{tab.n}</span>
            </button>
          ))}
        </div>
        <div className="layout-switch">
          {([['board', 'board', 'Board'], ['split', 'split', 'Split']] as const).map(([k, ic, lbl]) => (
            <button key={k} className={`lay-btn ${layout === k ? 'on' : ''}`} onClick={() => setLayout(k)}>
              <Icon name={ic} size={15} />{lbl}
            </button>
          ))}
        </div>
      </div>

      {loading && <p style={{ color: 'var(--text-3)', fontSize: 13 }}>Loading…</p>}
      {error && (
        <div style={{ padding: '16px', border: '1px solid var(--low)', borderRadius: 'var(--radius)', background: 'var(--low-soft)', color: 'var(--low)', fontSize: 13 }}>
          Could not reach the Scout API: {error}
        </div>
      )}
      {!loading && !error && tickets.length === 0 && (
        <div className="empty-state">No tickets yet. Run the batch to populate.</div>
      )}

      {filtered.length > 0 && (
        layout === 'board'
          ? <BoardLayout tickets={filtered} decisions={decisions} selected={selected} onOpen={open} />
          : <SplitLayout tickets={filtered} decisions={decisions} selected={selected} onOpen={open} onApprove={approve} onDismiss={dismiss} />
      )}

      {drawerTicket && (
        <TicketDrawer t={drawerTicket} decision={decisions[drawerTicket.id] ?? 'proposed'}
          onClose={() => setDrawer(null)} onApprove={approve} onDismiss={dismiss} nav={drawerNav} />
      )}
      {reviewing && (
        <ReviewMode tickets={tickets} decisions={decisions} onApprove={approve} onDismiss={dismiss} onClose={() => setReviewing(false)} />
      )}
    </div>
  )
}

// ─── Overview View ────────────────────────────────────────────────────────────

function OverviewView({ tickets, onGoTriage }: { tickets: Ticket[]; onGoTriage: () => void }) {
  const total = tickets.length
  const investigated = tickets.filter((t) => t.triage?.verdict === 'investigate').length
  const clarify = tickets.filter((t) => t.triage?.verdict === 'clarify').length
  const outOfScope = tickets.filter((t) => t.triage?.verdict === 'out_of_scope').length
  const insufficient = tickets.filter((t) => t.triage?.verdict === 'insufficient_signal').length
  const pending = tickets.filter((t) => isVisible(t) && !t.review).length
  const highConf = tickets.filter((t) => t.diagnosis?.confidence === 'High').length

  const disposition = [
    { label: 'Investigate', n: investigated, color: 'var(--accent)' },
    { label: 'Clarify', n: clarify, color: 'var(--med)' },
    { label: 'Out of scope', n: outOfScope, color: 'var(--text-faint)' },
    { label: 'Insufficient', n: insufficient, color: 'var(--border-strong)' },
  ].filter((d) => d.n > 0)

  return (
    <div>
      <div className="view-head">
        <div>
          <h1 className="view-title">Overview</h1>
          <p className="view-sub">Summary of the last triage run across all tickets.</p>
        </div>
        <button className="btn accent" onClick={onGoTriage}>
          <Icon name="bolt" size={15} /> Open triage queue
          {pending > 0 && <span style={{ background: 'rgba(255,255,255,.22)', padding: '1px 8px', borderRadius: 999, fontSize: 12, fontWeight: 700 }}>{pending}</span>}
        </button>
      </div>

      <div className="ov-kpis">
        {[
          { icon: 'inbox', label: 'Total tickets', value: total },
          { icon: 'shield', label: 'Investigated', value: investigated },
          { icon: 'spark', label: 'High confidence', value: highConf, accent: 'var(--high)' },
          { icon: 'bolt', label: 'Awaiting review', value: pending, accent: 'var(--accent)' },
        ].map((k) => (
          <div key={k.label} className="card ov-kpi">
            <div className="ov-kpi-top">
              <span className="ov-kpi-label">{k.label}</span>
              <Icon name={k.icon} size={16} />
            </div>
            <div className="ov-kpi-num mono tnum" style={k.accent ? { color: k.accent } : undefined}>{k.value}</div>
          </div>
        ))}
      </div>

      <div className="ov-grid">
        <div className="card ov-card">
          <div className="ov-card-head"><Icon name="pulse" size={15} /><span className="ov-card-title">Verdict breakdown</span></div>
          <div className="ov-legend">
            {disposition.map((d) => (
              <div key={d.label} className="ov-legend-row">
                <span className="ov-legend-dot" style={{ background: d.color }} />
                <span className="ov-legend-lbl">{d.label}</span>
                <span className="ov-legend-val">{d.n}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card ov-card">
          <div className="ov-card-head"><Icon name="shield" size={15} /><span className="ov-card-title">Confidence distribution</span></div>
          {(['High', 'Medium', 'Low', 'Insufficient'] as ConfLevel[]).map((level) => {
            const n = tickets.filter((t) => t.diagnosis?.confidence === level).length
            const ck: ConfKey = level === 'High' ? 'high' : level === 'Medium' ? 'med' : 'low'
            const colors = { high: 'var(--high)', med: 'var(--med)', low: 'var(--low)' }
            return (
              <div key={level} className="ov-legend-row" style={{ marginBottom: 10 }}>
                <span className="ov-legend-dot" style={{ background: colors[ck] }} />
                <span className="ov-legend-lbl">{level}</span>
                <div style={{ flex: 1, height: 6, background: 'var(--panel-3)', borderRadius: 999, overflow: 'hidden', margin: '0 12px' }}>
                  <div style={{ height: '100%', width: `${investigated ? (n / investigated) * 100 : 0}%`, background: colors[ck], borderRadius: 999, transition: 'width .7s' }} />
                </div>
                <span className="ov-legend-val">{n}</span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ─── Cost View ────────────────────────────────────────────────────────────────

function CostView({ tickets }: { tickets: Ticket[] }) {
  const stageAgg = useMemo(() => {
    const m: Record<string, { tokens: number; cost: number; runs: number }> = {}
    tickets.forEach((t) =>
      Object.entries(t.stage_costs).forEach(([stage, cost]) => {
        m[stage] = m[stage] ?? { tokens: 0, cost: 0, runs: 0 }
        m[stage].tokens += cost.input + cost.output
        m[stage].cost += (cost.input + cost.output) * 0.00000025
        m[stage].runs += 1
      })
    )
    return Object.entries(m).sort((a, b) => b[1].tokens - a[1].tokens)
  }, [tickets])

  const maxTokens = Math.max(...stageAgg.map(([, s]) => s.tokens), 1)
  const totalTok = tickets.reduce((s, t) => s + totalTokens(t.stage_costs), 0)
  const totalCost = tickets.reduce((s, t) => s + totalCostUSD(t.stage_costs), 0)

  const ranked = [...tickets].sort((a, b) => totalTokens(b.stage_costs) - totalTokens(a.stage_costs)).slice(0, 10)
  const maxTok = Math.max(...ranked.map((t) => totalTokens(t.stage_costs)), 1)

  return (
    <div>
      <div className="view-head">
        <div>
          <h1 className="view-title">Token economics</h1>
          <p className="view-sub">How Scout spent its budget across this triage run.</p>
        </div>
      </div>

      {tickets.length === 0 ? (
        <div className="empty-state">No tickets yet. Run the batch to see cost data.</div>
      ) : (
        <>
          <div className="card cost-hero" style={{ marginBottom: 16 }}>
            <div className="cost-hero-main">
              <div className="cost-hero-spent">
                <span className="cost-hero-label">Estimated spend this run</span>
                <span className="cost-hero-num mono tnum">${totalCost.toFixed(4)}</span>
                <span className="cost-hero-meta mono">{(totalTok / 1000).toFixed(1)}k tokens · {tickets.length} tickets</span>
              </div>
            </div>
          </div>

          {stageAgg.length > 0 && (
            <div className="card cost-stages">
              <div className="dt-block-head" style={{ marginBottom: 16 }}><Icon name="trace" size={15} /><span>Cost by stage</span></div>
              <div className="stage-rows">
                {stageAgg.map(([stage, s]) => (
                  <div key={stage} className="stage-row">
                    <span className="stage-name">{stage}</span>
                    <span className="stage-tok">{(s.tokens / 1000).toFixed(1)}k</span>
                    <div className="stage-bar-track">
                      <div className="stage-bar-fill" style={{ width: `${(s.tokens / maxTokens) * 100}%` }} />
                    </div>
                    <span className="stage-cost">${s.cost.toFixed(4)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {ranked.length > 0 && (
            <div className="card cost-stages" style={{ marginTop: 16 }}>
              <div className="dt-block-head" style={{ marginBottom: 16 }}><Icon name="ticket" size={15} /><span>Most expensive tickets</span></div>
              <div className="waterfall">
                {ranked.map((t) => {
                  const tok = totalTokens(t.stage_costs)
                  return (
                    <div key={t.id} className="wf-row">
                      <span className="mono tk-id">{t.id}</span>
                      <span className="wf-title">{t.title}</span>
                      <div style={{ height: 8, background: 'var(--panel-3)', borderRadius: 999, overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${(tok / maxTok) * 100}%`, background: 'var(--accent)', borderRadius: 999 }} />
                      </div>
                      <span className="wf-cost">{(tok / 1000).toFixed(1)}k</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ─── Validation View ──────────────────────────────────────────────────────────

function ValidationView() {
  return (
    <div>
      <div className="view-head">
        <div>
          <h1 className="view-title">Validation</h1>
          <p className="view-sub">Accuracy metrics against a curated set of historical tickets with known root causes.</p>
        </div>
      </div>
      <div className="card" style={{ padding: 48, textAlign: 'center' }}>
        <div style={{ fontSize: 40, marginBottom: 16 }}>📋</div>
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 8 }}>No validation data yet</div>
        <p style={{ fontSize: 13, color: 'var(--text-3)', maxWidth: 400, margin: '0 auto' }}>
          Build a Validation Set — 15–20 historical tickets with confirmed root causes — to measure Scout's accuracy here.
        </p>
      </div>
    </div>
  )
}

// ─── Database view ────────────────────────────────────────────────────────────

const DB_TABLES = [
  { name: 'tickets', label: 'Tickets' },
  { name: 'triage_results', label: 'Triage results' },
  { name: 'diagnoses', label: 'Diagnoses' },
  { name: 'evidence_items', label: 'Evidence items' },
  { name: 'stage_counts', label: 'Stage counts' },
  { name: 'review_actions', label: 'Review actions' },
]

interface DbResult {
  table: string; columns: string[]; rows: Record<string, unknown>[]
  total: number; limit: number; offset: number
}

function DbCell({ val, col }: { val: unknown; col: string }) {
  const [expanded, setExpanded] = useState(false)
  if (val === null || val === undefined) return <span className="db-null">null</span>
  const s = String(val)
  const isId = col === 'id' || col.endsWith('_id')
  const isLong = s.length > 80
  return (
    <span
      className={isLong ? `db-cell-long ${expanded ? 'expanded' : ''}` : (isId ? 'pk' : '')}
      title={isLong && !expanded ? s : undefined}
      onClick={isLong ? () => setExpanded((x) => !x) : undefined}
      style={isLong ? { cursor: 'pointer' } : undefined}
    >
      {s}
    </span>
  )
}

function DatabaseView() {
  const [active, setActive] = useState('tickets')
  const [data, setData] = useState<DbResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [counts, setCounts] = useState<Record<string, number>>({})

  useEffect(() => {
    DB_TABLES.forEach(({ name }) => {
      fetch(`${API}/db/${name}?limit=0&offset=0`)
        .then((r) => r.json())
        .then((d: DbResult) => setCounts((c) => ({ ...c, [name]: d.total })))
        .catch(() => {})
    })
  }, [])

  useEffect(() => {
    setLoading(true)
    setData(null)
    fetch(`${API}/db/${active}`)
      .then((r) => r.json())
      .then((d: DbResult) => { setData(d); setCounts((c) => ({ ...c, [active]: d.total })) })
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [active])

  return (
    <div>
      <div className="view-head">
        <div>
          <h1 className="view-title">Database</h1>
          <p className="view-sub">Live read-only view of the Scout SQLite database.</p>
        </div>
      </div>
      <div className="db-wrap">
        <div className="db-tables">
          {DB_TABLES.map(({ name, label }) => (
            <button key={name} className={`db-table-btn ${active === name ? 'on' : ''}`}
              onClick={() => setActive(name)}>
              {label}
              {counts[name] != null && <span className="db-n">{counts[name]}</span>}
            </button>
          ))}
        </div>

        <div className="card db-panel">
          <div className="db-panel-head">
            <span className="db-panel-title">{active}</span>
            {data && <span className="db-panel-meta">{data.total} row{data.total !== 1 ? 's' : ''}</span>}
            {loading && <span className="db-panel-meta">Loading…</span>}
          </div>

          {data && data.rows.length === 0 && (
            <div className="db-empty">No rows yet in <code>{active}</code></div>
          )}

          {data && data.rows.length > 0 && (
            <>
              <div className="db-scroll">
                <table className="db-table">
                  <thead>
                    <tr>{data.columns.map((c) => <th key={c}>{c}</th>)}</tr>
                  </thead>
                  <tbody>
                    {data.rows.map((row, i) => (
                      <tr key={i}>
                        {data.columns.map((c) => (
                          <td key={c} className={c === 'id' ? 'pk' : c.endsWith('_id') ? 'fk' : ''}>
                            <DbCell val={row[c]} col={c} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {data.total > data.rows.length && (
                <div className="db-pagination">
                  Showing first {data.rows.length} of {data.total} rows
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────

const NAV: { k: Route; label: string; icon: string }[] = [
  { k: 'overview', label: 'Overview', icon: 'pulse' },
  { k: 'dashboard', label: 'Triage queue', icon: 'list' },
  { k: 'cost', label: 'Token economics', icon: 'coins' },
  { k: 'validation', label: 'Validation', icon: 'shield' },
  { k: 'flow', label: 'Investigation Flow', icon: 'flow' },
  { k: 'db', label: 'Database', icon: 'db' },
]
const NAV_TITLE: Record<Route, string> = {
  overview: 'Overview', dashboard: 'Triage queue', cost: 'Token economics',
  validation: 'Validation', flow: 'Investigation Flow', db: 'Database',
}

function Sidebar({ route, setRoute, theme, setTheme, pending, onNav }: {
  route: Route; setRoute: (r: Route) => void
  theme: string; setTheme: (t: string) => void
  pending: number; onNav?: () => void
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark"><Icon name="scout" size={19} /></div>
        <div>
          <div className="brand-name">Scout</div>
          <div className="brand-tag">overnight triage</div>
        </div>
      </div>
      <nav className="nav">
        <div className="nav-label">Workspace</div>
        {NAV.map((n) => (
          <button key={n.k} className={`nav-item ${route === n.k ? 'on' : ''}`}
            onClick={() => { setRoute(n.k); onNav?.() }}>
            <Icon name={n.icon} size={17} />
            {n.label}
            {n.k === 'dashboard' && pending > 0 && <span className="nav-n">{pending}</span>}
          </button>
        ))}
      </nav>
      <div className="sidebar-foot">
        <div className="theme-toggle">
          <button className={`theme-opt ${theme === 'dark' ? 'on' : ''}`} onClick={() => setTheme('dark')}><Icon name="moon" size={14} /> Dark</button>
          <button className={`theme-opt ${theme === 'light' ? 'on' : ''}`} onClick={() => setTheme('light')}><Icon name="sun" size={14} /> Light</button>
        </div>
      </div>
    </aside>
  )
}

// ─── App shell ────────────────────────────────────────────────────────────────

const LS = 'scout_ui_v1'
function loadPref() { try { return JSON.parse(localStorage.getItem(LS) ?? '{}') } catch { return {} } }
function savePref(o: object) { try { localStorage.setItem(LS, JSON.stringify(o)) } catch {} }

export default function App() {
  const pref = loadPref()
  const [route, setRoute] = useState<Route>('overview')
  const [theme, setThemeRaw] = useState<string>(pref.theme ?? 'dark')
  const [navOpen, setNavOpen] = useState(true)
  const [tickets, setTickets] = useState<Ticket[]>([])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    savePref({ theme })
  }, [theme])

  useEffect(() => {
    fetch(`${API}/tickets`).then((r) => r.json()).then(setTickets).catch(() => {})
  }, [])

  const setTheme = (t: string) => setThemeRaw(t)
  const pending = tickets.filter((t) => isVisible(t) && !t.review).length

  return (
    <div className={`app ${navOpen ? '' : 'nav-closed'}`}>
      <Sidebar route={route} setRoute={setRoute} theme={theme} setTheme={setTheme} pending={pending}
        onNav={() => { if (window.innerWidth <= 760) setNavOpen(false) }} />
      <main className="main">
        <div className="topbar">
          <div className="topbar-inner">
            <button className="icon-btn hamburger" onClick={() => setNavOpen((o) => !o)} title="Toggle menu">
              <Icon name="menu" size={18} />
            </button>
            <div className="brand-mark sm"><Icon name="scout" size={15} /></div>
            <span className="topbar-name">Scout</span>
            <span className="topbar-sep" />
            <span className="topbar-title">{NAV_TITLE[route]}</span>
          </div>
        </div>

        {route === 'flow' ? (
          <FlowEditor />
        ) : (
          <div className="main-inner">
            {route === 'overview' && <OverviewView tickets={tickets} onGoTriage={() => setRoute('dashboard')} />}
            {route === 'dashboard' && <TicketsView />}
            {route === 'cost' && <CostView tickets={tickets} />}
            {route === 'validation' && <ValidationView />}
            {route === 'db' && <DatabaseView />}
          </div>
        )}
      </main>
    </div>
  )
}
