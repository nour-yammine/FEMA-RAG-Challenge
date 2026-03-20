// src/App.jsx - Root component
import { useState, useRef, useEffect, useCallback } from 'react'
import Sidebar from './components/Sidebar'
import ChatMessage from './components/ChatMessage'
import WelcomeScreen from './components/WelcomeScreen'
import { sendMessage, deleteConversation } from './services/api'
import jsPDF from 'jspdf'

const ASSESSMENT_QUESTIONS = [
  'What is the Cost Estimating Format (CEF) and what types of projects is it used for?',
  'Who determines which local factors to use when developing a CEF cost estimate, and what factors do they consider?',
  'What is Strategic Funds Management (SFM) and what is its purpose?',
  'What types of entities are eligible to apply for FEMA Public Assistance?',
  'What are the two main types of federal disaster declarations, and what assistance is available under each?',
  'In the CEF process, what is the difference between Part A and Part B of the cost estimate, and who is responsible for each?',
  'When does the SFM SOP NOT apply? What exceptions exist?',
  'Explain the process for a subgrantee to receive PA funding, from the initial Request for Public Assistance through final obligation. Reference the relevant SOPs and guides.',
  `What does the PAPPG say about the use of the words "must" and "required" versus "should" in policy guidance? Why does this distinction matter?`,
  'What is the Alternative Procedures Pilot Policy, and how does it change the standard PA process for permanent work projects?',
  'What Construction Specifications Institute (CSI) standards are referenced in the CEF process, and how should unit costs be documented? Specifically, which unit types are acceptable and which are not?',
  'If a subgrantee wants to split Project Worksheets (PWs) to create multiple obligations, under what circumstances is this allowed according to the SFM SOP?',
  'Compare and contrast how the PAPPG and the Applicant Handbook describe the roles of State governments in the PA process. Are there any differences in emphasis or detail?',
  'What is the review cycle for SOPs according to the SFM SOP? Does the SOP automatically expire?',
  'A city sustained damage to a public library and a water treatment plant in the same disaster. Walk through how FEMA would process these as separate projects under the PA program, referencing the relevant cost estimation and fund management procedures.',
]

// Auto-resize textarea to fit content
function useAutoResize(ref) {
  const resize = useCallback(() => {
    if (!ref.current) return
    ref.current.style.height = 'auto'
    ref.current.style.height = Math.min(ref.current.scrollHeight, 160) + 'px'
  }, [ref])
  return resize
}

