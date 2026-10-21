// NutriScan AI web: everything that talks to the NutriScan AI backend (/api/v1).
// Every response is an envelope {success, code, message, data}. Every AI feature (scan, chat, meal ideas,
// insight) is answered by Gemini through the backend; nothing is faked on the page.
const CFG = window.SMF_CONFIG;

// ---------- Connection status (shown in the sidebar) ----------
// state: 'idle' (no call yet) | 'ok' | 'ai' (server fine, AI provider failed) | 'http' (server answered with an
// error) | 'offline'
const net = { state: 'idle', detail: '', lastFail: 0 };

// Short labels for the server's AI_UNAVAILABLE `details.reason`.
const AI_REASONS = {
  auth: 'API key rejected', not_configured: 'no API key', quota: 'quota reached', model: 'model not found',
  timeout: 'timed out', network: 'server offline from Gemini', bad_request: 'request rejected',
};

const getToken = () => (window.getAuthToken ? window.getAuthToken() : null);

// Defaults for paths an older config.js may not list yet.
const DEFAULT_ENDPOINTS = { guest: '/auth/guest', suggest: '/recipes/suggest' };

function endpoint(name) {
  const path = CFG.endpoints[name] ?? DEFAULT_ENDPOINTS[name];
  if (!path) { const e = new Error('disabled'); e.disabled = true; throw e; }
  return path;
}

// Calls the API and returns the envelope's `data`. Errors carry {status, code, serverMessage, details}.
async function callApi(path, options = {}) {
  const { timeoutMs = CFG.requestTimeoutMs, ...fetchOptions } = options;
  const token = getToken();
  const headers = { ...(token && { Authorization: 'Bearer ' + token }), ...(fetchOptions.headers || {}) };
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(CFG.apiBase + path, { ...fetchOptions, headers, signal: ctl.signal });
    const text = await res.text();
    let body = null;
    try { body = text ? JSON.parse(text) : null; } catch { body = null; }
    if (!res.ok || (body && body.success === false)) {
      const e = new Error(body?.message || 'HTTP ' + res.status);
      e.status = res.status; e.path = path;
      e.code = body?.code; e.serverMessage = body?.message; e.details = body?.details;
      if (res.status === 401 && token && window.onSessionExpired) window.onSessionExpired();
      // 4xx means the server is up and answered; 5xx is shown in the sidebar. AI_* errors mean the server is
      // fine but Gemini failed, so say that instead of "server error".
      if (/^AI_/.test(e.code || '')) { net.state = 'ai'; net.detail = AI_REASONS[e.details?.reason] || 'busy'; }
      else if (res.status >= 500) { net.state = 'http'; net.detail = `${e.code || 'HTTP ' + res.status}`; }
      else net.state = 'ok';
      throw e;
    }
    net.state = 'ok'; net.detail = '';
    return body && 'data' in body ? body.data : body;
  } catch (e) {
    if (!e.status && !(e instanceof SyntaxError)) {
      net.state = 'offline'; net.detail = e.name === 'AbortError' ? 'Request timed out' : 'Server not reachable';
      net.lastFail = Date.now();
      e.offline = true;
    }
    e.path = e.path || path;
    throw e;
  } finally { clearTimeout(timer); }
}

const jsonBody = obj => ({ body: JSON.stringify(obj), headers: { 'Content-Type': 'application/json' } });

// Plain-language reason a call fell back to local data or failed.
function reasonFor(e) {
  if (e.disabled) return '';
  if (e.notSignedIn) return 'Sign in or continue as a guest to use the AI.';
  if (e.offline) return net.detail === 'Request timed out'
    ? 'The server took too long to answer. The AI may be busy; try again in a moment.'
    : `The server at ${CFG.apiBase} did not respond. Is it running? (In Terminal: uvicorn app.main:app --reload)`;
  if (e.serverMessage) return e.serverMessage;
  if (e.status) return `The server answered ${e.status} for ${e.path}.`;
  return 'The reply was not in a shape the app understands.';
}

// Is the backend up? Updates the connection status shown in the sidebar.
async function pingServer() {
  try { await callApi('/health', { timeoutMs: 5000 }); return true; } catch { return false; }
}

