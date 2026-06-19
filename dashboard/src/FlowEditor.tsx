import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap, addEdge,
  useNodesState, useEdgesState, Handle, Position,
  type Node, type Edge, type Connection, type NodeTypes, type OnConnect,
  ReactFlowProvider, useReactFlow,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

type McpType = 'knowledge_graph' | 'code_graph' | 'oracle' | 'azure_devops'
type NodeKind = 'tool' | 'branch' | 'conclude'
type Condition = 'gte_high' | 'gte_medium' | 'eq_low' | 'eq_insufficient' | 'always'

interface ToolNodeConfig { mcp: McpType; label: string }
interface BranchEdge { target_node_id: string; condition: Condition }
interface FlowNode { id: string; type: NodeKind; config: ToolNodeConfig | null; edges: BranchEdge[] }
interface InvestigationFlow { nodes: FlowNode[]; entry_node_id: string }

const MCP_LABELS: Record<McpType, string> = {
  knowledge_graph: 'Knowledge Graph',
  code_graph: 'Code Graph',
  oracle: 'Oracle',
  azure_devops: 'Azure DevOps',
}

const MCP_DESC: Record<McpType, string> = {
  knowledge_graph: 'Semantic search over the incident knowledge base and runbooks.',
  code_graph: 'Static analysis and dependency traversal across the source repository.',
  oracle: 'Historical incident lookup and pattern matching against past events.',
  azure_devops: 'Queries work items, PRs, and recent pipeline runs from Azure DevOps.',
}

const MCP_ACCENT: Record<McpType, string> = {
  knowledge_graph: '#5b8cff',
  code_graph: '#2fb574',
  oracle: '#06b6d4',
  azure_devops: '#818cf8',
}

const CONDITION_LABELS: Record<Condition, string> = {
  gte_high: '≥ High', gte_medium: '≥ Medium', eq_low: '= Low',
  eq_insufficient: '= Insufficient', always: 'Always',
}
const CONDITION_DESC: Record<Condition, string> = {
  gte_high: 'Fires when triage confidence is High',
  gte_medium: 'Fires when confidence is Medium or High',
  eq_low: 'Fires when confidence is exactly Low',
  eq_insufficient: 'Fires when there was insufficient signal',
  always: 'Always follows this edge regardless of confidence',
}
const CONDITIONS: Condition[] = ['gte_high', 'gte_medium', 'eq_low', 'eq_insufficient', 'always']

interface McpServerStatus { url: string; reachable: boolean }
type McpStatus = Record<string, McpServerStatus>
const FlowStatusContext = createContext<McpStatus>({})

interface ToolNodeData { mcp: McpType; label: string; [key: string]: unknown }
interface BranchNodeData { [key: string]: unknown }
interface ConcludeNodeData { [key: string]: unknown }

const handleStyle: React.CSSProperties = {
  width: 10, height: 10, borderRadius: '50%',
  background: 'var(--border-strong)', border: '2px solid var(--panel)',
  transition: 'background .14s',
}

function ToolNodeComponent({ data }: { data: ToolNodeData }) {
  const status = useContext(FlowStatusContext)
  const serverStatus = status[data.mcp]
  const unreachable = serverStatus !== undefined && !serverStatus.reachable
  const accent = MCP_ACCENT[data.mcp] ?? 'var(--border-strong)'
  return (
    <div style={{ position: 'relative', background: 'var(--panel)', border: `2px solid ${accent}`, borderRadius: 10, padding: '10px 14px', minWidth: 160, boxShadow: 'var(--shadow)' }}>
      <Handle type="target" position={Position.Top} style={handleStyle} />
      {unreachable && (
        <span title="MCP server not running — click the node to see connection details" style={{ position: 'absolute', top: -8, right: -8, width: 18, height: 18, borderRadius: '50%', background: 'var(--low)', border: '2px solid var(--panel)', display: 'grid', placeItems: 'center', fontSize: 9, fontWeight: 700, color: '#fff', fontFamily: 'var(--mono)' }}>!</span>
      )}
      <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', fontWeight: 700, marginBottom: 4, fontFamily: 'var(--mono)' }}>Tool</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{MCP_LABELS[data.mcp]}</div>
      <Handle type="source" position={Position.Bottom} style={handleStyle} />
    </div>
  )
}

