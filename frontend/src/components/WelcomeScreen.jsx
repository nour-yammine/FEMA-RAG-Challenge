// src/components/WelcomeScreen.jsx

const SUGGESTIONS = [
  'What is the Cost Estimating Format (CEF) and what types of projects is it used for?',
  'What is Strategic Funds Management (SFM) and what is its purpose?',
  'What types of entities are eligible to apply for FEMA Public Assistance?',
  'What are the two main types of federal disaster declarations?',
  'Explain the difference between Part A and Part B of the CEF cost estimate.',
  'What does the PAPPG say about the use of "must" versus "should" in policy guidance?',
]

export default function WelcomeScreen({ onSuggestion }) {
  return (
    <div className="welcome">
      <div className="welcome-icon">🏛️</div>
      <h2>FEMA Public Assistance Assistant</h2>
      <p>
        Ask questions about FEMA disaster recovery procedures, funding policies,
        cost estimation, and applicant guidance. Answers are grounded in the
        official FEMA Public Assistance documents.
      </p>
      <div className="suggestions-grid">
        {SUGGESTIONS.map((s, i) => (
          <button
            key={i}
            className="suggestion-btn"
            onClick={() => onSuggestion(s)}
          >
            {s.length > 90 ? s.slice(0, 88) + '…' : s}
          </button>
        ))}
      </div>
    </div>
  )
}
