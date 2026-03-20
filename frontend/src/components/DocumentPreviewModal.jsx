import { useMemo } from 'react'

function isLikelyPdfEndpoint(url) {
  if (!url) return false
  const lower = url.toLowerCase()
  return lower.endsWith('.pdf') || lower.includes('/pdf/') || lower.includes('/api/files/')
}

export default function DocumentPreviewModal({
  isOpen,
  pdfUrl,
  page = 1,
  title = 'Cited PDF',
  onClose,
}) {
  const normalizedPage = Number.isFinite(Number(page)) && Number(page) > 0 ? Number(page) : 1
  const viewerUrl = useMemo(() => {
    if (!pdfUrl) return ''
    const pageHash = `#page=${normalizedPage}`
    return pdfUrl.includes('#') ? `${pdfUrl}&page=${normalizedPage}` : `${pdfUrl}${pageHash}`
  }, [pdfUrl, normalizedPage])

  if (!isOpen) return null

  const canEmbed = isLikelyPdfEndpoint(pdfUrl)

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0,0,0,0.55)',
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: '95vw',
          height: '90vh',
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 12px',
            background: 'var(--bg-input)',
            borderBottom: '1px solid var(--border)',
            gap: 8,
          }}
        >
          <div style={{ fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {title} - page {normalizedPage}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <a
              href={viewerUrl}
              target="_blank"
              rel="noreferrer"
              style={{
                fontSize: 12,
                border: '1px solid var(--border)',
                borderRadius: 6,
                padding: '4px 10px',
                color: 'var(--text-primary)',
                textDecoration: 'none',
              }}
            >
              Open in new tab
            </a>
            <button
              type="button"
              onClick={onClose}
              style={{
                background: 'none',
                border: '1px solid var(--border)',
                borderRadius: 6,
                padding: '4px 10px',
                cursor: 'pointer',
                color: 'var(--text-primary)',
              }}
            >
              Close
            </button>
          </div>
        </div>

        {canEmbed ? (
          <object
            data={viewerUrl}
            type="application/pdf"
            width="100%"
            height="100%"
            style={{ background: '#fff' }}
          >
            <div style={{ padding: 16 }}>
              <p style={{ marginTop: 0 }}>This browser could not embed the PDF.</p>
              <a href={viewerUrl} target="_blank" rel="noreferrer">Open the PDF in a new tab</a>
            </div>
          </object>
        ) : (
          <div style={{ padding: 16 }}>
            <p style={{ marginTop: 0 }}>
              This citation did not resolve to a PDF endpoint.
            </p>
            <a href={viewerUrl} target="_blank" rel="noreferrer">Open in a new tab</a>
          </div>
        )}
      </div>
    </div>
  )
}