// True when a background sync should not bother the server (it just failed).
const recentlyOffline = () => net.state === 'offline' && Date.now() - net.lastFail < 30000;
const signedIn = () => auth.mode === 'account' && !!getToken();
const notSignedInError = () => Object.assign(new Error('not signed in'), { notSignedIn: true });

// ---------- Mapping backend JSON to the shape the UI uses ----------
const num = v => { if (v === undefined || v === null || v === '') return null; const n = parseFloat(v); return Number.isFinite(n) ? n : null; };
const round1 = v => (v === null ? null : Math.round(v * 10) / 10);
const pick = (o, keys, d) => { for (const k of keys) { const v = o?.[k]; if (v !== undefined && v !== null && v !== '') return v; } return d; };
const textList = v => Array.isArray(v)
  ? v.map(x => typeof x === 'string' ? x : pick(x, ['text', 'name', 'description', 'title'], '')).map(String).filter(Boolean)
  : (typeof v === 'string' && v ? v.split(/\n|;|•/).map(s => s.trim()).filter(Boolean) : []);

// Backend Nutrients → the short keys the UI uses.
const fromNutrients = n => ({
  cal: Math.round(num(n?.calories) ?? 0),
  protein: round1(num(n?.protein_g) ?? 0),
  carbs: round1(num(n?.carbohydrates_g) ?? 0),
  fat: round1(num(n?.fat_g) ?? 0),
  fibre: round1(num(n?.fiber_g)),
  sodium: num(n?.sodium_mg) === null ? null : Math.round(num(n.sodium_mg)),
  sugar: round1(num(n?.sugar_g)),
  satFat: round1(num(n?.saturated_fat_g)),
});

const toNutrients = m => ({
  calories: +m.cal || 0, protein_g: +m.protein || 0, carbohydrates_g: +m.carbs || 0, fat_g: +m.fat || 0,
  saturated_fat_g: +m.satFat || 0, fiber_g: +m.fibre || 0, sugar_g: +m.sugar || 0, sodium_mg: +m.sodium || 0,
});

// A ScanResult from POST /scans → the food object the scan page renders.
function fromScan(s) {
  const items = (s.items || []).map(i => ({
    id: i.id, name: i.name, grams: i.quantity_g, serving: i.serving_description, confidence: i.confidence,
    cal: Math.round(num(i.nutrients?.calories) ?? 0), protein: round1(num(i.nutrients?.protein_g) ?? 0),
    nutritionSource: i.nutrition_source || 'estimate',
  }));
  const name = s.meal_name || (items[0] && items[0].name) || 'Your meal';
  const health = s.health || null;
  return {
    name, ...fromNutrients(s.totals),
    scanId: s.id, mealType: s.meal_type, imageUrl: s.image_url, loggedIntakeId: s.logged_intake_id,
    street: isStreetFood([name, ...items.map(i => i.name)].join(' ')),
    summary: items.length ? items.map(i => `${i.name} (${i.serving || i.grams + ' g'})`).join(', ') : '',
    items, health, classifier: s.classifier, aiModel: s.ai_model,
    pros: [], cons: (health?.flags || []).map(f => f.message), tips: health?.tips || [], ingredients: [],
  };
}

// An IntakeEntry → a meal in the local log.
function fromEntry(e) {
  const names = [e.name, ...(e.items || []).map(i => i.name)].join(' ');
  return {
    ...fromNutrients(e.totals), id: e.id, remoteId: e.id, scanId: e.scan_id || null, name: e.name,
    at: Date.parse(e.eaten_at) || Date.now(), mealType: e.meal_type, source: e.source,
    street: e.is_street_food ?? isStreetFood(names), home: e.is_home_cooked ?? false, synced: true,
  };
}

const mealTypeAt = t => { const h = new Date(t).getHours(); return h >= 5 && h <= 10 ? 'breakfast' : h >= 11 && h <= 15 ? 'lunch' : h >= 19 && h <= 22 ? 'dinner' : 'snack'; };

