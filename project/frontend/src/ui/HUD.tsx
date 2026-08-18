import type { PayloadItem } from '../types'
import { COLOR_MAP } from '../types'
import { useSimStore } from '../store/simStore'

function PanelShell({
  title,
  children,
  className = '',
}: {
  title: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={`hud-panel ${className}`}>
      <div className="hud-panel-title">{title}</div>
      {children}
    </div>
  )
}

export function LeftPanel() {
  const battery = useSimStore((s) => s.runtime?.battery ?? 0)
  const batteryMax = useSimStore((s) => s.scenario?.robot.battery_max ?? 100)
  const payload = useSimStore((s) => s.runtime?.payload ?? [])
  const capacity = useSimStore((s) => s.scenario?.robot.cargo_capacity ?? 3)
  const pct = Math.round((battery / batteryMax) * 100)

  return (
    <aside className="hud-left">
      <div className="brand">
        <div className="brand-kicker">EMERGENCY CONTROL</div>
        <div className="brand-title">AI OPERATIONS UNIT</div>
      </div>

      <PanelShell title="POWER CORE">
        <div className="battery-row">
          <div className="battery-track">
            <div
              className="battery-fill"
              style={{
                width: `${pct}%`,
                background:
                  pct > 40 ? 'linear-gradient(90deg,#22d3ee,#06b6d4)' : 'linear-gradient(90deg,#f87171,#ef4444)',
              }}
            />
          </div>
          <span className="battery-pct">{pct}%</span>
        </div>
        <div className="muted">Battery {battery}/{batteryMax}</div>
      </PanelShell>

      <PanelShell title="PAYLOAD">
        <div className="payload-slots">
          {Array.from({ length: capacity }).map((_, i) => {
            const item = payload[i]
            return (
              <div key={i} className={`payload-slot ${item ? 'filled' : ''}`}>
                {item ? <PayloadLabel item={item} /> : <span className="muted">empty</span>}
              </div>
            )
          })}
        </div>
        {payload.length === 0 && <div className="muted">No items equipped.</div>}
      </PanelShell>

      <MissionProgress />

      <PanelShell title="MAP LEGEND">
        <ul className="legend">
          <li><span className="dot" style={{ background: COLOR_MAP.yellow }} /> Keys</li>
          <li><span className="dot" style={{ background: COLOR_MAP.cyan }} /> Doors (translucent)</li>
          <li><span className="dot" style={{ background: COLOR_MAP.blue }} /> Panel OK</li>
          <li><span className="dot" style={{ background: COLOR_MAP.red }} /> Panel DAMAGED / Station OFFLINE</li>
          <li><span className="dot" style={{ background: COLOR_MAP.green }} /> Station ONLINE</li>
          <li><span className="dot" style={{ background: '#fbbf24' }} /> Charger</li>
          <li><span className="dot" style={{ background: '#fb923c' }} /> Tools</li>
          <li className="legend-cost">
            <span className="cost-bar" /> Floor tint = corridor MOVE cost (each cost = distinct color)
          </li>
        </ul>
      </PanelShell>
    </aside>
  )
}

/** Progreso de la misión: estado en vivo de paneles y estaciones. */
function MissionProgress() {
  const scenario = useSimStore((s) => s.scenario)
  const panels = useSimStore((s) => s.runtime?.panels)
  const stations = useSimStore((s) => s.runtime?.stations)
  if (!scenario || !panels || !stations) return null

  const goal = scenario.goal.stations_online
  const done = goal.filter((id) => stations[id] === 'ONLINE').length

  return (
    <PanelShell title={`MISSION PROGRESS — ${done}/${goal.length}`}>
      <div className="mission-list">
        {scenario.panels.map((p) => (
          <div key={p.id} className="mission-row">
            <span>{p.id}</span>
            <span className={panels[p.id] === 'OK' ? 'pill pill-ok' : 'pill pill-bad'}>
              {panels[p.id]}
            </span>
          </div>
        ))}
        {scenario.stations.map((s) => (
          <div key={s.id} className="mission-row">
            <span>
              {s.id}
              {goal.includes(s.id) && <em className="goal-mark"> ★</em>}
            </span>
            <span className={stations[s.id] === 'ONLINE' ? 'pill pill-ok' : 'pill pill-bad'}>
              {stations[s.id]}
            </span>
          </div>
        ))}
      </div>
    </PanelShell>
  )
}

