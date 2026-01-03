import React from 'react'
import type { SignalsState } from '../lib/types'

type Props = {
  signals: SignalsState | null
}

export default function SignalsPanel({ signals }: Props) {
  if (!signals) {
    return (
      <div className="p-4 bg-slate-100 rounded-lg">
        <h3 className="font-medium text-slate-500">Signals: 未接続</h3>
      </div>
    )
  }

  const speedColor = signals.current_speed > 2.5 ? 'text-red-600' : 'text-slate-900'
  const staleColor = signals.is_stale ? 'bg-yellow-100' : 'bg-white'

  return (
    <div className={`p-4 rounded-lg shadow ${staleColor}`}>
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-medium">DuoSignals</h3>
        {signals.is_stale && (
          <span className="px-2 py-0.5 text-xs bg-yellow-200 text-yellow-800 rounded">
            STALE
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <span className="text-slate-500">Mode:</span>
          <span className="ml-1 font-mono">{signals.jetracer_mode}</span>
        </div>
        <div>
          <span className="text-slate-500">Speed:</span>
          <span className={`ml-1 font-mono ${speedColor}`}>
            {signals.current_speed.toFixed(2)} m/s
          </span>
        </div>
        <div>
          <span className="text-slate-500">Steering:</span>
          <span className="ml-1 font-mono">{signals.steering_angle.toFixed(1)}°</span>
        </div>
        <div>
          <span className="text-slate-500">Turn:</span>
          <span className="ml-1 font-mono">#{signals.turn_count}</span>
        </div>
      </div>

      {/* Scene Facts */}
      {Object.keys(signals.scene_facts).length > 0 && (
        <div className="mt-3 pt-2 border-t">
          <h4 className="text-xs text-slate-500 mb-1">Scene Facts</h4>
          <div className="flex flex-wrap gap-1">
            {Object.entries(signals.scene_facts).map(([key, value]) => (
              <span key={key} className="px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded">
                {key}: {value}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Topic Depth */}
      {signals.topic_depth > 0 && (
        <div className="mt-2">
          <span className="text-xs text-slate-500">Topic Depth: </span>
          <span className={`text-xs font-mono ${signals.topic_depth >= 3 ? 'text-orange-600' : ''}`}>
            {signals.topic_depth}
          </span>
          {signals.topic_depth >= 3 && (
            <span className="ml-1 text-xs text-orange-600">Loop risk</span>
          )}
        </div>
      )}

      {/* Distance Sensors */}
      {Object.keys(signals.distance_sensors).length > 0 && (
        <div className="mt-2">
          <h4 className="text-xs text-slate-500 mb-1">Sensors</h4>
          <div className="flex gap-2 text-xs font-mono">
            {Object.entries(signals.distance_sensors).map(([key, value]) => (
              <span key={key} className="px-1 bg-slate-100 rounded">
                {key}: {typeof value === 'number' ? value.toFixed(0) : value}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
