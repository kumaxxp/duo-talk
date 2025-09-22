import React from 'react'

export default function CovSpark({ values, width=180, height=24 }: { values: number[], width?: number, height?: number }){
  if (!values?.length) return null
  const max = Math.max(...values, 0.001)
  const pts = values.map((v,i)=> [i*(width/((values.length-1)||1)), height - (v/max)*height])
  const d = pts.map((p,i)=> (i?'L':'M')+p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')
  return (
    <svg width={width} height={height}>
      <path d={d} fill="none" stroke="#10b981" strokeWidth="2" />
    </svg>
  )
}