function BranchNodeComponent(_props: { data: BranchNodeData }) {
  return (
    <div style={{ background: 'var(--panel)', border: '2px solid var(--med)', borderRadius: 10, padding: '10px 14px', minWidth: 120, boxShadow: 'var(--shadow)' }}>
      <Handle type="target" position={Position.Top} style={handleStyle} />
      <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', fontWeight: 700, marginBottom: 4, fontFamily: 'var(--mono)' }}>Router</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--med)' }}>Branch</div>
      <Handle type="source" position={Position.Bottom} style={handleStyle} />
    </div>
  )
}

function ConcludeNodeComponent(_props: { data: ConcludeNodeData }) {
  return (
    <div style={{ background: 'var(--panel)', border: '3px double var(--accent)', borderRadius: 10, padding: '10px 14px', minWidth: 120, boxShadow: 'var(--shadow)' }}>
      <Handle type="target" position={Position.Top} style={handleStyle} />
      <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', fontWeight: 700, marginBottom: 4, fontFamily: 'var(--mono)' }}>Terminal</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--accent)' }}>Conclude</div>
    </div>
  )
}

const nodeTypes: NodeTypes = {
  ToolNode: ToolNodeComponent as NodeTypes[string],
  BranchNode: BranchNodeComponent as NodeTypes[string],
  ConcludeNode: ConcludeNodeComponent as NodeTypes[string],
}

interface DragItem { kind: NodeKind; mcp?: McpType; label: string }

const SIDEBAR_ITEMS: DragItem[] = [
  { kind: 'tool', mcp: 'knowledge_graph', label: 'Knowledge Graph' },
  { kind: 'tool', mcp: 'code_graph', label: 'Code Graph' },
  { kind: 'tool', mcp: 'oracle', label: 'Oracle' },
  { kind: 'tool', mcp: 'azure_devops', label: 'Azure DevOps' },
  { kind: 'branch', label: 'Branch' },
  { kind: 'conclude', label: 'Conclude' },
]

function SidebarItem({ item, serverStatus }: { item: DragItem; serverStatus?: McpServerStatus }) {
  const onDragStart = (e: React.DragEvent) => {
    e.dataTransfer.setData('application/scout-node', JSON.stringify(item))
    e.dataTransfer.effectAllowed = 'copy'
  }
  const accent = item.kind === 'tool' && item.mcp ? MCP_ACCENT[item.mcp]
    : item.kind === 'branch' ? 'var(--med)'
    : item.kind === 'conclude' ? 'var(--accent)'
    : 'var(--border-strong)'
  const dotColor = serverStatus === undefined ? 'var(--text-faint)'
    : serverStatus.reachable ? 'var(--high)' : 'var(--low)'
  return (
    <div draggable onDragStart={onDragStart} className="flow-palette-item" style={{ borderColor: accent }}>
      <span style={{ color: 'var(--text)' }}>{item.label}</span>
      {item.kind === 'tool' && (
        <span className="flow-status-dot" style={{ background: dotColor }}
          title={serverStatus === undefined ? 'Status unknown' : serverStatus.reachable ? 'Reachable' : 'Server not running'} />
      )}
    </div>
  )
}

// ─── Unified Node Inspector ───────────────────────────────────────────────────

function InspectorRow({ label, value, mono = false, accent }: { label: string; value: React.ReactNode; mono?: boolean; accent?: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, padding: '9px 0', borderBottom: '1px solid var(--border-soft)' }}>
      <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', fontWeight: 700 }}>{label}</span>
      <span style={{ fontSize: 12, fontFamily: mono ? 'var(--mono)' : undefined, color: accent ?? 'var(--text-2)', wordBreak: 'break-all', lineHeight: 1.5 }}>{value}</span>
    </div>
  )
}

