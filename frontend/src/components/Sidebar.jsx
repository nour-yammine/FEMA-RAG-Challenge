// src/components/Sidebar.jsx
import { useEffect, useState } from 'react'
import { getIngestionStatus, getHealth } from '../services/api'

// Map document labels to badge colors (matching CSS variables)
const BADGE_STYLES = {
  PAPPG:           { bg: '#6366f1', label: 'PAPPG' },
  CEF_SOP:         { bg: '#0891b2', label: 'CEF' },
  SFM_SOP:         { bg: '#7c3aed', label: 'SFM' },
  DamageAssessment:{ bg: '#d97706', label: 'DA' },
  ApplicantHandbook:{ bg: '#059669', label: 'HNDBK' },
  Unknown:         { bg: '#6b7280', label: '???' },
}

function DocBadge({ label }) {
  const style = BADGE_STYLES[label] || BADGE_STYLES.Unknown
  return (
    <span
      className="doc-badge"
      style={{ background: style.bg, color: '#fff' }}
    >
      {style.label}
    </span>
  )
}

export default function Sidebar({ onNewChat }) {
  const [docs, setDocs] = useState({})
  const [health, setHealth] = useState({ status: 'loading', chunks_in_db: 0 })

  useEffect(() => {
    async function load() {
      try {
        const [statusData, healthData] = await Promise.all([
          getIngestionStatus(),
          getHealth(),
        ])
        setDocs(statusData.ingested_files || {})
        setHealth(healthData)
      } catch {
        setHealth({ status: 'error', chunks_in_db: 0 })
      }
    }
    load()
  }, [])

  const docEntries = Object.entries(docs)

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">🏛</div>
          <div className="sidebar-logo-text">
            <h1>FEMA RAG</h1>
            <p>Public Assistance Assistant</p>
          </div>
        </div>
        <button className="btn-new-chat" onClick={onNewChat}>
          <span>＋</span> New Conversation
        </button>
      </div>

      <div className="sidebar-section">Source Documents</div>

      <div className="sidebar-docs">
        {docEntries.length === 0 ? (
          <div style={{ padding: '10px 8px', fontSize: 12, color: 'var(--text-muted)' }}>
            No documents ingested yet.
            <br />
            Run <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>python -m ingestion.ingest</code>
          </div>
        ) : (
          docEntries.map(([filename, info]) => (
            <div className="doc-item" key={filename}>
              <DocBadge label={info.document_label} />
              <span className="doc-name" title={filename}>
                {filename.replace(/_/g, ' ').replace('.pdf', '')}
              </span>
              <span className="doc-chunks">{info.num_chunks}c</span>
            </div>
          ))
        )}
      </div>

      <div className="sidebar-footer">
        <div className="db-status">
          <span
            className={`status-dot ${
              health.status === 'loading' ? 'loading' :
              health.status === 'error'   ? 'error' : ''
            }`}
          />
          <span>
            {health.status === 'error'
              ? 'Backend unreachable'
              : health.status === 'loading'
              ? 'Connecting...'
              : `${health.chunks_in_db.toLocaleString()} chunks in DB`}
          </span>
        </div>
      </div>
    </aside>
  )
}