export default function App() {
  const [messages, setMessages] = useState([])          // [{role, content, sources, numChunks, model, timestamp}]
  const [input, setInput]         = useState('')
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState(null)
  const [conversationId, setConversationId] = useState(null)
  const [topK, setTopK]           = useState(5)
  const [globalMetaOpen, setGlobalMetaOpen] = useState(true)
  const [batchRunning, setBatchRunning] = useState(false)
  const [batchProgress, setBatchProgress] = useState({ done: 0, total: ASSESSMENT_QUESTIONS.length })

  const bottomRef   = useRef(null)
  const textareaRef = useRef(null)
  const resize      = useAutoResize(textareaRef)

  // Scroll to bottom when messages update
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // Auto-resize textarea on input change
  useEffect(() => { resize() }, [input, resize])

  // ── Send a message ────────────────────────────────────────────────
  async function handleSend(text) {
    const msgText = (text ?? input).trim()
    if (!msgText || loading) return

    setInput('')
    setError(null)

    // Append user message
    const userMsg = {
      role: 'user',
      content: msgText,
      timestamp: Date.now(),
    }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      const data = await sendMessage(msgText, conversationId, topK)

      // Save conversation ID from first response
      if (!conversationId) setConversationId(data.conversation_id)

      const aiMsg = {
        role: 'assistant',
        content: data.answer,
        sources: data.sources,
        numChunks: data.num_chunks_retrieved,
        model: data.model_used,
        timestamp: Date.now(),
      }
      setMessages(prev => [...prev, aiMsg])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // ── New conversation ──────────────────────────────────────────────
  async function handleNewChat() {
    if (conversationId) {
      try { await deleteConversation(conversationId) } catch {}
    }
    setMessages([])
    setConversationId(null)
    setError(null)
    setInput('')
  }

  // ── Keyboard handling ─────────────────────────────────────────────
  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const hasMessages = messages.length > 0

  function buildAssessmentPdf(results, startedAt, endedAt) {
    const doc = new jsPDF({ unit: 'pt', format: 'a4' })
    const pageWidth = doc.internal.pageSize.getWidth()
    const pageHeight = doc.internal.pageSize.getHeight()
    const margin = 44
    const contentWidth = pageWidth - margin * 2
    let y = margin

    const PALETTE = {
      ink: [15, 23, 42],
      body: [51, 65, 85],
      muted: [85, 96, 112], // UI: --text-muted
      accent: [30, 64, 175],
      line: [226, 232, 240],
      card: [248, 250, 252],
      cover: [17, 24, 39],
      // PDF "Retrieved Details" panel colors (match UI CSS vars)
      rdBg: [17, 24, 39], // UI: --bg-chunk
      rdBorder: [42, 52, 71], // UI: --border
      rdBody: [17, 24, 39], // UI: chunk-text-body has no background
      rdText: [139, 153, 176], // UI: --text-secondary
      rdMuted: [85, 96, 112], // UI: --text-muted
      rdGreen: [34, 197, 94], // UI: --score-high
      rdTrack: [42, 52, 71], // UI: score-bar track
      rdTag: [99, 102, 241], // default badge (overridden per document)
    }

    const SCORE_RGB = (score) => {
      if (score >= 0.75) return [34, 197, 94] // --score-high
      if (score >= 0.50) return [245, 158, 11] // --score-mid
      return [239, 68, 68] // --score-low
    }

    const BADGE_STYLES_RGB = {
      PAPPG: { bg: [99, 102, 241], color: [255, 255, 255] }, // #6366f1
      CEF_SOP: { bg: [8, 145, 178], color: [255, 255, 255] }, // #0891b2
      SFM_SOP: { bg: [124, 58, 237], color: [255, 255, 255] }, // #7c3aed
      DamageAssessment: { bg: [217, 119, 6], color: [255, 255, 255] }, // #d97706
      ApplicantHandbook: { bg: [5, 150, 105], color: [255, 255, 255] }, // #059669
      Unknown: { bg: [107, 114, 128], color: [255, 255, 255] }, // #6b7280
    }

    const getBadge = (documentLabel) => BADGE_STYLES_RGB[documentLabel] || BADGE_STYLES_RGB.Unknown

    const ensureSpace = (needed = 18, continuedLabel = '') => {
      if (y + needed <= pageHeight - margin) return
      doc.addPage()
      y = margin
      if (continuedLabel) {
        doc.setFont('helvetica', 'bold')
        doc.setFontSize(9)
        doc.setTextColor(...PALETTE.muted)
        doc.text(continuedLabel, margin, y)
        y += 16
      }
    }

    const renderJustifiedLine = (line, yy, width) => {
      const words = String(line).trim().split(/\s+/).filter(Boolean)
      if (words.length < 2) {
        doc.text(line, margin, yy)
        return
      }
      const wordsWidth = words.reduce((acc, w) => acc + doc.getTextWidth(w), 0)
      const totalExtra = width - wordsWidth
      if (totalExtra <= 0) {
        doc.text(line, margin, yy)
        return
      }
      const gap = totalExtra / (words.length - 1)
      let x = margin
      words.forEach((word, idx) => {
        doc.text(word, x, yy)
        if (idx < words.length - 1) x += doc.getTextWidth(word) + gap
      })
    }

    // UI is `white-space: pre-wrap` + `word-break: break-word`.
    // jsPDF's `splitTextToSize` doesn't always break long tokens, so we do a
    // width-aware greedy wrap that can split a long "word" into smaller pieces.
    const breakTokenToWidth = (token, width) => {
      if (!token) return ['']
      if (doc.getTextWidth(token) <= width) return [token]

      const out = []
      let i = 0
      while (i < token.length) {
        // Find largest substring that still fits.
        let lo = 1
        let hi = token.length - i
        let best = 1
        while (lo <= hi) {
          const mid = Math.floor((lo + hi) / 2)
          const slice = token.slice(i, i + mid)
          if (doc.getTextWidth(slice) <= width) {
            best = mid
            lo = mid + 1
          } else {
            hi = mid - 1
          }
        }
        out.push(token.slice(i, i + best))
        i += best
      }
      return out
    }

    const wrapPreWrap = (text, width) => {
      const str = String(text ?? '').replace(/\r\n/g, '\n').replace(/\r/g, '\n')
      const paragraphs = str.split('\n')
      const allLines = []

      paragraphs.forEach((p, pIdx) => {
        const tokens = p.split(/\s+/).filter(Boolean)
        let line = ''

        tokens.forEach((tok) => {
          if (!tok) return
          const tokParts = breakTokenToWidth(tok, width)
          tokParts.forEach((part, partIdx) => {
            const candidate = line ? `${line} ${part}` : part
            if (!line) {
              line = part
              return
            }
            if (doc.getTextWidth(candidate) <= width) {
              line = candidate
              return
            }
            allLines.push(line)
            line = partIdx === 0 ? part : part
          })
        })

        if (line) allLines.push(line)
        if (pIdx < paragraphs.length - 1) allLines.push('') // preserve newline gap
      })

      // Remove trailing empty line introduced by last newline.
      if (allLines.length > 0 && allLines[allLines.length - 1] === '') allLines.pop()
      return allLines
    }

    const writeWrapped = (text, opts = {}) => {
      const {
        size = 10,
        style = 'normal',
        color = [31, 41, 55],
        lineGap = 13,
        justify = false,
        continuedLabel = '',
        width = contentWidth,
      } = opts
      doc.setFont('helvetica', style)
      doc.setFontSize(size)
      doc.setTextColor(...color)
      const lines = doc.splitTextToSize(String(text ?? ''), width)
      lines.forEach((line, index) => {
        ensureSpace(lineGap, continuedLabel)
        const shouldJustify = justify && index < lines.length - 1
        if (shouldJustify) {
          renderJustifiedLine(line, y, width)
        } else {
          doc.text(line, margin, y)
        }
        y += lineGap
      })
    }

    const drawMessageBubble = (opts) => {
      const {
        role, // 'user' | 'assistant'
        text,
        paddingX = 16,
        paddingY = 12,
        fontSize = 11,
        lineHeight = 1.65,
        radius = 14,
        continuedLabel = '',
      } = opts

      const bubbleWidth = contentWidth
      const bubbleTextWidth = bubbleWidth - paddingX * 2

      const bgUser = [30, 58, 95] // --bg-user-msg
      const bgAi = [22, 27, 39] // --bg-ai-msg
      const borderUser = [30, 74, 122] // explicit in css
      const borderAi = PALETTE.rdBorder // --border
      const textColor = [232, 237, 245] // --text-primary

      doc.setFont('helvetica', 'normal')
      doc.setFontSize(fontSize)
      doc.setTextColor(...textColor)

      const lines = wrapPreWrap(text, bubbleTextWidth)
      const lh = fontSize * lineHeight
      const bubbleHeight = paddingY + fontSize + lines.length * lh + paddingY

      ensureSpace(bubbleHeight + 10, continuedLabel)

      const fill = role === 'user' ? bgUser : bgAi
      const border = role === 'user' ? borderUser : borderAi

      doc.setFillColor(...fill)
      doc.setDrawColor(...border)
      doc.roundedRect(margin, y, bubbleWidth, bubbleHeight, radius, radius, 'FD')

      let yy = y + paddingY + fontSize
      lines.forEach((line) => {
        doc.setTextColor(...textColor)
        doc.text(line, margin + paddingX, yy)
        yy += lh
      })

      y = y + bubbleHeight + 10
    }

    const sectionRule = (gap = 16) => {
      ensureSpace(16)
      doc.setDrawColor(...PALETTE.line)
      doc.line(margin, y, pageWidth - margin, y)
      y += gap
    }

    doc.setFillColor(...PALETTE.cover)
    doc.rect(0, 0, pageWidth, 104, 'F')
    doc.setTextColor(248, 250, 252)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(20)
    doc.text('FEMA RAG Assessment Outputs', margin, 42)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(11)
    doc.text('Run all 15 required questions with retrieval metadata', margin, 64)
    doc.text(`Generated: ${endedAt.toLocaleString()}`, margin, 82)
    y = 128

    writeWrapped('Submission Summary', { size: 12, style: 'bold', color: PALETTE.ink, lineGap: 16 })
    writeWrapped(`Top-k retrieval: ${topK}`, { size: 10, color: PALETTE.muted })
    writeWrapped('Conversation mode: single-conversation', { size: 10, color: PALETTE.muted })
    writeWrapped(`Started: ${startedAt.toLocaleString()}`, { size: 10, color: PALETTE.muted })
    writeWrapped(`Completed: ${endedAt.toLocaleString()}`, { size: 10, color: PALETTE.muted })
    writeWrapped('Each question begins on a new page.', { size: 10, color: PALETTE.muted })
    sectionRule(18)

    results.forEach((r, index) => {
      doc.addPage()
      y = margin

      doc.setFillColor(...PALETTE.card)
      doc.roundedRect(margin, y - 8, contentWidth, 24, 4, 4, 'F')
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(12)
      doc.setTextColor(...PALETTE.ink)
      doc.text(`Question ${r.question_index}`, margin + 10, y + 6)
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(9)
      doc.setTextColor(...PALETTE.muted)
      doc.text(`Page ${index + 2}`, pageWidth - margin - 8, y + 6, { align: 'right' })
      y += 28

      // Match the UI's message bubble layout and wrapping.
      drawMessageBubble({ role: 'user', text: r.question, fontSize: 11, continuedLabel: `Question ${r.question_index} (continued)` })
      drawMessageBubble({ role: 'assistant', text: r.answer || '', fontSize: 11, continuedLabel: `Question ${r.question_index} (continued)` })

      const sourceCount = Array.isArray(r.sources) ? r.sources.length : 0
      if (!r.sources?.length) {
        writeWrapped('No sources returned for this question.', { size: 9.5, color: PALETTE.muted })
      } else {
        // "MetadataPanel" style header + stats row (Retrieval Details)
        const avgScore = r.sources.reduce((acc, s) => acc + (Number.isFinite(s.score) ? Number(s.score) : 0), 0) / Math.max(1, r.sources.length)
        const uniqueDocs = new Set((r.sources ?? []).map(s => s.source_document).filter(Boolean)).size

        const metaHeaderH = 42
        ensureSpace(metaHeaderH + 10, `Question ${r.question_index} (continued)`)

        // Header background + bottom divider.
        doc.setFillColor(13, 20, 32) // UI: --bg-meta
        doc.setDrawColor(...PALETTE.rdBorder)
        doc.roundedRect(margin, y, contentWidth, metaHeaderH, 10, 10, 'F')
        doc.line(margin, y + metaHeaderH, margin + contentWidth, y + metaHeaderH)

        // Left title.
        doc.setFont('helvetica', 'bold')
        doc.setFontSize(12)
        doc.setTextColor(...PALETTE.rdText)
        doc.text('Retrieval Details', margin + 14, y + 22)

        // Right-side stat pills.
        const pillH = 16
        const pillBg = [26, 34, 54] // UI: --bg-meta-card
        const pillBorder = PALETTE.rdBorder
        const pillText = PALETTE.rdMuted

        const pills = [
          { text: `${r.num_chunks_retrieved} chunks`, font: { family: 'helvetica', style: 'bold', size: 11 } },
          { text: `avg score ${avgScore.toFixed(3)}`, font: { family: 'helvetica', style: 'normal', size: 11 } },
          { text: `${uniqueDocs} doc${uniqueDocs !== 1 ? 's' : ''}`, font: { family: 'helvetica', style: 'normal', size: 11 } },
          { text: String(r.model_used ?? ''), font: { family: 'courier', style: 'normal', size: 10, mono: true } },
        ]

        // Layout from right to left so it fits better on narrow pages.
        let cursorRight = margin + contentWidth - 10
        for (let i = pills.length - 1; i >= 0; i -= 1) {
          const { text, font } = pills[i]
          const useFont = font?.mono ? 'courier' : 'helvetica'
          doc.setFont(useFont, font?.style ?? 'normal')
          doc.setFontSize(font?.size ?? 10)
          doc.setTextColor(...pillText)

          const paddingX = 7
          const textW = doc.getTextWidth(text)
          const pillW = textW + paddingX * 2
          const pillX = Math.max(margin + 14, cursorRight - pillW)
          const pillY = y + (metaHeaderH - pillH) / 2 + 2

          doc.setFillColor(...pillBg)
          doc.setDrawColor(...pillBorder)
          doc.roundedRect(pillX, pillY, pillW, pillH, 4, 4, 'FD')
          doc.setTextColor(...pillText)
          doc.text(text, pillX + pillW / 2, pillY + 11, { align: 'center' })

          cursorRight = pillX - 6
        }

        y += metaHeaderH + 10 // UI: chunks-list padding

        r.sources.forEach((s, idx) => {
          const sourceDocument = String(s.source_document ?? s.document_label ?? 'Unknown source')
          const pageLabel = s.page_number ? `p.${s.page_number}` : 'p.?'
          const rawScore = Number.isFinite(s.score) ? Number(s.score) : 0
          const scoreClamped = Math.max(0, Math.min(1, rawScore))
          const scoreLabel = scoreClamped.toFixed(3)
          const scoreRgb = SCORE_RGB(scoreClamped)
          const badge = getBadge(s.document_label)
          const section = (s.section ?? '').toString().replace(/\s+/g, ' ').trim()
          const sectionPath = (s.section_path ?? '').toString().replace(/\s+/g, ' ').trim()
          const strategy = s.chunk_strategy ?? 'Chunker'
          const badgeLabel = String(s.document_label ?? 'Unknown')
          // Measure chunk text with the same font/size we render with later.
          doc.setFont('courier', 'normal')
          doc.setFontSize(10)
          const excerptLinesAll = wrapPreWrap(String(s.text ?? ''), contentWidth - 24)
          // UI chunk-text-body uses max-height: 220px; mimic visible portion in PDF.
          const maxTextLines = Math.floor((220 * 0.75) / 13) // ~12 lines
          const excerptLines = excerptLinesAll.length > maxTextLines
            ? [...excerptLinesAll.slice(0, maxTextLines - 1), '…']
            : excerptLinesAll
          const excerptHeight = excerptLines.length * 13
          const blockMinHeight = 84 + excerptHeight + 26

          // Keep each source block together when possible.
          ensureSpace(blockMinHeight, `Question ${r.question_index} (continued)`)

          const blockTop = y
          const blockHeight = blockMinHeight - 8
          const blockWidth = contentWidth

          // Outer retrieval card.
          doc.setFillColor(...PALETTE.rdBg)
          doc.setDrawColor(...PALETTE.rdBorder)
          doc.roundedRect(margin, blockTop, blockWidth, blockHeight, 6, 6, 'FD')

          // Top row: # / score + progress.
          const rowY = blockTop + 16
          doc.setFont('helvetica', 'bold')
          doc.setFontSize(9)
          doc.setTextColor(...PALETTE.rdMuted)
          doc.text(`#${idx + 1}`, margin + 10, rowY)
          doc.setTextColor(...scoreRgb)
          doc.text(scoreLabel, margin + 34, rowY)

          const barX = margin + 76
          const barY = rowY - 4
          const barW = blockWidth - 182
          const barH = 5
          doc.setFillColor(...PALETTE.rdTrack)
          doc.roundedRect(barX, barY, barW, barH, 2, 2, 'F')
          const pct = Math.round(scoreClamped * 100)
          const fillW = pct <= 0 ? 0 : barW * (pct / 100)
          if (fillW > 0) {
            doc.setFillColor(...scoreRgb)
            doc.roundedRect(barX, barY, fillW, barH, 2, 2, 'F')
          }

          // Right-side doc badge + page.
          const badgeW = 46
          const badgeH = 14
          const badgeX = margin + blockWidth - 92
          const badgeY = rowY - 10
          doc.setFillColor(...badge.bg)
          doc.roundedRect(badgeX, badgeY, badgeW, badgeH, 3, 3, 'F')
          doc.setFont('helvetica', 'bold')
          doc.setFontSize(7.5)
          doc.setTextColor(...badge.color)
          doc.text(badgeLabel.slice(0, 14), badgeX + badgeW / 2, badgeY + 9, { align: 'center' })
          doc.setFont('helvetica', 'normal')
          doc.setFontSize(8)
          doc.setFont('courier', 'normal')
          doc.setFontSize(10)
          doc.setTextColor(...PALETTE.rdMuted)
          doc.text(pageLabel, margin + blockWidth - 36, rowY)
          doc.setFont('helvetica', 'normal')

          // Section / hierarchy subtitle.
          let sectionY = rowY + 15
          doc.setFont('helvetica', 'italic')
          doc.setFontSize(8.5)
          doc.setTextColor(...PALETTE.rdText)
          if (sectionPath && sectionPath !== section) {
            const pathLines = doc.splitTextToSize(`⛳ ${sectionPath}`, blockWidth - 20)
            pathLines.forEach((line) => {
              doc.text(line, margin + 10, sectionY)
              sectionY += 11
            })
          }
          doc.text(section ? `§ ${section}` : `§ ${sourceDocument}`, margin + 10, sectionY)

          // Body panel with chunk text.
          const bodyTop = sectionY + 8
          const bodyHeight = blockHeight - (bodyTop - blockTop) - 18
          doc.setFillColor(...PALETTE.rdBody)
          doc.roundedRect(margin + 8, bodyTop, blockWidth - 16, bodyHeight, 4, 4, 'F')

          let textY = bodyTop + 14
          doc.setFont('courier', 'normal')
          doc.setFontSize(10)
          doc.setTextColor(...PALETTE.rdText)
          excerptLines.forEach((line) => {
            doc.text(line, margin + 14, textY)
            textY += 13
          })

          // Strategy tag (UI: chunk-strategy-tag)
          const tagText = (() => {
            const chunkIndex = Number.isFinite(Number(s.chunk_index)) ? Number(s.chunk_index) : idx
            const sourceShort = sourceDocument.length > 28 ? `${sourceDocument.slice(0, 28)}…` : sourceDocument
            return `Strategy: ${strategy} · Chunk #${chunkIndex} · ${sourceShort}`
          })()

          const tagH = 18
          const tagY = blockTop + blockHeight - tagH
          doc.setFillColor(13, 20, 32) // UI: --bg-meta
          doc.roundedRect(margin + 8, tagY, blockWidth - 16, tagH, 4, 4, 'F')

          doc.setFont('helvetica', 'bold')
          doc.setFontSize(8.2)
          doc.setTextColor(...PALETTE.rdMuted)
          doc.text(tagText, margin + 10, tagY + 12)

          y = blockTop + blockHeight + 12
        })
      }
    })

    const stamp = endedAt.toISOString().slice(0, 19).replace(/[:T]/g, '-')
    doc.save(`fema-rag-15-questions-${stamp}.pdf`)
  }

  async function runAssessmentAndExportPdf() {
    if (batchRunning || loading) return
    setBatchRunning(true)
    setBatchProgress({ done: 0, total: ASSESSMENT_QUESTIONS.length })
    setError(null)

    const startedAt = new Date()
    const results = []
    let convId = null

    try {
      for (let i = 0; i < ASSESSMENT_QUESTIONS.length; i += 1) {
        const question = ASSESSMENT_QUESTIONS[i]
        const data = await sendMessage(question, convId, topK)
        convId = data.conversation_id || convId
        results.push({
          question_index: i + 1,
          question,
          answer: data.answer,
          conversation_id: data.conversation_id,
          num_chunks_retrieved: data.num_chunks_retrieved,
          model_used: data.model_used,
          sources: data.sources || [],
        })
        setBatchProgress({ done: i + 1, total: ASSESSMENT_QUESTIONS.length })
      }

      buildAssessmentPdf(results, startedAt, new Date())
    } catch (err) {
      setError(`Assessment run failed: ${err.message}`)
    } finally {
      setBatchRunning(false)
    }
  }

  return (
    <div className="app-layout">
      {/* ── Left sidebar ── */}
      <Sidebar onNewChat={handleNewChat} />

      {/* ── Main chat column ── */}
      <div className="chat-area">

        {/* Header */}
        <div className="chat-header">
          <div className="chat-header-left">
            <h2>FEMA PA Assistant</h2>
            <p>
              {conversationId
                ? `Session: ${conversationId.slice(0, 8)}…`
                : 'Ask questions about FEMA Public Assistance'}
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {/* Top-K selector */}
            <label style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'flex', gap: 6, alignItems: 'center' }}>
              Top-K
              <select
                value={topK}
                onChange={e => setTopK(Number(e.target.value))}
                style={{
                  background: 'var(--bg-input)',
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  color: 'var(--text-primary)',
                  padding: '2px 6px',
                  fontSize: 12,
                  cursor: 'pointer',
                }}
              >
                {[3, 5, 7, 10].map(k => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
            </label>

            {/* Global metadata toggle */}
            <button
              className={`btn-toggle-meta ${globalMetaOpen ? 'active' : ''}`}
              onClick={() => setGlobalMetaOpen(o => !o)}
              title="Toggle retrieval metadata panels"
            >
              {globalMetaOpen ? '🔍 Hide Metadata' : '🔍 Show Metadata'}
            </button>

            <button
              className={`btn-toggle-meta ${batchRunning ? 'active' : ''}`}
              onClick={runAssessmentAndExportPdf}
              title="Run all 15 required questions and export PDF"
              disabled={batchRunning || loading}
            >
              {batchRunning ? `Running ${batchProgress.done}/${batchProgress.total}` : 'Run 15 + Export PDF'}
            </button>

            {hasMessages && (
              <button
                className="btn-toggle-meta"
                onClick={handleNewChat}
                title="Start a new conversation"
              >
                ↺ New Chat
              </button>
            )}
          </div>
        </div>

        {/* Messages or welcome screen */}
        <div className="messages-container">
          {!hasMessages ? (
            <WelcomeScreen onSuggestion={text => handleSend(text)} />
          ) : (
            messages.map((msg, i) => (
              <ChatMessage
                key={i}
                message={msg}
                showMetaByDefault={globalMetaOpen}
              />
            ))
          )}

          {loading && (
            <div className="message-row assistant">
              <div className="loading-indicator">
                <div className="loading-dots">
                  <span /><span /><span />
                </div>
                Searching FEMA documents…
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Error banner */}
        {error && (
          <div className="error-banner">
            <span>⚠️</span>
            <span>{error}</span>
            <button
              onClick={() => setError(null)}
              style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: 14 }}
            >
              ✕
            </button>
          </div>
        )}

        {/* Input area */}
        <div className="input-area">
          <div className="input-wrapper">
            <textarea
              ref={textareaRef}
              className="msg-textarea"
              placeholder="Ask about FEMA Public Assistance procedures, funding, eligibility…"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              disabled={loading}
            />
            <button
              className="send-btn"
              onClick={() => handleSend()}
              disabled={!input.trim() || loading}
              title="Send message (Enter)"
            >
              ↑
            </button>
          </div>
          <p className="input-hint">
            Enter to send · Shift+Enter for new line · Top-K controls how many chunks are retrieved
          </p>
        </div>
      </div>
    </div>
  )
}
