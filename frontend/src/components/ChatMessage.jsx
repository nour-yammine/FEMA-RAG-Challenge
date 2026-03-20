// src/components/ChatMessage.jsx
import { useMemo, useState } from 'react'
import MetadataPanel from './MetadataPanel'
import DocumentPreviewModal from './DocumentPreviewModal'

const DOC_NUMBERS_BY_LABEL = {
  CEF_SOP: 1,
  ApplicantHandbook: 2,
  SFM_SOP: 3,
  PAPPG: 4,
  DamageAssessment: 5,
}

/** Stable [n] map: actual PDF filename → display number for this answer. */
function buildDocNumberMap(sources) {
  const byFilename = new Map()
  if (!sources?.length) return byFilename

  const uniqueFiles = [...new Set(sources.map(s => s.source_document).filter(Boolean))]
  const usedNums = new Set()

  for (const fn of uniqueFiles) {
    const row = sources.find(s => s.source_document === fn)
    const pref = DOC_NUMBERS_BY_LABEL[row?.document_label]
    if (pref != null && !usedNums.has(pref)) {
      byFilename.set(fn.toLowerCase(), pref)
      usedNums.add(pref)
    }
  }

  let seq = 1
  for (const fn of uniqueFiles) {
    const k = fn.toLowerCase()
    if (byFilename.has(k)) continue
    while (usedNums.has(seq)) seq += 1
    byFilename.set(k, seq)
    usedNums.add(seq)
    seq += 1
  }

  return byFilename
}

