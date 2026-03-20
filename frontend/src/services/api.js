// src/services/api.js — All calls to the FastAPI backend

const BASE_URL = '/api'

/**
 * Send a chat message and receive an answer with retrieval metadata.
 * @param {string} message
 * @param {string|null} conversationId
 * @param {number} topK
 * @returns {Promise<{answer, conversation_id, sources, num_chunks_retrieved, model_used}>}
 */
export async function sendMessage(message, conversationId = null, topK = 5) {
  const body = { message, top_k: topK }
  if (conversationId) body.conversation_id = conversationId

  const res = await fetch(`${BASE_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Server error: ${res.status}`)
  }

  return res.json()
}

/**
 * Get health status + chunk count from the backend.
 */
export async function getHealth() {
  const res = await fetch(`${BASE_URL}/health`)
  if (!res.ok) throw new Error('Backend unreachable')
  return res.json()
}

/**
 * Get ingestion manifest — which documents are loaded.
 */
export async function getIngestionStatus() {
  const res = await fetch(`${BASE_URL}/ingestion-status`)
  if (!res.ok) throw new Error('Could not fetch ingestion status')
  return res.json()
}

/**
 * Delete a conversation's history from the backend.
 */
export async function deleteConversation(conversationId) {
  const res = await fetch(`${BASE_URL}/conversation/${conversationId}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error('Could not delete conversation')
  return res.json()
}