function ToolConnectionEditor({ mcp, mcpStatus, onStatusRefresh }: {
  mcp: McpType
  mcpStatus: McpStatus
  onStatusRefresh: () => void
}) {
  const srv = mcpStatus[mcp]
  const [urlInput, setUrlInput] = useState(srv?.url ?? '')
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')

  // Sync field when mcpStatus refreshes from outside
  useEffect(() => {
    if (srv?.url && saveState === 'idle') setUrlInput(srv.url)
  }, [srv?.url])

  let port = '—'
  try { port = urlInput ? new URL(urlInput).port || '80' : '—' } catch {}

  const isDirty = urlInput.trim() !== (srv?.url ?? '')

  const handleSave = async () => {
    if (!urlInput.trim()) return
    setSaveState('saving')
    try {
      const res = await fetch('http://localhost:8000/mcp/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [mcp]: urlInput.trim() }),
      })
      if (!res.ok) throw new Error()
      setSaveState('saved')
      onStatusRefresh()
      setTimeout(() => setSaveState('idle'), 2000)
    } catch {
      setSaveState('error')
      setTimeout(() => setSaveState('idle'), 3000)
    }
  }

  return (
    <>
      <InspectorRow label="MCP service" value={MCP_LABELS[mcp]} accent={MCP_ACCENT[mcp]} />
      <InspectorRow label="Description" value={MCP_DESC[mcp]} />
      <InspectorRow label="Protocol" value="SSE (Server-Sent Events)" />

      {/* Editable URL */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5, padding: '9px 0', borderBottom: '1px solid var(--border-soft)' }}>
        <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', fontWeight: 700 }}>Connection URL</span>
        <input
          className="flow-edge-select"
          style={{ fontFamily: 'var(--mono)', fontSize: 11.5, width: '100%' }}
          value={urlInput}
          onChange={(e) => { setUrlInput(e.target.value); setSaveState('idle') }}
          onKeyDown={(e) => { if (e.key === 'Enter') handleSave() }}
          placeholder="http://127.0.0.1:8100/sse"
          spellCheck={false}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 11, color: 'var(--text-faint)', fontFamily: 'var(--mono)' }}>
            port: <span style={{ color: 'var(--text-2)' }}>{port}</span>
          </span>
          <button
            className={`btn sm${isDirty || saveState !== 'idle' ? ' accent' : ''}`}
            style={{ marginLeft: 'auto', minWidth: 90 }}
            onClick={handleSave}
            disabled={saveState === 'saving' || !urlInput.trim()}
          >
            {saveState === 'saving' ? 'Testing…'
              : saveState === 'saved' ? '✓ Saved'
              : saveState === 'error' ? 'Error'
              : 'Save & test'}
          </button>
        </div>
        {saveState === 'error' && (
          <span style={{ fontSize: 11, color: 'var(--low)' }}>Could not reach the backend. Is the Scout API running?</span>
        )}
      </div>

      {/* Live status */}
      <InspectorRow
        label="Server status"
        value={
          srv === undefined ? 'Unknown — API not reachable' :
          srv.reachable
            ? <span style={{ color: 'var(--high)', fontWeight: 600 }}>● Online</span>
            : <span style={{ color: 'var(--low)', fontWeight: 600 }}>● Offline — server not running</span>
        }
      />
      {srv && !srv.reachable && (
        <div style={{ marginTop: 6, marginBottom: 4, padding: '10px 12px', background: 'var(--low-soft)', border: '1px solid color-mix(in oklch, var(--low) 28%, transparent)', borderRadius: 8, fontSize: 11.5, color: 'var(--text-2)', lineHeight: 1.6 }}>
          Start the MCP server at the URL above, then click <strong>Save &amp; test</strong> to verify the connection.
        </div>
      )}
    </>
  )
}