function normalizeCitationFilename(raw) {
  return String(raw ?? '')
    .trim()
    .replace(/^[\s"'“”‘’]+|[\s"'“”‘’]+$/g, '')
}

function getDocNumberForFilename(filename, sources, docNumberByFilename) {
  const fn = normalizeCitationFilename(filename)
  if (!fn) return null

  const key = fn.toLowerCase()
  if (docNumberByFilename?.has(key)) return docNumberByFilename.get(key)

  const base = key.replace(/\.pdf$/i, '')
  for (const [k, v] of docNumberByFilename?.entries() ?? []) {
    const kb = k.replace(/\.pdf$/i, '')
    if (key === k || key.includes(k) || k.includes(key) || base === kb || key.includes(kb) || k.includes(base)) {
      return v
    }
  }

  const name = key
  const exact = sources?.find(s => (s.source_document ?? '').toLowerCase() === key)
  if (exact) return DOC_NUMBERS_BY_LABEL[exact.document_label] ?? docNumberByFilename?.get(key) ?? null

  const fuzzy = sources?.find(s => {
    const sd = (s.source_document ?? '').toLowerCase()
    if (!sd) return false
    return name === sd || name.includes(sd) || sd.includes(name.replace(/\.pdf$/i, ''))
      || sd.replace(/\.pdf$/i, '').includes(base)
  })
  if (fuzzy) return DOC_NUMBERS_BY_LABEL[fuzzy.document_label] ?? null

  if (name.includes('cef')) return 1
  if (name.includes('app_handbk') || name.includes('fema323') || name.includes('handbk')) return 2
  if (name.includes('sfm') || name.includes('9570') || name.includes('strategic')) return 3
  if (name.includes('pappg') || name.includes('policy-guide')) return 4
  if (name.includes('daom') || name.includes('femadaom') || name.includes('damage')) return 5
  return null
}

/**
 * Matches (Source: file.pdf, Section: …, Page: 1) or Pages: 1, 2
 * Section may span newlines. Runs on full message so "Sources (retrieved):" bullets are included.
 * Must be constructed per render — /g regexes keep mutable lastIndex.
 */
function matchAllCitations(text) {
  const re = /\(\s*Source:\s*([^,]+)\s*,\s*Sections?:\s*([\s\S]*?)\s*,\s*Pages?:\s*([\d\s,]+)\s*\)/gi
  const out = []
  let m
  while ((m = re.exec(text)) !== null) {
    out.push({ match: m, start: m.index, end: re.lastIndex })
  }
  return out
}

export default function ChatMessage({ message, showMetaByDefault = false }) {
  const [metaOpen, setMetaOpen] = useState(showMetaByDefault)
  const [pdfModal, setPdfModal] = useState({ isOpen: false, pdfUrl: '', page: 1, title: '' })
  const isUser = message.role === 'user'

  const docNumberByFilename = useMemo(
    () => buildDocNumberMap(message?.sources),
    [message?.sources],
  )

  function resolveCitationToDocument(filename, pageCandidate) {
    const safeFilename = normalizeCitationFilename(filename)
    const normalizedPage = Number.isFinite(Number(pageCandidate)) && Number(pageCandidate) > 0
      ? Number(pageCandidate)
      : 1

    const sources = message?.sources ?? []
    const key = safeFilename.toLowerCase()
    const matchSource = sources.find(s => (s.source_document ?? '').toLowerCase() === key)
      ?? sources.find(s => {
        const sd = (s.source_document ?? '').toLowerCase()
        return sd && (key.includes(sd) || sd.includes(key.replace(/\.pdf$/i, '')))
      })

    const resolvedName = matchSource?.source_document || safeFilename
    const title = resolvedName || 'Cited document'
    const pdfUrl = `/api/pdf/${encodeURIComponent(resolvedName)}`
    const page = normalizedPage

    return {
      fileUrl: pdfUrl,
      page,
      title,
    }
  }

  function openDocumentPreview({ pdfUrl, page, title }) {
    setPdfModal({
      isOpen: true,
      pdfUrl,
      page,
      title,
    })
  }

  const citationsLegend = useMemo(() => {
    if (isUser || !message?.sources?.length) return null
    const seen = new Map()
    for (const s of message.sources) {
      const fn = s.source_document
      if (!fn) continue
      const idx = docNumberByFilename.get(fn.toLowerCase())
      if (idx == null || seen.has(idx)) continue
      seen.set(idx, fn)
    }
    if (seen.size === 0) return null

    return (
      <div style={{ marginTop: 8, marginLeft: 6, display: 'flex', gap: 10, flexWrap: 'wrap', color: 'var(--text-muted)' }}>
        {[...seen.entries()].sort((a, b) => a[0] - b[0]).map(([idx, doc]) => (
          <span
            key={`${idx}-${doc}`}
            style={{ fontSize: 12, padding: '2px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-meta-card)' }}
          >
            [{idx}] {doc}
          </span>
        ))}
      </div>
    )
  }, [isUser, message?.sources, docNumberByFilename])

  function renderContentWithClickableCitations() {
    const text = message?.content ?? ''
    // Parse entire body so citations under "Sources (retrieved):" are clickable too.
    const parts = []
    let last = 0
    let citationIndex = 0

    const hits = matchAllCitations(text)
    for (const { match: m, start, end } of hits) {
      if (start > last) parts.push(text.slice(last, start))

      const filename = normalizeCitationFilename(m[1])
      const candidates = String(m[3] ?? '')
        .split(',')
        .map(s => Number(s.trim()))
        .filter(n => Number.isFinite(n) && n > 0)

      const pageNum = candidates[0] || 1
      const docNum = getDocNumberForFilename(filename, message?.sources, docNumberByFilename) ?? '?'

      const citeKey = `${start}-${end}-${encodeURIComponent(filename)}-${pageNum}-${citationIndex}`
      parts.push(
        <button
          key={citeKey}
          type="button"
          onClick={() => {
            const resolved = resolveCitationToDocument(filename, pageNum)
            openDocumentPreview({
              pdfUrl: resolved.fileUrl,
              page: resolved.page,
              title: resolved.title,
            })
          }}
          style={{
            background: 'none',
            border: 'none',
            padding: 0,
            margin: 0,
            cursor: 'pointer',
            textDecoration: 'underline',
            color: 'inherit',
            font: 'inherit',
            fontWeight: 500,
          }}
          title={`Open ${filename} page ${pageNum}`}
        >
          [{docNum}] p.{pageNum}
        </button>,
      )
      last = end
      citationIndex += 1
    }

    if (parts.length > 0) {
      if (last < text.length) parts.push(text.slice(last))
      return parts
    }

    return text
  }

  return (
    <div className={`message-row ${isUser ? 'user' : 'assistant'}`}>
      <div className={`message-bubble ${isUser ? 'user' : 'assistant'}`}>
        {renderContentWithClickableCitations()}
      </div>

      {citationsLegend}

      {/* Only assistant messages have metadata */}
      {!isUser && message.sources && (
        <>
          <div className="message-meta-bar">
            <span>{new Date(message.timestamp).toLocaleTimeString()}</span>
            <button
              className="btn-show-meta"
              onClick={() => setMetaOpen(o => !o)}
            >
              {metaOpen ? '▲ Hide' : '▼ Show'} retrieval ({message.numChunks} chunks)
            </button>
            {[...new Set(message.sources.map(s => s.document_label))].map(label => (
              <span
                key={label}
                style={{
                  fontSize: 10,
                  padding: '1px 6px',
                  borderRadius: 3,
                  background: 'var(--bg-meta-card)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-muted)',
                }}
              >
                {label}
              </span>
            ))}
          </div>

          {metaOpen && (
            <MetadataPanel
              sources={message.sources}
              numChunksRetrieved={message.numChunks}
              model={message.model}
            />
          )}
        </>
      )}

      <DocumentPreviewModal
        isOpen={!isUser && pdfModal.isOpen}
        pdfUrl={pdfModal.pdfUrl}
        page={pdfModal.page}
        title={pdfModal.title}
        onClose={() => setPdfModal({ isOpen: false, pdfUrl: '', page: 1, title: '' })}
      />
    </div>
  )
}