const BANNERS = {
  success: { text: 'MISSION COMPLETE', cls: 'banner-ok' },
  failed: { text: 'FAILURE — no valid plan', cls: 'banner-bad' },
  rejected: { text: 'PLAN REJECTED BY SIMULATOR', cls: 'banner-bad' },
} as const

/** Resultado final de la ejecución, visible sin leer el log. */
export function ResultBanner() {
  const outcome = useSimStore((s) => s.outcome)
  const error = useSimStore((s) => s.error)
  if (outcome === 'idle' || outcome === 'running') return null

  const banner = BANNERS[outcome]
  return (
    <div className={`result-banner ${banner.cls}`}>
      <strong>{banner.text}</strong>
      {error && <span className="result-detail">{error}</span>}
    </div>
  )
}

function PayloadLabel({ item }: { item: PayloadItem }) {
  if (item.kind === 'key') {
    return (
      <span style={{ color: COLOR_MAP[item.color] ?? '#fff' }}>
        KEY {item.id}
      </span>
    )
  }
  if (item.kind === 'tool') {
    return <span style={{ color: '#fb923c' }}>{item.id}</span>
  }
  return <span style={{ color: '#a78bfa' }}>{item.type}</span>
}

export function RightPanel() {
  const energySpent = useSimStore((s) => s.runtime?.energySpent ?? 0)
  const totalCost = useSimStore((s) => s.totalCost)
  const log = useSimStore((s) => s.log)
  const stepIndex = useSimStore((s) => s.stepIndex)
  const planLen = useSimStore((s) => s.plan.length)
  const error = useSimStore((s) => s.error)

  return (
    <aside className="hud-right">
      <PanelShell title="ENERGY COST" className="energy-cost">
        <div className="energy-big">{energySpent}</div>
        {totalCost > 0 && (
          <div className="muted">
            Plan total: {totalCost}
            {energySpent === totalCost && stepIndex === planLen && planLen > 0 && (
              <span className="pill pill-ok cost-match">match</span>
            )}
          </div>
        )}
      </PanelShell>

      <PanelShell title="EXECUTION LOG" className="log-panel">
        <div className="step-counter">
          STEP {stepIndex}/{planLen || 0}
        </div>
        {error && <div className="log-error-banner">{error}</div>}
        <div className="log-scroll">
          {log.map((e) => (
            <div key={e.index} className={`log-line log-${e.level}`}>
              {e.text}
            </div>
          ))}
        </div>
      </PanelShell>
    </aside>
  )
}

export function BottomControls({
  onExecute,
  onReset,
}: {
  onExecute: () => void
  onReset: () => void
}) {
  const running = useSimStore((s) => s.running)
  const outcome = useSimStore((s) => s.outcome)
  const planLen = useSimStore((s) => s.plan.length)
  const speed = useSimStore((s) => s.speed)
  const setSpeed = useSimStore((s) => s.setSpeed)
  const setRunning = useSimStore((s) => s.setRunning)
  const zone = useSimStore((s) => s.runtime?.robotZone)
  // Mientras el backend busca aún no hay plan: se avisa para que no parezca
  // que la interfaz se colgó.
  const searching = outcome === 'running' && planLen === 0
  const zoneName = useSimStore(
    (s) => s.scenario?.zones.find((z) => z.id === s.runtime?.robotZone)?.name,
  )

  return (
    <footer className="hud-bottom">
      <button className="btn btn-primary" onClick={onExecute} disabled={running || searching}>
        {searching ? '⏳ SEARCHING...' : '▶ EXECUTE PLAN'}
      </button>
      <button
        className="btn btn-secondary"
        onClick={() => {
          setRunning(false)
          onReset()
        }}
      >
        ↺ RESET
      </button>
      <label className="speed-control">
        SPEED
        <input
          type="range"
          min={0.5}
          max={3}
          step={0.25}
          value={speed}
          onChange={(e) => setSpeed(Number(e.target.value))}
        />
        <span>{speed.toFixed(2)}x</span>
      </label>
      <div className="zone-badge">
        ZONE <strong>{zone}</strong> · {zoneName}
      </div>
    </footer>
  )
}
