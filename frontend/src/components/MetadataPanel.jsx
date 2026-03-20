// src/components/MetadataPanel.jsx
import { useState } from 'react'

const BADGE_STYLES = {
  PAPPG:            { bg: '#6366f1', color: '#fff' },
  CEF_SOP:          { bg: '#0891b2', color: '#fff' },
  SFM_SOP:          { bg: '#7c3aed', color: '#fff' },
  DamageAssessment: { bg: '#d97706', color: '#fff' },
  ApplicantHandbook:{ bg: '#059669', color: '#fff' },
  Unknown:          { bg: '#6b7280', color: '#fff' },
}

function scoreColor(score) {
  if (score >= 0.75) return 'var(--score-high)'
  if (score >= 0.50) return 'var(--score-mid)'
  return 'var(--score-low)'
}

function ChunkCard({ chunk, index }) {
  const [expanded, setExpanded] = useState(false)
  const badge = BADGE_STYLES[chunk.document_label] || BADGE_STYLES.Unknown
  const pct = Math.round(chunk.score * 100)

  return (
    <div className="chunk-card">
      {/* Header row — always visible */}
      <div
        className="chunk-card-header"
        onClick={() => setExpanded(e => !e)}
        title="Click to expand chunk text"
      >
        {/* Rank */}
        <span style={{ fontSize: 10, color: 'var(--text-muted)', minWidth: 18 }}>
          #{index + 1}
        </span>

        {/* Score */}
        <span
          className="chunk-score"
          style={{ color: scoreColor(chunk.score) }}
        >
          {chunk.score.toFixed(3)}
        </span>

        {/* Score bar */}
        <div className="score-bar">
          <div
            className="score-fill"
            style={{ width: `${pct}%`, background: scoreColor(chunk.score) }}
          />
        </div>

        {/* Document badge */}
        <span
          className="chunk-doc-badge"
          style={{ background: badge.bg, color: badge.color }}
        >
          {chunk.document_label}
        </span>

        {/* Page */}
        <span className="chunk-page">p.{chunk.page_number}</span>

        {/* Expand icon */}
        <span className="chunk-expand-icon">
          {expanded ? '▲' : '▼'}
        </span>
      </div>

      {/* Section / hierarchy — always visible */}
      {chunk.section_path && chunk.section_path !== chunk.section && (
        <div className="chunk-section" style={{ fontSize: 11, opacity: 0.92 }} title="Hierarchy in document">
          ⛳ {chunk.section_path}
        </div>
      )}
      {chunk.section && (
        <div className="chunk-section" title="Document section">
          § {chunk.section}
        </div>
      )}

      {/* Full chunk text — collapsed by default */}
      {expanded && (
        <>
          <div className="chunk-text-body">
            {chunk.text}
          </div>
          <div className="chunk-strategy-tag">
            <span>Strategy: <strong>{chunk.chunk_strategy}</strong></span>
            <span>·</span>
            <span>Chunk #{chunk.chunk_index}</span>
            <span>·</span>
            <span style={{ wordBreak: 'break-all' }}>{chunk.source_document}</span>
          </div>
        </>
      )}
    </div>
  )
}

export default function MetadataPanel({ sources, numChunksRetrieved, model }) {
  if (!sources || sources.length === 0) return null

  // Unique documents referenced
  const uniqueDocs = [...new Set(sources.map(s => s.source_document))]
  const avgScore = (
    sources.reduce((acc, s) => acc + s.score, 0) / sources.length
  ).toFixed(3)

  return (
    <div className="metadata-panel">
      <div className="meta-header">
        <div className="meta-header-left">
          <span>🔍</span>
          <span>Retrieval Details</span>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <span className="meta-stat">{numChunksRetrieved} chunks</span>
          <span className="meta-stat">avg score {avgScore}</span>
          <span className="meta-stat">{uniqueDocs.length} doc{uniqueDocs.length !== 1 ? 's' : ''}</span>
          <span className="meta-stat" style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
            {model}
          </span>
        </div>
      </div>

      <div className="chunks-list">
        {sources.map((chunk, i) => (
          <ChunkCard key={chunk.chunk_id} chunk={chunk} index={i} />
        ))}
      </div>
    </div>
  )
}