// ---------- Photo prep ----------
// Phone photos are often 4-8 MB. Shrinking them keeps the upload fast (the server resizes to 1024 px anyway).
async function prepareImage(file, maxDim = 1280) {
  if (!file.type.startsWith('image/') || file.type === 'image/gif') return file;
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, maxDim / Math.max(bmp.width, bmp.height));
    if (scale === 1 && file.size < 600000 && /jpe?g|png|webp/.test(file.type)) { bmp.close?.(); return file; }
    const c = document.createElement('canvas');
    c.width = Math.round(bmp.width * scale); c.height = Math.round(bmp.height * scale);
    c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
    bmp.close?.();
    const blob = await new Promise(res => c.toBlob(res, 'image/jpeg', 0.85));
    return blob ? new File([blob], file.name.replace(/\.\w+$/, '') + '.jpg', { type: 'image/jpeg' }) : file;
  } catch { return file; }
}

// ---------- Scan ----------
const LABEL_HINT = 'Photo of a packaged food or its nutrition label. Estimate one serving of the product.';

// The real pipeline: classifier hints + Gemini vision on the server.
// Throws for real failures (not food, AI unavailable, offline) so the page can show the reason.
async function analyzeImage(file, mode, mealType) {
  if (!signedIn()) throw notSignedInError();
  const img = await prepareImage(file);
  const form = new FormData();
  form.append(CFG.imageField, img, img.name);
  if (mode === 'label') form.append('description', LABEL_HINT);
  if (mealType && mealType !== 'auto') form.append('meal_type', mealType);
  const data = await callApi(endpoint('scans'), { method: 'POST', body: form, timeoutMs: CFG.aiTimeoutMs });
  return fromScan(data);
}

// ---------- Chat about a scanned food (NutriBuddy, Gemini) ----------
const chatSessions = new Map(); // scanId → chat session id

// Gemini answers with the scan linked as context. Returns {text, markdown, tools[]} or {error} with the reason.
async function askBot(question, food) {
  const key = food.scanId || 'general';
  try {
    if (!signedIn()) throw notSignedInError();
    let sessionId = chatSessions.get(key);
    if (!sessionId) {
      const session = await callApi(endpoint('chat'), { method: 'POST', ...jsonBody(food.scanId ? { scan_id: food.scanId } : {}) });
      sessionId = session.id;
      chatSessions.set(key, sessionId);
    }
    const form = new FormData();
    form.append('text', question);
    const r = await callApi(`${endpoint('chat')}/${sessionId}/messages`, { method: 'POST', body: form, timeoutMs: CFG.aiTimeoutMs });
    const msg = r.assistant_message;
    return { text: msg.content, markdown: true, tools: msg.tool_calls || [] };
  } catch (e) {
    if (e.status === 404) chatSessions.delete(key);
    return { error: true, text: "Couldn't get an answer from the AI. " + reasonFor(e) };
  }
}

// ---------- Meal ideas from the ingredients in the room ----------
// A RecipeOut from POST /recipes/suggest → the recipe card shape the cook page renders.
function fromRecipe(r, i) {
  const n = fromNutrients(r.nutrients);
  return {
    id: 'ai-' + i, ai: true, from: '', keys: [],
    meal: r.name, why: r.why, time: r.time_minutes, gear: r.kitchen,
    cal: n.cal, protein: n.protein, carbs: n.carbs, fat: n.fat, fibre: n.fibre, sodium: n.sodium, sugar: n.sugar,
    steps: r.steps || [], ingredientsList: r.ingredients || [],
  };
}

// Gemini meal ideas for what the person has, within their kitchen, diet and allergies (from the profile).
async function suggestMeals(items, profile) {
  try {
    if (!signedIn()) throw notSignedInError();
    const r = await callApi(endpoint('suggest'), {
      method: 'POST', timeoutMs: CFG.aiTimeoutMs,
      ...jsonBody({ ingredients: items.slice(0, 20), kitchen: profile.kitchen || 'burner', count: 3 }),
    });
    return { source: 'ai', meals: r.meals.map(fromRecipe) };
  } catch (e) {
    return { source: 'error', meals: [], reason: reasonFor(e) };
  }
}

// ---------- Daily insight (dashboard) ----------
const fetchInsight = () => callApi(endpoint('insight'), { timeoutMs: CFG.aiTimeoutMs });

// ---------- Meal log ⇄ intake entries ----------
async function fetchRemoteMeals() {
  const out = [];
  for (let page = 1; page <= 5; page++) {
    const r = await callApi(`${endpoint('intake')}?days=90&page=${page}&page_size=100`);
    out.push(...r.items.map(fromEntry));
    if (out.length >= r.total || !r.items.length) break;
  }
  return out;
}