function NodeInspector({ selectedNode, edges, nodes, mcpStatus, onConditionChange, onDeleteEdge, onStatusRefresh, onClose }: {
  selectedNode: Node
  edges: Edge[]
  nodes: Node[]
  mcpStatus: McpStatus
  onConditionChange: (edgeId: string, c: Condition) => void
  onDeleteEdge: (edgeId: string) => void
  onStatusRefresh: () => void
  onClose: () => void
}) {
  const nodeType = selectedNode.type

  const getNodeLabel = (id: string) => {
    const n = nodes.find((x) => x.id === id)
    if (!n) return id
    if (n.type === 'ToolNode') return MCP_LABELS[(n.data as ToolNodeData).mcp] ?? id
    if (n.type === 'BranchNode') return 'Branch'
    if (n.type === 'ConcludeNode') return 'Conclude'
    return id
  }

  const outgoing = edges.filter((e) => e.source === selectedNode.id)
  const incoming = edges.filter((e) => e.target === selectedNode.id)

  return (
    <div className="flow-inspector">
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <span className="flow-inspector-title" style={{ margin: 0 }}>
          {nodeType === 'ToolNode' ? 'Tool node'
            : nodeType === 'BranchNode' ? 'Branch node'
            : 'Conclude node'}
        </span>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-faint)', cursor: 'pointer', padding: 4, lineHeight: 1 }} title="Close inspector">✕</button>
      </div>

      {/* Node ID */}
      <InspectorRow label="Node ID" value={selectedNode.id} mono />

      {/* Tool node details */}
      {nodeType === 'ToolNode' && (() => {
        const data = selectedNode.data as ToolNodeData
        return (
          <ToolConnectionEditor
            mcp={data.mcp}
            mcpStatus={mcpStatus}
            onStatusRefresh={onStatusRefresh}
          />
        )
      })()}

      {/* Branch node details */}
      {nodeType === 'BranchNode' && (
        <>
          <InspectorRow label="Purpose" value="Routes the investigation to different paths based on the triage confidence level of the result so far." />
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', fontWeight: 700, marginBottom: 10 }}>Outgoing edges</div>
            {outgoing.length === 0
              ? <p style={{ fontSize: 12, color: 'var(--text-3)', margin: 0 }}>No edges yet. Drag from the bottom dot to another node to add one.</p>
              : outgoing.map((edge) => {
                const condition = (edge.data?.condition as Condition | undefined) ?? 'always'
                return (
                  <div key={edge.id} className="flow-edge-card">
                    <div className="flow-edge-target">→ {getNodeLabel(edge.target)}</div>
                    <select className="flow-edge-select" value={condition}
                      onChange={(e) => onConditionChange(edge.id, e.target.value as Condition)}>
                      {CONDITIONS.map((c) => <option key={c} value={c}>{CONDITION_LABELS[c]}</option>)}
                    </select>
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 8, lineHeight: 1.4 }}>{CONDITION_DESC[condition]}</div>
                    <button onClick={() => onDeleteEdge(edge.id)}
                      style={{ fontSize: 11, color: 'var(--low)', background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}>
                      Delete edge
                    </button>
                  </div>
                )
              })
            }
          </div>
        </>
      )}

      {/* Conclude node details */}
      {nodeType === 'ConcludeNode' && (
        <InspectorRow label="Purpose" value="Ends the investigation flow. Every valid flow must have exactly one Conclude node. All paths must eventually reach it." />
      )}

      {/* Connections summary (all node types) */}
      <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
        <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', fontWeight: 700, marginBottom: 8 }}>Connections</div>
        <div style={{ fontSize: 12, color: 'var(--text-3)', display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span>↑ {incoming.length} incoming edge{incoming.length !== 1 ? 's' : ''}</span>
          {nodeType !== 'ConcludeNode' && <span>↓ {outgoing.length} outgoing edge{outgoing.length !== 1 ? 's' : ''}</span>}
        </div>
      </div>

      {/* Delete button */}
      <div style={{ marginTop: 16 }}>
        <button
          className="btn"
          style={{ width: '100%', justifyContent: 'center', color: 'var(--low)', borderColor: 'color-mix(in oklch, var(--low) 28%, transparent)' }}
          onClick={onClose}
          title="Select the node on the canvas then press Delete or Backspace"
        >
          Click node → press <span className="kbd" style={{ margin: '0 4px' }}>Del</span> to remove
        </button>
      </div>
    </div>
  )
}

// ─── Flow serialisation helpers ───────────────────────────────────────────────

function rfToFlow(nodes: Node[], edges: Edge[]): InvestigationFlow {
  const targetIds = new Set(edges.map((e) => e.target))
  const entryNode = nodes.find((n) => !targetIds.has(n.id)) ?? nodes[0]
  const flowNodes: FlowNode[] = nodes.map((n) => {
    const outgoing = edges.filter((e) => e.source === n.id)
    const branchEdges: BranchEdge[] = outgoing.map((e) => ({
      target_node_id: e.target,
      condition: (e.data?.condition as Condition | undefined) ?? 'always',
    }))
    if (n.type === 'ToolNode') {
      const d = n.data as ToolNodeData
      return { id: n.id, type: 'tool', config: { mcp: d.mcp, label: d.label }, edges: branchEdges }
    }
    if (n.type === 'BranchNode') return { id: n.id, type: 'branch', config: null, edges: branchEdges }
    return { id: n.id, type: 'conclude', config: null, edges: [] }
  })
  return { nodes: flowNodes, entry_node_id: entryNode?.id ?? '' }
}

