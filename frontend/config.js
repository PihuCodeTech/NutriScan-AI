// ScanMyFood web: connection settings for the NutriScan AI backend (FastAPI, /api/v1).
window.SMF_CONFIG = {
  // When the backend serves this page (http://localhost:8000/app/), talk to the same origin.
  // When the page is opened some other way (another dev server, file://), fall back to the local backend.
  apiBase: /^https?:$/.test(location.protocol) && location.pathname.startsWith('/app')
    ? location.origin + '/api/v1'
    : 'http://localhost:8000/api/v1',

  // Paths are appended to apiBase.
  endpoints: {
    register: '/auth/register',   // POST {email, password, name} → {access_token, user}
    login: '/auth/login',         // POST {email, password} → {access_token, user}
    me: '/users/me',              // GET → {id, email, name, profile, onboarding_complete}
    profile: '/users/me/profile', // PUT partial profile
    targets: '/users/me/targets', // GET daily targets computed from the profile
    scans: '/scans',              // POST multipart image (+description) → ScanResult; POST /scans/{id}/log
    intake: '/intake',            // GET list, POST manual entry, DELETE /intake/{id}
    insight: '/insights/daily',   // GET AI daily insight
    chat: '/chat/sessions',       // POST session {scan_id}; POST /chat/sessions/{id}/messages (multipart text)
    suggest: '/recipes/suggest',  // POST {ingredients, kitchen, count} → Gemini meal ideas
    guest: '/auth/guest',         // POST → a throw-away guest account {access_token, user}
  },

  // Name of the multipart field that carries the photo.
  imageField: 'image',

  // AI calls can take 10–40 s, and up to ~95 s in the worst case: the backend gives Gemini 30 s per attempt and
  // makes up to 3 attempts (primary, primary again, fallback model). Keep aiTimeoutMs above that, or the page
  // gives up while the server is still working.
  requestTimeoutMs: 20000,
  aiTimeoutMs: 120000,
};