// Scanned meals are logged through the scan (keeps every item and its grams); others as a manual entry.
async function pushMeal(m) {
  if (m.scanId) {
    try {
      const entry = await callApi(`${endpoint('scans')}/${m.scanId}/log`, {
        method: 'POST', ...jsonBody({ meal_type: m.mealType || mealTypeAt(m.at), eaten_at: new Date(m.at).toISOString(), is_street_food: !!m.street }),
      });
      return entry.id;
    } catch (e) {
      if (e.code === 'ALREADY_LOGGED' && e.details?.intake_id) return e.details.intake_id;
      if (e.status !== 404) throw e; // scan deleted: fall through and log the numbers manually
    }
  }
  const entry = await callApi(endpoint('intake'), {
    method: 'POST',
    ...jsonBody({
      name: m.name.slice(0, 120), meal_type: m.mealType || mealTypeAt(m.at), eaten_at: new Date(m.at).toISOString(),
      is_street_food: !!m.street, is_home_cooked: !!m.home,
      items: [{ name: m.name.slice(0, 120), serving_description: m.home ? 'home-cooked portion' : '1 serving', nutrients: toNutrients(m) }],
    }),
  });
  return entry.id;
}

// keepalive lets the request finish while the page is closing.
const deleteMeal = (id, keepalive = false) => callApi(`${endpoint('intake')}/${encodeURIComponent(id)}`, { method: 'DELETE', keepalive });

// ---------- Profile ----------
const ACTIVITY_TO_API = { sitting: 'sedentary', light: 'light', active: 'active' };
const ACTIVITY_FROM_API = { sedentary: 'sitting', light: 'light', moderate: 'active', active: 'active', very_active: 'active' };
const DIET_TO_API = { Vegan: 'vegan', Vegetarian: 'veg', Eggetarian: 'eggetarian', 'Non-vegetarian': 'non_veg' };
const DIET_FROM_API = Object.fromEntries(Object.entries(DIET_TO_API).map(([k, v]) => [v, k]));

async function fetchRemoteProfile() {
  const me = await callApi(endpoint('me'));
  const p = me.profile || {}, out = {};
  if (me.name) out.name = me.name.slice(0, 40);
  if (p.age) out.age = p.age;
  if (p.sex) out.sex = p.sex;
  if (p.weight_kg) out.weight = p.weight_kg;
  if (p.height_cm) out.height = p.height_cm;
  if (p.activity_level) out.activity = ACTIVITY_FROM_API[p.activity_level];
  if (p.goal) out.goalDir = p.goal;
  if (p.diet_type) out.diet = DIET_FROM_API[p.diet_type];
  if (p.kitchen) out.kitchen = p.kitchen;
  if (Array.isArray(p.allergies)) out.allergies = p.allergies;
  if (me.onboarding_complete) {
    const t = await fetchTargets();
    if (t?.calories) out.goal = Math.round(t.calories);
  }
  return out;
}

const fetchTargets = () => callApi(endpoint('targets'));

const pushProfile = p => callApi(endpoint('profile'), {
  method: 'PUT',
  ...jsonBody({
    age: Math.round(+p.age), sex: p.sex, height_cm: +p.height, weight_kg: +p.weight,
    activity_level: ACTIVITY_TO_API[p.activity] || 'light', goal: p.goalDir || 'maintain',
    diet_type: DIET_TO_API[p.diet] || 'veg', kitchen: p.kitchen || 'burner',
    // Only when known: a partial profile (e.g. "Suggest a calorie goal") must not wipe saved allergies.
    ...(Array.isArray(p.allergies) && { allergies: p.allergies }),
  }),
});

// The first-run choices alone: a partial update, so it never invents an age, height or weight.
const pushProfileChoices = p => callApi(endpoint('profile'), {
  method: 'PUT',
  ...jsonBody({ goal: p.goalDir || 'maintain', diet_type: DIET_TO_API[p.diet] || 'veg', kitchen: p.kitchen || 'burner' }),
});

// Daily totals + server-computed targets (the UI's single source of truth for goals).
const fetchDaily = () => callApi(endpoint('intake') + '/daily');
// Multi-day summary incl. the server-computed street-free streak and home-cooked count.
const fetchSummary = (days = 7) => callApi(`${endpoint('intake')}/summary?days=${days}`);