function flowToRf(flow: InvestigationFlow): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = flow.nodes.map((fn, i) => {
    const base = { id: fn.id, position: { x: 100 + (i % 4) * 220, y: 80 + Math.floor(i / 4) * 160 } }
    if (fn.type === 'tool') return { ...base, type: 'ToolNode', data: { mcp: fn.config?.mcp ?? 'oracle', label: fn.config?.label ?? '' } satisfies ToolNodeData }
    if (fn.type === 'branch') return { ...base, type: 'BranchNode', data: {} satisfies BranchNodeData }
    return { ...base, type: 'ConcludeNode', data: {} satisfies ConcludeNodeData }
  })
  const edges: Edge[] = flow.nodes.flatMap((fn) =>
    fn.edges.map((be) => ({
      id: `${fn.id}->${be.target_node_id}-${be.condition}`,
      source: fn.id, target: be.target_node_id,
      data: { condition: be.condition }, label: CONDITION_LABELS[be.condition],
    }))
  )
  return { nodes, edges }
}

function validateFlow(nodes: Node[], edges: Edge[]): string | null {
  const concludes = nodes.filter((n) => n.type === 'ConcludeNode')
  if (concludes.length === 0) return 'Must have exactly one Conclude node.'
  if (concludes.length > 1) return 'Must have exactly one Conclude node (found multiple).'
  for (const n of nodes.filter((n) => n.type !== 'ConcludeNode')) {
    if (!edges.some((e) => e.source === n.id)) return `Node "${n.id}" has no outgoing edges.`
  }
  return null
}

let nodeCounter = 1

// ─── Canvas ───────────────────────────────────────────────────────────────────

function FlowCanvas() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [selectedNode, setSelectedNode] = useState<Node | null>(null)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [mcpStatus, setMcpStatus] = useState<McpStatus>({})
  const reactFlowWrapper = useRef<HTMLDivElement>(null)
  const { screenToFlowPosition } = useReactFlow()

  useEffect(() => {
    const fetch_ = () =>
      fetch('http://localhost:8000/flow/status').then((r) => r.json()).then(setMcpStatus).catch(() => {})
    fetch_()
    const id = setInterval(fetch_, 30_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    fetch('http://localhost:8000/flow').then((r) => r.json())
      .then((data: InvestigationFlow) => { const rf = flowToRf(data); setNodes(rf.nodes); setEdges(rf.edges) })
      .catch(() => {})
  }, [setNodes, setEdges])

  const onConnect: OnConnect = useCallback(
    (c: Connection) => setEdges((eds) => addEdge({ ...c, data: { condition: 'always' }, label: CONDITION_LABELS['always'] }, eds)),
    [setEdges]
  )

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode((prev) => prev?.id === node.id ? null : node)
  }, [])

  const onPaneClick = useCallback(() => setSelectedNode(null), [])

  const onDragOver = useCallback((e: React.DragEvent) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy' }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const raw = e.dataTransfer.getData('application/scout-node')
    if (!raw) return
    const item: DragItem = JSON.parse(raw)
    const position = screenToFlowPosition({ x: e.clientX, y: e.clientY })
    const id = `node-${nodeCounter++}`
    let newNode: Node
    if (item.kind === 'tool' && item.mcp)
      newNode = { id, type: 'ToolNode', position, data: { mcp: item.mcp, label: MCP_LABELS[item.mcp] } satisfies ToolNodeData }
    else if (item.kind === 'branch')
      newNode = { id, type: 'BranchNode', position, data: {} satisfies BranchNodeData }
    else
      newNode = { id, type: 'ConcludeNode', position, data: {} satisfies ConcludeNodeData }
    setNodes((nds) => [...nds, newNode])
  }, [screenToFlowPosition, setNodes])

  // Keep inspector in sync when nodes change (e.g. after delete)
  useEffect(() => {
    if (selectedNode) {
      const still = nodes.find((n) => n.id === selectedNode.id)
      if (!still) setSelectedNode(null)
    }
  }, [nodes, selectedNode])

  const onConditionChange = useCallback((edgeId: string, condition: Condition) =>
    setEdges((eds) => eds.map((e) => e.id === edgeId ? { ...e, data: { condition }, label: CONDITION_LABELS[condition] } : e)),
    [setEdges])

  const onDeleteEdge = useCallback((edgeId: string) =>
    setEdges((eds) => eds.filter((e) => e.id !== edgeId)), [setEdges])

  const validationError = validateFlow(nodes, edges)
  const canSave = validationError === null && nodes.length > 0

  const handleSave = async () => {
    if (!canSave) return
    setSaveStatus('saving')
    try {
      const res = await fetch('http://localhost:8000/flow', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(rfToFlow(nodes, edges)),
      })
      setSaveStatus(res.ok ? 'saved' : 'error')
      if (res.ok) setTimeout(() => setSaveStatus('idle'), 2000)
    } catch { setSaveStatus('error') }
  }

  return (
    <FlowStatusContext.Provider value={mcpStatus}>
      <div className="flow-editor-wrap">
        {/* Palette */}
        <div className="flow-palette">
          <div className="flow-palette-title">Node Palette</div>
          {SIDEBAR_ITEMS.map((item) => (
            <SidebarItem key={`${item.kind}-${item.mcp ?? ''}`} item={item}
              serverStatus={item.mcp ? mcpStatus[item.mcp] : undefined} />
          ))}
          <p style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 16, lineHeight: 1.6 }}>
            Drag a node onto the canvas. Click any node to inspect it.
          </p>
        </div>

        {/* Canvas */}
        <div className="flow-canvas-area">
          <div className="flow-toolbar">
            <button className={`btn${canSave ? ' accent' : ''}`} onClick={handleSave}
              disabled={!canSave || saveStatus === 'saving'}>
              {saveStatus === 'saving' ? 'Saving…' : 'Save Flow'}
            </button>
            {saveStatus === 'saved' && <span style={{ fontSize: 13, color: 'var(--high)', fontWeight: 600 }}>Saved!</span>}
            {saveStatus === 'error' && <span style={{ fontSize: 13, color: 'var(--low)' }}>Save failed</span>}
            {validationError
              ? <span style={{ fontSize: 12, color: 'var(--low)' }}>{validationError}</span>
              : nodes.length > 0 && <span style={{ fontSize: 12, color: 'var(--high)', fontWeight: 600 }}>✓ Flow valid</span>}
            <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-faint)', display: 'flex', gap: 10, alignItems: 'center' }}>
              <span>Connect: drag <span style={{ color: 'var(--text-3)' }}>bottom dot → top dot</span></span>
              <span>Select → <span className="kbd">Del</span> to remove</span>
            </span>
          </div>
          <div ref={reactFlowWrapper} style={{ flex: 1 }}>
            <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes}
              onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
              onConnect={onConnect} onNodeClick={onNodeClick} onPaneClick={onPaneClick}
              onDrop={onDrop} onDragOver={onDragOver}
              deleteKeyCode={['Delete', 'Backspace']}
              multiSelectionKeyCode="Shift"
              fitView>
              <Background color="var(--border)" />
              <Controls />
              <MiniMap />
            </ReactFlow>
          </div>
        </div>

        {/* Inspector panel — opens for any node type */}
        {selectedNode && (
          <NodeInspector
            selectedNode={selectedNode}
            edges={edges}
            nodes={nodes}
            mcpStatus={mcpStatus}
            onConditionChange={onConditionChange}
            onDeleteEdge={onDeleteEdge}
            onStatusRefresh={() =>
              fetch('http://localhost:8000/flow/status').then((r) => r.json()).then(setMcpStatus).catch(() => {})
            }
            onClose={() => setSelectedNode(null)}
          />
        )}
      </div>
    </FlowStatusContext.Provider>
  )
}

export default function FlowEditor() {
  return <ReactFlowProvider><FlowCanvas /></ReactFlowProvider>
}
