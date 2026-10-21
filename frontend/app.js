// NutriScan AI web: app logic and pages.
// Load order in index.html: config.js, data.js, api.js, auth.js, app.js

// ---------- Small helpers ----------
const DAY = 86400000;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const has = v => v !== null && v !== undefined && v !== '';
const sum = (list, key) => list.reduce((total, m) => total + (+m[key] || 0), 0);
const sameDay = (a, b) => new Date(a).toDateString() === new Date(b).toDateString();
const uid = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
const dash = v => has(v) ? v : '–';
const dateLabel = t => new Date(t).toLocaleDateString('en', { weekday: 'short', day: 'numeric', month: 'short' });

function md(text) {
  const lines = esc(text).split(/\n/);
  let html = '', inList = false;
  for (const raw of lines) {
    const line = raw.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/(^|\s)\*(\S.*?)\*(?=\s|$)/g, '$1<i>$2</i>');
    const item = /^\s*(?:[-*•]|\d+\.)\s+(.*)$/.exec(line);
    if (item) { if (!inList) { html += '<ul>'; inList = true; } html += `<li>${item[1]}</li>`; continue; }
    if (inList) { html += '</ul>'; inList = false; }
    if (line.trim()) html += `<p>${line}</p>`;
  }
  return html + (inList ? '</ul>' : '');
}

let toastTimer, toastExpire = null;
// A short message at the bottom. With an action (e.g. Undo) it stays longer (8 s), offers one button and
// takes keyboard focus; the timer pauses while the pointer is over it, and if focus is still on it when it
// closes, focus goes to `action.refocus()`. A toast that replaces an unanswered one still lets that one expire (e.g. finish a removal).
function toast(text, action) {
  clearTimeout(toastTimer);
  const before = toastExpire; toastExpire = null; before?.();
  $('#toast')?.remove();
  const t = document.createElement('div');
  t.id = 'toast'; t.setAttribute('role', 'status');
  t.append(Object.assign(document.createElement('span'), { textContent: text }));
  document.body.append(t);
  const close = expired => {
    clearTimeout(toastTimer);
    if (toastExpire === done) toastExpire = null;
    const hadFocus = t.contains(document.activeElement);
    t.remove();
    if (expired) action?.expire?.();
    if (hadFocus) action?.refocus?.()?.focus();
  };
  const done = () => close(true);
  const arm = () => { clearTimeout(toastTimer); toastTimer = setTimeout(done, action ? 8000 : 4000); };
  if (action) {
    toastExpire = action.expire ? () => action.expire() : null;
    const b = Object.assign(document.createElement('button'), { type: 'button', className: 'toast-act', textContent: action.label });
    b.onclick = () => { toastExpire = null; close(false); action.run(); };
    t.append(b);
    t.addEventListener('pointerenter', () => clearTimeout(toastTimer));
    t.addEventListener('pointerleave', arm);
    b.focus();
  }
  arm();
}

// ---------- Icons ----------
// One line-icon family (24 px grid, 1.75 stroke, round caps), drawn here so the app needs no icon font.
const ICONS = {
  home: '<path d="M3.5 10.5 12 3.5l8.5 7"/><path d="M5.5 9v10.5a1 1 0 0 0 1 1h3.5v-6h4v6h3.5a1 1 0 0 0 1-1V9"/>',
  camera: '<path d="M4 8.5a2 2 0 0 1 2-2h1.8l1.5-2.2h5.4l1.5 2.2H18a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"/><circle cx="12" cy="13" r="3.4"/>',
  history: '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.4"/><path d="M3.5 3.8v4.6h4.6"/><path d="M12 7.5V12l3 2"/>',
  cook: '<path d="M4 11h13v1.5a6 6 0 0 1-6 6h-1a6 6 0 0 1-6-6Z"/><path d="M17 12.5h3.5"/><path d="M8.5 4.5c-.8 1 .8 2 0 3.5M12.5 4.5c-.8 1 .8 2 0 3.5"/>',
  award: '<circle cx="12" cy="9" r="5.5"/><path d="m8.7 13.6-1.4 6.9 4.7-2.6 4.7 2.6-1.4-6.9"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0"/>',
  sprout: '<path d="M12 20.5V12"/><path d="M12 12c0-4 2.8-6.8 7.5-6.8 0 4-2.8 6.8-7.5 6.8Z"/><path d="M12 14.5c0-3-2.3-5.2-6.5-5.2 0 3 2.3 5.2 6.5 5.2Z"/>',
  flame: '<path d="M12 21c3.9 0 6.5-2.6 6.5-6.3 0-3-1.8-5.3-3.7-7.2-.4 1.8-1.3 3-2.5 3.6.3-3.2-1.1-6.1-4.1-7.8.3 3.1-1.5 5-2.6 6.8A7.6 7.6 0 0 0 5.5 14.7C5.5 18.4 8.1 21 12 21Z"/>',
  trophy: '<path d="M8 4h8v5a4 4 0 0 1-8 0Z"/><path d="M8 6H5.5a2.8 2.8 0 0 0 2.8 3.8M16 6h2.5a2.8 2.8 0 0 1-2.8 3.8"/><path d="M12 13v3.5"/><path d="M9 20.5h6l-.7-4h-4.6Z"/>',
  tag: '<path d="M3.5 12V4.5a1 1 0 0 1 1-1H12l8.5 8.5-8.5 8.5Z"/><circle cx="8" cy="8" r="1.4"/>',
  check: '<path d="m5 12.5 4.3 4.3L19 7.3"/>',
  alert: '<path d="M10.3 4.3 2.9 17.5A2 2 0 0 0 4.6 20.5h14.8a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0Z"/><path d="M12 9.5v4"/><path d="M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5"/><path d="M12 7.8h.01"/>',
  image: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="m20.5 15.5-4.8-4.8-9.2 8.8"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  download: '<path d="M12 4v11"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/><path d="M5 20h14"/>',
  chat: '<path d="M5.5 5h13a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H11l-4.5 3.5V17h-1a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z"/><path d="M8.5 10h7M8.5 13h4.5"/>',
  send: '<path d="M4.5 11.5 20 4l-6.5 16-2.6-6.4Z"/><path d="m10.9 13.6 4.6-4.6"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  trash: '<path d="M4.5 7h15"/><path d="M9.5 7V4.5h5V7"/><path d="m6.5 7 .9 12.5h9.2L17.5 7"/>',
  swap: '<path d="M7 4.5 3.5 8 7 11.5"/><path d="M3.5 8h13"/><path d="m17 12.5 3.5 3.5-3.5 3.5"/><path d="M20.5 16h-13"/>',
};
const icon = (name, cls = '') => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICONS[name] || ''}</svg>`;
document.querySelectorAll('[data-icon]').forEach(el => el.insertAdjacentHTML('afterbegin', icon(el.dataset.icon)));

// ---------- Loading indicators ----------
// AI calls take 10–40 s. A spinning circle, a seconds counter and what the AI is doing right now show that the
// page is still working. Each step is [seconds elapsed, message].
const LOADING_STEPS = {
  scan: [[0, 'Uploading your photo…'], [3, 'Spotting each item on the plate…'], [10, 'Estimating portions and nutrients…'],
    [25, 'Adding up the totals and writing tips…'], [45, 'Still working. The AI is busy right now; this can take up to a minute.']],
  ideas: [[0, 'Finding meals you can make…'], [15, 'Checking them against your diet and kitchen…'],
    [45, 'Still working. The AI is busy right now; this can take up to a minute.']],
};
const loadingStep = (kind, since) => {
  const s = (Date.now() - since) / 1000;
  return LOADING_STEPS[kind].filter(([at]) => s >= at).pop()[1];
};
const loadingTime = since => `${Math.floor((Date.now() - since) / 1000)} s`;

function loadingHtml(kind, since) {
  return `<div class="loading" role="status" data-kind="${kind}" data-since="${since}">
    <span class="spinner big" aria-hidden="true"></span>
    <div><b class="loading-msg">${esc(loadingStep(kind, since))}</b><small class="loading-time" aria-hidden="true">${loadingTime(since)}</small></div></div>`;
}

// One ticker updates every loading card on screen, so it keeps going if the page is re-rendered meanwhile.
setInterval(() => document.querySelectorAll('.loading[data-since]').forEach(el => {
  const since = +el.dataset.since;
  const msg = el.querySelector('.loading-msg'), next = loadingStep(el.dataset.kind, since);
  if (msg.textContent !== next) msg.textContent = next; // re-setting the same text would be re-announced
  el.querySelector('.loading-time').textContent = loadingTime(since);
}), 1000);

// Puts a small spinner in a button while it waits; call again with on=false to restore it.
function busyButton(btn, on, label) {
  if (!btn) return;
  if (on) {
    btn.dataset.idle = btn.dataset.idle ?? btn.innerHTML;
    btn.innerHTML = `<span class="spinner" aria-hidden="true"></span>${esc(label || btn.textContent)}`;
  } else if (btn.dataset.idle !== undefined) {
    btn.innerHTML = btn.dataset.idle;
    delete btn.dataset.idle;
  }
  btn.disabled = on;
  btn.setAttribute('aria-busy', on);
}

// ---------- State (saved per person in localStorage) ----------
const DEFAULT_PROFILE = { name: '', age: 20, sex: 'other', weight: 65, height: 170, activity: 'light', goal: 2000, goalDir: 'maintain', diet: 'Vegetarian', kitchen: 'burner', allergies: [] };
let state;
let scan = { file: null, url: '', mode: 'meal', result: null, chat: [], added: false, busy: false, since: 0 };
let cook = { pantry: '', results: null, busy: false, since: 0, focus: '' };
let ui = { histFilter: 'all' };
// Numbers the server owns (goals and the street-free streak), so the UI agrees with the AI. null = not loaded.
let serverTargets = null, serverStreak = null;
// 'profile' or 'default': whether the server's goals come from the person's own age, height and weight.
let serverBasis = null;

const storeKey = () => 'smf:' + authUid();

// Every account (guest or not) starts empty: no sample meals.
function emptyState() {
  return { v: 2, sample: false, profile: { ...DEFAULT_PROFILE }, startedOn: Date.now(), badges: {}, claims: [], stats: { labelScans: 0, mealScans: 0 }, profileTouched: false, meals: [] };
}

// Removes the sample meals and everything that was earned from them.
function dropSample(startedOn) {
  state.meals = state.meals.filter(m => !m.sample);
  state.sample = false; state.badges = {}; state.claims = [];
  state.startedOn = startedOn;
}

function loadState() {
  let raw = null;
  try { raw = JSON.parse(localStorage.getItem(storeKey())); } catch { raw = null; }
  state = raw || emptyState();
  state.profile = { ...DEFAULT_PROFILE, ...state.profile };
  state.badges = state.badges || {};
  state.claims = state.claims || [];
  state.stats = { labelScans: 0, mealScans: 0, ...state.stats };
  state.meals = state.meals || [];
  state.startedOn = state.startedOn || Date.now();
}

function save() {
  try { localStorage.setItem(storeKey(), JSON.stringify(state)); }
  catch { toast('Could not save on this device. Storage may be full or blocked.'); }
}

// ---------- Derived numbers ----------
const todayMeals = () => state.meals.filter(m => sameDay(m.at, Date.now()));
const weekMeals = () => state.meals.filter(m => m.at >= Date.now() - 7 * DAY);
const lastStreetAt = () => state.meals.filter(m => m.street).reduce((latest, m) => Math.max(latest, m.at), 0);
const runStart = () => Math.max(lastStreetAt(), state.startedOn);
const streakDays = () => serverStreak != null ? serverStreak : Math.max(0, Math.floor((Date.now() - runStart()) / DAY));

function bestStreak() {
  const marks = [state.startedOn, ...state.meals.filter(m => m.street && m.at >= state.startedOn).map(m => m.at), Date.now()].sort((a, b) => a - b);
  let best = 0;
  for (let i = 1; i < marks.length; i++) best = Math.max(best, Math.floor((marks[i] - marks[i - 1]) / DAY));
  return best;
}

// Completed calendar days since the start with no street meal logged.
function streetFreeDays() {
  let n = 0;
  const day = new Date(state.startedOn); day.setHours(0, 0, 0, 0);
  const end = new Date(); end.setHours(0, 0, 0, 0);
  for (; day < end; day.setDate(day.getDate() + 1)) if (!state.meals.some(m => m.street && sameDay(m.at, day))) n++;
  return n;
}

const homeCount = () => state.meals.filter(m => m.home).length;
const points = () => streetFreeDays() * 10 + homeCount() * 5 + state.claims.length * 50;
function level(pts) {
  const n = Math.floor(pts / 100) + 1;
  return { n, name: LEVELS[Math.min(n - 1, LEVELS.length - 1)], into: pts % 100 };
}
const claimable = () => Math.floor(streakDays() / 7) > state.claims.filter(t => t >= runStart()).length;
const badgeCtx = () => ({ streak: streakDays(), home: homeCount(), labelScans: state.stats.labelScans, scans: state.stats.mealScans + state.stats.labelScans });

function checkBadges(silent) {
  const ctx = badgeCtx();
  BADGES.forEach(b => {
    if (!state.badges[b.id] && b.test(ctx)) {
      state.badges[b.id] = Date.now();
      if (!silent) toast(`Badge unlocked: ${b.name}`);
    }
  });
  save();
}

function targets() {
  if (serverTargets) return serverTargets;  // computed by the backend from the profile (matches the AI)
  const p = state.profile, goal = +p.goal;
  return { cal: goal, protein: Math.max(45, Math.round(p.weight * 0.8)), carbs: Math.round(goal * 0.5 / 4), fat: Math.round(goal * 0.3 / 9) };
}

// Pull the server-computed targets and street-free streak; the dashboard and rewards read these.
async function refreshServerNumbers() {
  if (!signedIn()) { serverTargets = null; serverStreak = null; serverBasis = null; return; }
  try {
    const t = await fetchTargets();
    if (t && t.calories) serverTargets = { cal: Math.round(t.calories), protein: Math.round(t.protein_g), carbs: Math.round(t.carbohydrates_g), fat: Math.round(t.fat_g) };
    if (t && t.basis) serverBasis = t.basis;
  } catch { /* offline: keep the local estimate */ }
  try {
    const sum = await fetchSummary(7);
    if (sum && typeof sum.street_free_streak_days === 'number') serverStreak = sum.street_free_streak_days;
  } catch { /* offline */ }
}

// ---------- Live insights and body impact ----------
function insights(today) {
  const tg = targets(), out = [];
  const cal = sum(today, 'cal');
  const known = key => today.filter(m => has(m[key]));
  if (!today.length) out.push({ tone: 'info', text: 'Nothing logged today. Scan your first meal to get feedback.' });
  if (today.some(m => m.street)) {
    const best = bestStreak();
    out.push({ tone: 'info', text: `Street food today, so a fresh street-free run starts${best ? ` (your best so far: ${best} day${best === 1 ? '' : 's'})` : ''}. A plate with dal, curd or sprouts next balances it out.` });
  }
  if (cal > tg.cal) out.push({ tone: 'warn', text: `You are ${Math.round(cal - tg.cal)} kcal over your goal for today. Keep the rest of the day to fruit, curd or salad.` });
  else if (cal > tg.cal * 0.9) out.push({ tone: 'info', text: 'You are close to your calorie goal for the day. Choose something light for the rest of it.' });
  if (known('sodium').length && sum(today, 'sodium') > 2000) out.push({ tone: 'warn', text: `Sodium is at ${Math.round(sum(today, 'sodium'))} mg today, past the 2000 mg daily limit. Skip packaged snacks and pickles, and drink water.` });
  if (today.length >= 2 && known('fibre').length && sum(today, 'fibre') < 10) out.push({ tone: 'info', text: 'Fibre is low so far. Add a salad, a fruit or a bowl of dal.' });
  if (today.length && cal >= tg.cal * 0.5 && sum(today, 'protein') < tg.protein * 0.5) out.push({ tone: 'info', text: 'Protein is low for this point in the day. Dal, curd, paneer, eggs or sprouts would help.' });
  const streak = streakDays();
  if (!today.some(m => m.street) && streak >= 3 && streak < 7) out.push({ tone: 'good', text: `${7 - streak} more street-free days to your weekly reward.` });
  if (!out.length) out.push({ tone: 'good', text: 'Good day so far. Keep it up.' });
  const order = { warn: 0, info: 1, good: 2 };
  return out.sort((a, b) => order[a.tone] - order[b.tone]).slice(0, 3);
}

// A rough weekly read of what the logged food may be doing to four body systems.
// General guidance from thresholds (fibre 25 g, sodium 2000 mg, sugar 50 g a day), not a diagnosis.
function bodyImpact() {
  const w = weekMeals();
  if (w.length < 3) return null;
  const days = new Set(w.map(m => new Date(m.at).toDateString())).size;
  const avg = key => (w.filter(m => has(m[key])).length >= 3 ? sum(w.filter(m => has(m[key])), key) / days : null);
  const street = w.filter(m => m.street).length;
  const oily = w.filter(m => m.street || m.fat >= 20).length;
  const fibre = avg('fibre'), sodium = avg('sodium'), sugar = avg('sugar');

  // Nutrition patterns from the week's logged meals — not organ diagnoses.
  const salt = sodium === null ? null : sodium > 2300 ? 2 : sodium > 1800 ? 1 : 0;
  const saltText = sodium === null ? 'Not enough salt data yet.' : `Sodium averages ${Math.round(sodium)} mg a day (WHO suggests under ~2000 mg). Instant noodles, chips and pickles add up fast.`;

  const sugarL = sugar === null ? null : sugar > 50 ? 2 : sugar > 35 ? 1 : 0;
  const sugarText = sugar === null ? 'Not enough sugar data yet.' : `Sugar averages ${Math.round(sugar)} g a day. Sweet drinks, chai and desserts are the usual sources.`;

  const fibreL = fibre === null ? null : fibre < 15 ? 2 : fibre < 25 ? 1 : 0;
  const fibreText = fibre === null ? 'Not enough fibre data yet.' : `Fibre averages ${Math.round(fibre)} g a day (aim for ~25 g). Dal, vegetables, fruit and sprouts help.`;

  const friedL = oily >= 4 ? 2 : oily >= 2 ? 1 : 0;
  const meals = n => (n === 1 ? 'meal' : 'meals');
  const friedCount = !oily ? 'No fried or street meals this week'
    : street === oily ? `${street} street ${meals(street)} this week`
    : `${oily} fried or street ${meals(oily)} this week${street ? `, ${street} from the street` : ''}`;
  const friedText = `${friedCount}. Deep-fried food eaten often is worth cutting back.`;

  return [
    { label: 'Salt', level: salt, text: saltText },
    { label: 'Sugar', level: sugarL, text: sugarText },
    { label: 'Fibre', level: fibreL, text: fibreText },
    { label: 'Fried food', level: friedL, text: friedText },
  ];
}

// ---------- Pieces of UI ----------
// A tray compartment that fills up like a serving: the level shows how much of today's goal is eaten.
function cell(label, value, goal, unit, tone) {
  const pct = Math.min(100, Math.round(value / goal * 100));
  return `<div class="cell ${value > goal ? 'over' : ''}" style="--fill:${pct}%;--tone:${tone}">
    <span class="cell-label">${label}</span><b class="num">${Math.round(value)}<span class="unit">${unit}</span></b>
    <span class="cell-goal">of ${goal}${unit} · ${Math.round(value / goal * 100)}%</span></div>`;
}

function weekChart() {
  const goal = +state.profile.goal;
  const days = [...Array(7)].map((_, i) => {
    const d = Date.now() - (6 - i) * DAY;
    const list = state.meals.filter(m => sameDay(m.at, d));
    return { label: new Date(d).toLocaleDateString('en', { weekday: 'short' }), cal: sum(list, 'cal'), streetCal: sum(list.filter(m => m.street), 'cal') };
  });
  const top = Math.max(goal, ...days.map(d => d.cal)) * 1.12;  // headroom for the value labels
  // One street snack shouldn't paint the whole day: only its share of the bar is tinted.
  const streetNote = d => d.streetCal ? `, ${Math.round(d.streetCal)} kcal of it street food` : '';
  const cols = days.map(d => `<div class="bar-col" title="${d.label}: ${Math.round(d.cal)} kcal${streetNote(d)}">
      ${d.cal ? `<small class="bar-v num">${Math.round(d.cal)}</small>` : ''}<span class="bar" style="height:${d.cal / top * 100}%">${d.streetCal ? `<i class="bar-street" style="height:${d.streetCal / d.cal * 100}%"></i>` : ''}</span></div>`).join('');
  const empty = days.every(d => !d.cal)
    ? '<p class="chart-empty">No meals logged in the last 7 days. Scan or log a meal and it shows up here.</p>' : '';
  const summary = days.map(d => `${d.label} ${Math.round(d.cal)} kcal${d.streetCal ? ` (${Math.round(d.streetCal)} kcal street food)` : ''}`).join(', ');
  return `<div class="bars" role="img" aria-label="Calories over the last 7 days against your goal of ${goal} kcal: ${summary}.">
    <div class="bars-plot" aria-hidden="true"><span class="goal-line" style="bottom:${goal / top * 100}%"></span>${cols}${empty}</div>
    <div class="bars-x" aria-hidden="true">${days.map(d => `<span>${d.label}</span>`).join('')}</div></div>`;
}

// Filled dots are street-free days; the next one is today, in progress.
const dots = streak => `<div class="dots" aria-hidden="true">${[...Array(7)].map((_, i) => `<i class="${i < streak % 7 || (streak && streak % 7 === 0) ? 'full' : i === streak % 7 ? 'now' : ''}"></i>`).join('')}</div>`;

function impactHtml() {
  const rows = bodyImpact();
  if (!rows) return `<div class="empty-inline">${icon('info')}<p>Log at least 3 meals this week to see your salt, sugar, fibre and fried-food patterns.</p></div>`;
  const word = ['On track', 'Watch', 'High'], tone = ['var(--leaf)', 'var(--turmeric)', 'var(--chili)'], fill = [28, 64, 100];
  return `<div class="tray impact">${rows.map(r => `<div class="cell ${r.level === null ? 'nodata' : ''}" style="--fill:${r.level === null ? 0 : fill[r.level]}%;--tone:${r.level === null ? 'var(--line-strong)' : tone[r.level]}">
      <span class="cell-label">${r.label}</span><b>${r.level === null ? 'No data' : word[r.level]}</b><span class="cell-goal">this week</span></div>`).join('')}</div>
    <ul class="reasons">${rows.map(r => `<li><b>${r.label}.</b> ${esc(r.text)}</li>`).join('')}</ul>
    <p class="sub small">Patterns from the meals you logged this week — general guidance, not medical advice. Log every meal for a fairer picture.</p>`;
}

const MEAL_LABEL = { breakfast: 'Breakfast', lunch: 'Lunch', dinner: 'Dinner', snack: 'Snack' };

// A removed meal waits here during the Undo window; it is deleted on the server when the window closes,
// another meal is removed, or the page is closed (keepalive lets that last request finish).
let pendingRemoval = null;
function flushRemoval(keepalive = false) {
  const m = pendingRemoval;
  pendingRemoval = null;
  if (m && m.synced && !m.sample && canSync()) {
    deleteMeal(m.remoteId || m.id, keepalive).then(() => refreshServerNumbers()).catch(() => {});
  }
}
window.addEventListener('pagehide', () => flushRemoval(true));

// ---------- Pages ----------
function dashboard() {
  const today = todayMeals(), tg = targets(), streak = streakDays();
  const name = state.profile.name ? ', ' + esc(state.profile.name) : '';
  const sample = state.sample ? `<div class="banner">${icon('info')}<div>These are sample meals so the dashboard is not empty. <button class="btn small secondary" data-act="clearMeals">Clear sample data and start fresh</button></div></div>` : '';
  return `${sample}<header class="page-head"><div><h2>Today${name}</h2><p class="sub">${new Date().toLocaleDateString('en', { weekday: 'long', day: 'numeric', month: 'long' })}</p></div>
    <button class="btn accent" data-page="scan">${icon('camera')}Scan a meal</button></header>
  ${needsSetup() ? setupHtml() : ''}
  <section class="tray" role="group" aria-label="Today's nutrition against your goals">
    ${cell('Calories', sum(today, 'cal'), tg.cal, ' kcal', 'var(--m-cal)')}
    ${cell('Protein', sum(today, 'protein'), tg.protein, 'g', 'var(--m-protein)')}
    ${cell('Carbs', sum(today, 'carbs'), tg.carbs, 'g', 'var(--m-carbs)')}
    ${cell('Fat', sum(today, 'fat'), tg.fat, 'g', 'var(--m-fat)')}
  </section>
  ${defaultGoals() ? `<p class="tray-note">Goals are a general ${tg.cal.toLocaleString('en-IN')} kcal default for now. <a href="#profile" data-page="profile">Add your age, height and weight</a> to get your own.</p>` : ''}
  <div class="dash-grid">
    <section class="card today-read"><h3>Today so far</h3>
      ${signedIn() ? `<div id="ai-insight">${skeleton(3)}</div>` : ''}
      ${today.length || !signedIn() ? `${signedIn() ? '<h4>From your log</h4>' : ''}
      <ul class="checks">${insights(today).map(i => `<li class="${i.tone}">${icon({ warn: 'alert', good: 'check' }[i.tone] || 'info')}<span>${esc(i.text)}</span></li>`).join('')}</ul>` : ''}</section>
    ${todayMealsHtml(today)}
    <section class="card chart-card"><h3>Last 7 days</h3>${weekChart()}
      <p class="legend"><span class="key leaf"></span>Calories <span class="key chili"></span>Street food <span class="key goal"></span>Your goal</p></section>
    <section class="card streak-card"><h3>Street-free streak</h3><p class="big num">${streak} <span>${streak === 1 ? 'day' : 'days'}</span></p>
      ${dots(streak)}
      <p class="sub">${claimable() ? 'Your weekly reward is ready to claim.' : streak >= 7 ? 'Weekly reward claimed. Keep going for the next one.' : streak === 0 ? `A new run starts today. ${bestStreak() ? `Best so far: ${bestStreak()} days.` : 'Seven street-free days earn the weekly reward.'}` : (7 - streak) + ' more days to your weekly reward.'}</p>
      <button class="btn secondary" data-page="rewards">See rewards</button></section>
    <section class="card wide"><h3>This week's eating patterns</h3>${impactHtml()}</section>
  </div>`;
}

// What was eaten today, newest last, each one tap from being logged again. On an empty day it offers the
// last few different meals instead ("same as yesterday's mess lunch").
function todayMealsHtml(today) {
  const row = m => `<li><div><b>${esc(m.name)}</b><small class="num">${MEAL_LABEL[m.mealType || mealTypeAt(m.at)] || 'Meal'} · ${Math.round(m.cal)} kcal</small></div>
      <button class="btn small secondary" data-act="relog" data-id="${esc(m.id)}" aria-label="Log ${esc(m.name)} again">Log again</button></li>`;
  const seen = new Set();
  const recent = [...state.meals].filter(m => !m.sample).sort((a, b) => b.at - a.at)
    .filter(m => !seen.has(m.name.toLowerCase()) && seen.add(m.name.toLowerCase())).slice(0, 3);
  const body = today.length
    ? `<ul class="mini-meals">${[...today].sort((a, b) => a.at - b.at).slice(-5).map(row).join('')}</ul>`
    : recent.length
      ? `<p class="sub small">Nothing logged yet today. Had one of these again?</p><ul class="mini-meals">${recent.map(row).join('')}</ul>`
      : `<p class="sub">No meals yet today.</p><button class="btn small secondary" data-page="history">${icon('plus')}Log a meal by hand</button>`;
  return `<section class="card meals-card"><h3>Today's meals</h3>${body}
    ${today.length || recent.length ? '<button class="btn ghost small see-all" data-page="history">See all in History</button>' : ''}</section>`;
}

// ---------- First run ----------
// Three choices change what every scan, tip and meal idea suggests, so a new account is asked for them once,
// on the dashboard, pre-filled with the defaults already in use. Body numbers (for calorie goals) stay in the
// Health profile; until they are there, the tray says its goals are a default.
const SETUP_CHOICES = {
  diet: ['Diet', { Vegetarian: 'Vegetarian', Eggetarian: 'Eggetarian', 'Non-vegetarian': 'Non-veg', Vegan: 'Vegan' }],
  kitchen: ['Kitchen in your room', { none: 'No cooking', kettle: 'Kettle only', burner: 'Burner' }],
  goalDir: ['Weight goal', { lose: 'Lose', maintain: 'Maintain', gain: 'Gain' }],
};
const needsSetup = () => !state.setupDone && !state.profileTouched;
const defaultGoals = () => (serverBasis ? serverBasis === 'default' : !state.profileTouched);

function setupHtml() {
  const p = state.profile;
  const group = ([key, [label, opts]]) => `<fieldset class="setup-q"><legend>${label}</legend><div class="segmented seg-${Object.keys(opts).length}">${Object.entries(opts)
    .map(([v, t]) => `<label><input type="radio" name="setup-${key}" value="${esc(v)}" ${v === p[key] ? 'checked' : ''}><span>${t}</span></label>`).join('')}</div></fieldset>`;
  return `<section class="card setup" aria-labelledby="setup-title"><h3 id="setup-title">How do you eat?</h3>
    <p class="sub">Scans, tips and meal ideas follow these. Change them any time in Health profile.</p>
    <div class="setup-grid">${Object.entries(SETUP_CHOICES).map(group).join('')}</div>
    <div class="actions"><button class="btn" data-act="saveSetup">Save choices</button><button class="btn ghost" data-act="skipSetup">Skip for now</button></div></section>`;
}

// Grey placeholder lines while text loads, so the card keeps its shape.
const skeleton = lines => `<div class="skeleton" role="status" aria-label="Loading">${[...Array(lines)].map(() => '<span></span>').join('')}</div>`;

function fitLine(f) {
  const tg = targets(), left = Math.round(tg.cal - sum(todayMeals(), 'cal'));
  const pct = Math.round(f.cal / tg.cal * 100);
  if (!f.cal) return '';
  return `About ${pct}% of your daily calories. ` + (f.cal > left
    ? `That is more than the ${Math.max(0, left)} kcal you have left today.`
    : `That leaves ${left - f.cal} kcal for the rest of the day.`);
}

function healthHtml(f) {
  const h = f.health;
  if (!h) return '';
  const tone = { green: 'var(--leaf)', amber: 'var(--turmeric)', red: 'var(--chili)' }[h.color] || 'var(--leaf)';
  const label = { good: 'Good', moderate: 'Moderate', needs_attention: 'Needs attention' }[h.label] || h.label;
  return `<div class="score" style="--tone:${tone}" role="img" aria-label="Health score ${h.score} out of 100, ${esc(label)}"><b class="num">${h.score}</b><span>/100</span><small>${esc(label)}</small></div>`;
}

function itemsHtml(f, subtitle = '') {
  if (!f.items || !f.items.length) return '';
  const conf = { high: '', medium: ' <small class="pill warn">medium confidence</small>', low: ' <small class="pill bad">low confidence</small>' };
  const src = s => s === 'table' ? ' <small class="pill ok" title="Nutrients from a curated food database (IFCT/USDA)">DB</small>' : ' <small class="pill" title="Nutrients estimated by the AI">AI est.</small>';
  return `<h4>What is on the plate</h4>${subtitle}<ul class="items">${f.items.map(i => `<li><span><span class="item-name">${esc(i.name)}</span>${conf[i.confidence] || ''}${src(i.nutritionSource)}<small>${esc(i.serving || i.grams + ' g')}</small></span><b class="num">${i.cal} kcal</b></li>`).join('')}</ul>`;
}

function resultHtml() {
  const f = scan.result;
  if (f.error) return `<div class="banner warn" role="alert">${icon('alert')}<div>${esc(f.error)}</div></div>`;
  // The four macros carry the dashboard tray's colours, so the same nutrient looks the same everywhere.
  const n = (label, v, unit, tone) => `<div ${tone ? `style="--tone:${tone}"` : ''}><small>${label}</small><b class="num">${dash(v)}${has(v) ? `<span class="unit">${unit}</span>` : ''}</b></div>`;
  const risk = { low: 'Low risk', medium: 'Medium risk', high: 'High risk' };
  // The two-stage pipeline, said where the items are: the image model's guess, then Gemini reads every item.
  const top = f.classifier?.predictions?.[0];
  const pipeline = top
    ? `<p class="pipeline">${icon('image')}<span>Image model's first guess: <b>${esc(top.display_name)}</b> (${Math.round(top.score * 100)}%). Gemini then read every item on the plate.</span></p>` : '';
  const list = (items, kind, none) => `<ul class="${kind}">${items.map(t => `<li>${icon(kind === 'tips' ? 'check' : 'alert')}<span>${esc(t)}</span></li>`).join('') || `<li class="none">${none}</li>`}</ul>`;
  const lists = f.health
    ? `<div class="lists"><div><h4>Watch out</h4>${list(f.cons, 'flags', 'Nothing flagged for this meal')}</div>
       <div><h4>Tips</h4>${list(f.tips, 'tips', 'No tips this time')}</div></div>
       <p class="sub small">${esc(f.health.disclaimer || 'Estimates only — not medical advice.')}</p>`
    : `<div class="lists"><div><h4>Advantages</h4>${list(f.pros, 'tips', 'None found')}</div>
       <div><h4>Disadvantages</h4>${list(f.cons, 'flags', 'None found')}</div></div>`;
  const photo = scan.url || f.imageUrl;
  // Verdict (this plate, its score, how it fits the day) → decision (log it / find a swap) → what is on the
  // plate → the numbers and advice. Rarely needed detail (fibre, sodium, sugar) is folded away.
  return `<article class="card result"><div class="result-head">
      ${photo ? `<img class="result-thumb" src="${esc(photo)}" alt="">` : ''}
      <div class="result-title"><h3 tabindex="-1">${esc(f.name)}</h3><span class="tag bad" ${f.street ? '' : 'hidden'}>Street food</span></div>
      ${healthHtml(f)}</div>
    <p class="fit">${fitLine(f)}</p>
    ${f.health ? `<details class="how score-how"><summary>How is the health score worked out?</summary>
      <p>The app starts at 100 and takes points off when salt, sugar, saturated fat or calories go over this meal's share of your day, or when protein or fibre fall short. It is worked out from this plate's nutrients; the AI doesn't pick the score.</p></details>` : ''}
    <div class="result-act" id="result-act">${resultActHtml()}</div>
    <section class="plate">${f.items ? itemsHtml(f, pipeline) : `<p class="sub">${esc(f.summary)}</p>${pipeline}`}
      <label class="check street-check"><input type="checkbox" data-act="toggleStreet" ${f.street ? 'checked' : ''}> Bought from a stall or cart? This is street food</label></section>
    <div class="nutri macros4">${n('Calories', f.cal, ' kcal', 'var(--m-cal)')}${n('Protein', f.protein, 'g', 'var(--m-protein)')}${n('Carbs', f.carbs, 'g', 'var(--m-carbs)')}${n('Fat', f.fat, 'g', 'var(--m-fat)')}</div>
    <details class="how more-nutri"><summary>Fibre, sodium and sugar</summary>
      <div class="nutri extras">${n('Fibre', f.fibre, 'g')}${n('Sodium', f.sodium, 'mg')}${n('Sugar', f.sugar, 'g')}</div></details>
    ${f.ingredients.length ? `<div class="chips" aria-label="Ingredients by risk">${f.ingredients.map(i => `<span class="chip ${i.risk}">${esc(i.name)}<small> ${risk[i.risk]}</small></span>`).join('')}</div>` : ''}
    ${lists}</article>
    <section class="card chat-card"><h3>Ask about this food</h3><div class="chat"><div class="msgs" id="msgs" aria-live="polite">${chatHtml()}</div>
    <div class="chips">${['How can I make this healthier?', 'Is this enough protein for me?', 'What can I eat instead?'].map(q => `<button class="chip btn-chip" data-act="ask" data-q="${esc(q)}">${esc(q)}</button>`).join('')}</div>
    <div class="ask"><input id="q" placeholder="Can I eat this every day?" aria-label="Question about this food"><button class="btn" data-act="send" aria-label="Ask">${icon('send')}<span class="ask-lbl">Ask</span></button></div></div></section>`;
}

// The decision row. Once the plate is logged it becomes a small day bar: what you had before (soft) and what
// this plate added (saffron, filling in), so logging lands somewhere you can see.
function resultActHtml(from) {
  if (!scan.added) {
    return `<div class="actions"><button class="btn accent" data-act="addMeal">${icon('plus')}Add to my log</button>
      <button class="btn secondary" data-act="swapFor">${icon('swap')}Find a home swap</button></div>`;
  }
  const goal = targets().cal, now = Math.round(sum(todayMeals(), 'cal'));
  const before = from ?? now - Math.round(scan.result.cal || 0);
  const pct = v => Math.max(0, Math.min(100, v / goal * 100));
  const left = goal - now;
  return `<div class="day-fill" role="status">
      <p><b class="num">${icon('check')}Added. Today: ${now} / ${goal} kcal</b><span class="sub">${left >= 0 ? `${left} kcal left for the day` : `${-left} kcal over today's goal`}</span></p>
      <div class="day-bar" aria-hidden="true"><i class="was" style="width:${pct(before)}%"></i><i class="now" style="left:${pct(before)}%;--to:${pct(now) - pct(before)}%"></i></div></div>
    <div class="actions"><button class="btn secondary" data-act="swapFor">${icon('swap')}Find a home swap</button><button class="btn ghost" data-page="dashboard">See today</button></div>`;
}

function chatHtml(list = scan.chat) {
  if (!list.length) return '<p class="sub chat-empty">Ask about portions, protein or cheaper, healthier options. The AI knows your profile and what you’ve eaten today.</p>';
  return list.map(m => `<div class="msg ${m.me ? 'me' : ''} ${m.markdown ? 'md' : ''} ${m.error ? 'err' : ''} ${m.pending ? 'pending' : ''}" ${m.error ? 'role="alert"' : ''}>${m.pending ? '<span class="spinner" aria-hidden="true"></span>' : ''}${m.markdown ? md(m.text) : esc(m.text)}${(m.tools || []).map(t => `<small class="tool">${icon('check')}${esc(t.summary)}</small>`).join('')}</div>`).join('');
}

// What the result column shows before the first scan.
const resultSlot = () => scan.busy ? loadingHtml('scan', scan.since) : scan.result ? resultHtml()
  : `<div class="result-empty">${icon('image')}<p>Your results show up here: calories and nutrients for every item on the plate, a health score and tips.</p></div>`;

// ---------- Ask (general chat, no scan needed) ----------
const askThread = { chat: [], busy: false };
const ASK_STARTERS = ['A cheap high-protein breakfast I can make', 'How am I doing today?', 'Light dinner ideas with just a kettle'];

function askPage() {
  return `<header class="page-head"><div><h2>Ask NutriBuddy</h2><p class="sub">Food questions, answered with your profile, goals and today's meals in mind. It can also log a meal for you.</p></div></header>
  <section class="card chat-card ask-card"><div class="chat"><div class="msgs" id="msgs" aria-live="polite">${chatHtml(askThread.chat)}</div>
    <div class="chips">${ASK_STARTERS.map(q => `<button class="chip btn-chip" data-act="ask" data-q="${esc(q)}">${esc(q)}</button>`).join('')}</div>
    <div class="ask"><input id="q" placeholder="Is Maggi okay twice a week?" aria-label="Your question"><button class="btn" data-act="send" aria-label="Ask">${icon('send')}<span class="ask-lbl">Ask</span></button></div></div>
    <p class="sub small">Estimates only — not medical advice.</p></section>`;
}

// The scan button follows the task: disabled until there is a photo, the turmeric action while there is one to
// analyze, and a quiet "Scan another photo" once a result is showing (then "Add to my log" is the action).
function analyzeBtnHtml() {
  if (scan.busy) return `<button class="btn accent wide" data-act="analyze" id="analyze" disabled aria-busy="true"><span class="spinner" aria-hidden="true"></span>Analyzing…</button>`;
  if (scan.result && !scan.result.error) return `<button class="btn secondary wide" data-act="scanAnother" id="analyze">${icon('camera')}Scan another photo</button>`;
  const label = scan.result?.error ? 'Try again' : 'Analyze'; // after a failed scan, the same photo can be retried
  return `<button class="btn accent wide" data-act="analyze" id="analyze" ${scan.file ? '' : 'disabled aria-describedby="analyze-hint"'}>${label}</button>
    ${scan.file ? '' : '<small id="analyze-hint" class="analyze-hint">Choose a photo to start.</small>'}`;
}

function refreshAnalyze() {
  const slot = $('#analyze-slot');
  if (slot) slot.innerHTML = analyzeBtnHtml();
}

function scanPage() {
  return `<header class="page-head"><div><h2>Scan food</h2><p class="sub">Photograph a whole meal or the nutrition label on a packet.</p></div></header>
  <div class="scan-layout">
  <section class="card scan-input">
    <label class="drop ${scan.url ? 'has-img' : ''}"><input type="file" id="file" class="sr" accept="image/*">
      <img id="preview" class="preview" alt="Selected food" ${scan.url ? `src="${scan.url}"` : 'hidden'}>
      <span class="drop-cta">${icon('camera')}<b class="drop-title">Choose a photo, take one, or drop it here</b><b class="drop-change">Choose another photo</b></span>
      <small id="fname">${scan.file ? esc(scan.file.name) : 'JPG, PNG or WebP'}</small></label>
    <div class="scan-options">
      <fieldset class="segmented"><legend class="sr">What are you scanning?</legend>
        <label><input type="radio" name="mode" value="meal" ${scan.mode === 'meal' ? 'checked' : ''}><span>Whole meal</span></label>
        <label><input type="radio" name="mode" value="label" ${scan.mode === 'label' ? 'checked' : ''}><span>Product label</span></label></fieldset>
      <label class="field">Which meal is this?
        <select id="meal-type">
          <option value="auto">Not sure / general</option>
          <option value="breakfast">Breakfast</option>
          <option value="lunch">Lunch</option>
          <option value="dinner">Dinner</option>
          <option value="snack">Snack</option>
        </select>
        <small>The score compares the plate with that meal's share of your day (lunch gets the most, a snack the least). Not sure? It's compared with a third of your day.</small>
      </label>
    </div>
    <div class="analyze-slot" id="analyze-slot">${analyzeBtnHtml()}</div>
  </section>
  <p id="scan-said" class="sr-only" role="status"></p><div id="result" class="scan-output">${resultSlot()}</div>
  </div>`;
}

function historyPage() {
  const all = [...state.meals].sort((a, b) => b.at - a.at);
  const list = all.filter(m => ui.histFilter === 'all' || (ui.histFilter === 'street' ? m.street : m.home));
  const groups = [];
  list.forEach(m => {
    const day = new Date(m.at).toDateString();
    if (!groups.length || groups[groups.length - 1].day !== day) groups.push({ day, at: m.at, meals: [] });
    groups[groups.length - 1].meals.push(m);
  });
  const row = m => `<li class="row"><div><div class="row-title"><b>${esc(m.name)}</b>${m.street ? '<span class="tag bad">Street</span>' : ''}${m.home ? '<span class="tag">Home cooked</span>' : ''}</div>
      <small class="num">${MEAL_LABEL[m.mealType || mealTypeAt(m.at)] || 'Meal'} · ${new Date(m.at).toLocaleTimeString('en', { hour: 'numeric', minute: '2-digit' })} · ${Math.round(m.cal)} kcal · protein ${m.protein}g · carbs ${m.carbs}g · fat ${m.fat}g</small></div>
      <button class="btn ghost danger small" data-act="remove" data-id="${esc(m.id)}" aria-label="Remove ${esc(m.name)}">${icon('trash')}<span>Remove</span></button></li>`;
  const body = groups.map(g => `<section class="day-group"><h3 class="day">${dateLabel(g.at)} <small class="num">${Math.round(sum(all.filter(x => sameDay(x.at, g.at)), 'cal'))} kcal</small></h3>
    <ul class="card list">${g.meals.map(row).join('')}</ul></section>`).join('');
  const f = (key, label) => `<button class="seg-btn" data-act="filter" data-v="${key}" aria-pressed="${ui.histFilter === key}">${label}</button>`;
  const week = weekMeals(), street = week.filter(m => m.street).length;
  return `<header class="page-head"><div><h2>History</h2><p class="sub">${week.length} meals in the last 7 days, ${street} of them street food.</p></div>
    <button class="btn secondary" data-act="exportCsv">${icon('download')}Export CSV</button></header>
  <div class="segmented filters" role="group" aria-label="Show meals">${f('all', 'All')}${f('street', 'Street food')}${f('home', 'Home cooked')}</div>
  <details class="card add-meal"><summary>${icon('plus')}Log a meal by hand</summary>
    <div class="form-row"><label class="field">Meal name<input id="m-name" maxlength="120" placeholder="Egg roll"></label>
    <label class="field">Calories<input id="m-cal" type="number" inputmode="numeric" min="0" max="3000" placeholder="350"></label></div>
    <fieldset class="form-row macros"><legend class="field-label">Protein, carbs and fat <small>(optional, in grams)</small></legend>
    <label class="field">Protein<input id="m-protein" type="number" inputmode="decimal" min="0" max="300" placeholder="12"></label>
    <label class="field">Carbs<input id="m-carbs" type="number" inputmode="decimal" min="0" max="500" placeholder="40"></label>
    <label class="field">Fat<input id="m-fat" type="number" inputmode="decimal" min="0" max="300" placeholder="15"></label>
    <small class="macros-hint">Left blank, this meal adds nothing to today's protein, carbs and fat.</small></fieldset>
    <label class="check"><input type="checkbox" id="m-street"> Street food</label>
    <div class="actions"><button class="btn" data-act="addManual">Add meal</button></div></details>
  ${body || `<div class="empty-state">${icon('history')}<h3>No meals here yet</h3><p>Scan one, or log one by hand.</p><button class="btn accent" data-page="scan">${icon('camera')}Scan a meal</button></div>`}`;
}

function gearLabel(r) { return { none: 'No cooking', kettle: 'Kettle only', burner: 'Burner needed' }[r.gear] || ''; }

function recipeCard(r, first) {
  const all = r.ingredientsList || r.pantry || [];
  const ing = all.filter(x => !all.some(y => y !== x && y.includes(x)));
  return `<article class="card recipe ${first ? 'match' : ''}">
    <div class="recipe-head"><h3>${esc(r.meal)}</h3>${first ? '<span class="tag warm">Matches your street meal</span>' : ''}</div>
    <p class="recipe-from">${r.ai ? 'AI suggestion' : r.from ? 'Instead of ' + esc(r.from) : 'Home-cooked idea'}</p>
    <p>${esc(r.why)}</p>
    <ul class="meta num"><li>${icon('clock')}${r.time} min</li><li>${r.cal} kcal</li><li>protein ${r.protein}g</li>${r.gear ? `<li>${gearLabel(r)}</li>` : ''}</ul>
    ${(ing.length || (r.steps || []).length) ? `<details class="how"><summary>Ingredients and steps</summary>
      ${ing.length ? `<p><b>Main ingredients:</b> ${ing.map(esc).join(', ')}</p>` : ''}
      ${(r.steps || []).length ? `<ol>${r.steps.map(s => `<li>${esc(s)}</li>`).join('')}</ol>` : ''}</details>` : ''}
    <button class="btn secondary" data-act="cooked" data-rid="${esc(r.id)}">${icon('check')}I cooked this</button>
  </article>`;
}

function suggestionsHtml() {
  if (cook.busy) return loadingHtml('ideas', cook.since);
  if (!cook.results) return '';
  const { source, meals, reason } = cook.results;
  if (source === 'error') return `<div class="banner warn" role="alert">${icon('alert')}<div>Couldn't get meal ideas from the AI. ${esc(reason || '')}</div></div>`;
  if (!meals.length) return `<div class="empty-inline">${icon('info')}<p>The AI found no meal for those ingredients with your kitchen and diet. Add a few more items.</p></div>`;
  return `<p class="sub">Suggested by the AI (Gemini) for what you have, your diet and your kitchen.</p><div class="recipe-grid">${meals.map(r => recipeCard(r, false)).join('')}</div>`;
}

function cookPage() {
  const p = state.profile, usable = usableRecipes(p);
  const last = state.meals.filter(m => m.street).sort((a, b) => b.at - a.at)[0];
  const focus = String(cook.focus || (last && last.name) || '').toLowerCase();
  const hit = r => !!focus && r.keys.some(k => focus.includes(k));
  const ordered = [...usable].sort((a, b) => hit(b) - hit(a));
  const rows = ordered.map((r, i) => recipeCard(r, i === 0 && hit(r))).join('');
  const why = cook.focus ? `You asked for a swap for ${esc(cook.focus)}.` : last ? `Your last street meal was ${esc(last.name)}, so matching swaps come first.` : 'Home-cooked swaps for common street food.';
  return `<header class="page-head"><div><h2>Cook instead</h2><p class="sub">Showing meals for a ${esc(p.diet)} diet. Kitchen: ${esc((KITCHENS[p.kitchen] || KITCHENS.burner).toLowerCase())}. Change these in <a href="#profile" data-page="profile">Health profile</a>.</p></div></header>
  <section class="card pantry-card"><h3>What is in your room?</h3>
    <label for="pantry" class="field-label">Ingredients you have, separated by commas</label>
    <div class="pantry-row"><input id="pantry" value="${esc(cook.pantry)}" placeholder="poha, onion, peanuts">
      <button class="btn" data-act="suggest" id="suggest" ${cook.busy ? 'disabled aria-busy="true"' : ''}>${cook.busy ? '<span class="spinner" aria-hidden="true"></span>Finding meals…' : 'Suggest meals'}</button></div>
    <div class="chips" aria-label="Add a common ingredient">${PANTRY_CHIPS.map(c => `<button class="chip btn-chip" data-act="pantryAdd" data-v="${c}">${icon('plus')}${c}</button>`).join('')}</div>
    <div id="suggestions" aria-live="polite">${suggestionsHtml()}</div></section>
  <section class="section"><h3 class="section-title">Swaps for street food</h3><p class="sub">${why}</p>
    ${rows ? `<div class="recipe-grid">${rows}</div>` : `<div class="empty-inline">${icon('info')}<p>No swaps fit this diet and kitchen. Change them in Health profile.</p></div>`}</section>`;
}

function rewardsPage() {
  const streak = streakDays(), best = bestStreak(), pts = points(), lv = level(pts), ctx = badgeCtx();
  const next = BADGES.filter(b => b.id[0] === 's').find(b => b.goal > streak);
  const can = claimable();
  const badgeRow = b => {
    const got = state.badges[b.id];
    const prog = Math.min(b.of(ctx), b.goal);
    return `<li class="badge ${got ? '' : 'locked'}"><span class="badge-icon">${icon(b.icon)}</span>
      <div><b>${b.name}</b><small>${got ? 'Unlocked ' + dateLabel(got) : b.desc}</small>
      ${got ? '' : `<div class="progress thin" role="progressbar" aria-label="${b.name} progress" aria-valuemin="0" aria-valuemax="${b.goal}" aria-valuenow="${prog}"><i style="width:${prog / b.goal * 100}%"></i></div><small class="num">${prog} of ${b.goal}</small>`}</div></li>`;
  };
  // Earned badges, then only the next one or two to aim for; the rest wait behind "More badges".
  const earned = BADGES.filter(b => state.badges[b.id]);
  const locked = BADGES.filter(b => !state.badges[b.id]);
  const upNext = [locked.find(b => b.id[0] !== 's'), locked.find(b => b.id[0] === 's')].filter(Boolean);
  const later = locked.filter(b => !upNext.includes(b));
  const badgeRows = [...earned, ...upNext].map(badgeRow).join('');
  const moreBadges = later.length ? `<details class="how more-badges"><summary>More badges (${later.length})</summary><ul class="badge-grid">${later.map(badgeRow).join('')}</ul></details>` : '';
  return `<header class="page-head"><div><h2>Rewards</h2><p class="sub">Go a full week without street food to unlock the weekly reward.</p></div></header>
  <div class="rewards-top">
  <section class="card streak-card"><h3>Street-free streak</h3><p class="big num">${streak} <span>day${streak === 1 ? '' : 's'}</span></p>
    ${dots(streak)}
    <p class="sub">${streak === 0 ? 'A new run starts today. ' : ''}${next ? (next.goal - streak) + ' more days for “' + next.name.replace(/-/g, '\u2011') + '”. ' : 'Every streak badge unlocked. '}${best ? `Best run so far: ${best} day${best === 1 ? '' : 's'}.` : ''}</p></section>
  <section class="card reward ${can ? 'ready' : ''}"><h3>Weekly reward</h3>
    <p>${can ? 'You made it through a full street-free week. Claim 50 bonus points.' : streak >= 7 ? 'Claimed for this week. The next one unlocks after 7 more street-free days.' : 'Unlocks after 7 days in a row without street food.'}</p>
    ${can ? '<button class="btn accent" data-act="claim">Claim 50 points</button>'
    : `<div class="progress thin" role="progressbar" aria-label="Weekly reward progress" aria-valuemin="0" aria-valuemax="7" aria-valuenow="${streak % 7}"><i style="width:${streak % 7 / 7 * 100}%"></i></div><small class="num">${streak % 7} of 7 street-free days</small>`}</section>
  <section class="card level-card"><h3>Level ${lv.n}: ${lv.name}</h3><div class="progress" role="progressbar" aria-label="Level progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${lv.into}"><i style="width:${lv.into}%"></i></div>
    <p class="sub">${pts} points. ${100 - lv.into} more for the next level. You earn 10 for every street-free day, 5 for every home-cooked meal and 50 for each weekly reward.</p></section>
  </div>
  <section class="section"><h3 class="section-title">Badges</h3><ul class="badge-grid">${badgeRows}</ul>${moreBadges}</section>`;
}

function profilePage() {
  const p = state.profile;
  const bmi = p.weight / ((p.height / 100) ** 2);
  const cat = bmi < 18.5 ? 'below the usual range' : bmi < 25 ? 'in the usual range' : bmi < 30 ? 'above the usual range' : 'well above the usual range';
  const field = (id, label, type = 'number', extra = '') => `<label class="field">${label}<input id="p-${id}" type="${type}" value="${esc(p[id])}" ${extra}></label>`;
  const opts = (id, map) => Object.entries(map).map(([v, t]) => `<option value="${v}" ${v === p[id] ? 'selected' : ''}>${t}</option>`).join('');
  const who = isGuestUser()
    ? `<p>You are using a <b>guest session</b>. The AI works the same, but the session ends when you close this tab. Create an account to keep your meals.</p><div class="actions"><button class="btn" data-act="signOut">Sign in or create an account</button><button class="btn secondary" data-act="syncNow">Sync now</button></div>`
    : `<p>Signed in as <b>${esc(authLabel())}</b>. Meals and profile sync to your account.</p><div class="actions"><button class="btn secondary" data-act="syncNow">Sync now</button><button class="btn secondary" data-act="signOut">Sign out</button></div>`;
  return `<header class="page-head"><div><h2>Health profile</h2><p class="sub">Your goals shape the dashboard and the advice you get. BMI ${bmi.toFixed(1)} is ${cat}. It is only a rough guide.</p></div></header>
  <section class="card"><h3>About you</h3>
  <div class="form-grid">
  ${field('name', 'Name', 'text', 'maxlength="40"')}${field('age', 'Age', 'number', 'min="13" max="100"')}
  <label class="field">Sex<select id="p-sex">${opts('sex', { female: 'Female', male: 'Male', other: 'Prefer not to say' })}</select></label>
  ${field('weight', 'Weight (kg)', 'number', 'min="25" max="250"')}${field('height', 'Height (cm)', 'number', 'min="100" max="230"')}
  <label class="field">Activity<select id="p-activity">${opts('activity', { sitting: 'Mostly sitting', light: 'Light, some walking', active: 'Active, regular exercise' })}</select></label></div>
  <h3 class="form-section">Goals and kitchen</h3>
  <div class="form-grid">
  <label class="field">Diet<select id="p-diet">${Object.keys(DIET_RANK).map(d => `<option ${d === p.diet ? 'selected' : ''}>${d}</option>`).join('')}</select></label>
  <label class="field">Weight goal<select id="p-goalDir">${opts('goalDir', { lose: 'Lose weight', maintain: 'Maintain weight', gain: 'Gain weight or muscle' })}</select></label>
  <label class="field">Kitchen in your room<select id="p-kitchen">${opts('kitchen', KITCHENS)}</select></label>
  <label class="field">Daily calorie goal<input id="p-goal" type="number" min="1200" max="4000" step="50" value="${esc(p.goal)}"></label>
  <label class="field wide-field">Allergies<input id="p-allergies" type="text" maxlength="400" value="${esc((p.allergies || []).join(', '))}" placeholder="e.g. peanuts, lactose" aria-describedby="allergy-hint">
    <small id="allergy-hint">Separate with commas. Scans, tips, meal ideas and the chat leave these out.</small></label></div>
  <div class="actions"><button class="btn" data-act="saveProfile">Save profile</button><button class="btn secondary" data-act="suggestGoal">Suggest a calorie goal</button></div></section>
  <div class="two-up">
  <section class="card"><h3>Account</h3>${who}</section>
  <section class="card"><h3>Your data</h3><p class="sub">Remove every logged meal and restart your streak. Badges you earned stay.</p><div class="actions"><button class="btn ghost danger" data-act="clearMeals">${icon('trash')}Clear all logged meals</button></div></section>
  </div>`;
}

const pages = { dashboard, scan: scanPage, ask: askPage, history: historyPage, cook: cookPage, rewards: rewardsPage, profile: profilePage };

function show(name, opts = {}) {
  if (!pages[name]) name = 'dashboard';
  document.querySelectorAll('.side [data-page]').forEach(b => {
    b.classList.toggle('on', b.dataset.page === name);
    if (b.dataset.page === name) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  try { $('#main').innerHTML = pages[name](); }
  catch (err) { console.error(err); $('#main').innerHTML = '<h2>Something went wrong</h2><p class="sub">This page could not be shown. Reload it, or open another page from the menu.</p>'; }
  if (location.hash !== '#' + name) {
    try { window.history[opts.push ? 'pushState' : 'replaceState'](null, '', '#' + name); } catch { /* some browsers block this on file:// pages */ }
  }
  window.scrollTo(0, 0);
  if (opts.focus) { const h = $('#main h2'); if (h) { h.tabIndex = -1; h.focus({ preventScroll: true }); } }
  if (name === 'rewards') checkBadges();
  if (name === 'dashboard' && signedIn()) loadInsight();
}
const currentPage = () => location.hash.replace('#', '');

function refreshStatus() {
  const chip = $('#status'), who = $('#who');
  if (who) who.textContent = authLabel();
  if (!chip) return;
  const map = { idle: ['Connecting to the server…', ''], ok: ['Connected to NutriScan AI', 'ok'], ai: ['Connected · AI unavailable: ' + net.detail, 'bad'], offline: ['Server not reachable: is uvicorn running?', 'bad'], http: ['Server error: ' + net.detail, 'bad'] };
  const [text, cls] = map[net.state];
  chip.innerHTML = `<span class="status-text">${esc(text)}</span>`; chip.title = text; chip.className = 'status ' + cls;
}

// ---------- Meals: create, log, sync ----------
const newMeal = (f, extra = {}) => ({ id: uid(), at: Date.now(), name: f.name, cal: f.cal, protein: f.protein, carbs: f.carbs, fat: f.fat, fibre: f.fibre ?? null, sodium: f.sodium ?? null, sugar: f.sugar ?? null, satFat: f.satFat ?? null, street: !!f.street, home: false, synced: false, ...extra });
const canSync = () => !!CFG.endpoints.intake && signedIn();

function logMeal(m) {
  state.meals.push(m);
  save();
  checkBadges();
  if (canSync() && !recentlyOffline()) {
    pushMeal(m).then(id => { m.synced = true; if (id) m.remoteId = String(id); save(); refreshStatus(); refreshServerNumbers(); }).catch(e => { refreshStatus(); if (!e.offline) toast('Saved on this device. The server said: ' + reasonFor(e)); });
  }
}

// The server is the source of truth for signed-in accounts: unsynced local meals are pushed first, then the
// log is rebuilt from the server's intake entries (last 90 days), keeping local-only flags such as "home cooked".
async function syncNow(manual) {
  if (!canSync()) { if (manual) toast('Sign in to sync your meals'); return; }
  try {
    for (const m of state.meals.filter(x => !x.synced && !x.sample)) { const id = await pushMeal(m); m.synced = true; if (id) m.remoteId = String(id); }
    // Independent reads go out together: one round of latency instead of four in a row.
    const [fetched, saved] = await Promise.all([
      fetchRemoteMeals(),
      state.profileTouched ? null : fetchRemoteProfile().catch(() => null), // optional: meals still sync
      refreshServerNumbers(),
    ]);
    // A meal in its Undo window is still on the server; don't bring it back.
    const waiting = pendingRemoval && (pendingRemoval.remoteId || pendingRemoval.id);
    const remote = fetched.filter(r => r.id !== waiting);
    const local = new Map(state.meals.filter(m => m.synced && !m.sample).map(m => [m.remoteId || m.id, m]));
    const before = state.meals.filter(m => !m.sample).length;
    const fresh = remote.filter(r => !local.has(r.id)).length;
    state.meals = [
      ...remote.map(r => { const l = local.get(r.id); return l ? { ...r, id: l.id, home: l.home, street: l.street || r.street } : r; }),
      ...state.meals.filter(m => !m.synced && !m.sample),
    ];
    state.sample = false;

    // Bring the saved profile (and the calorie target the server computes) onto this device,
    // but never over changes made here.
    let profileChanged = false;
    if (saved?.diet) state.setupDone = true;
    if (saved && !state.profileTouched) {
      if (!state.profile.name && auth.user?.name) saved.name = auth.user.name.slice(0, 40);
      if (Object.keys(saved).some(k => JSON.stringify(state.profile[k]) !== JSON.stringify(saved[k]))) {
        state.profile = { ...state.profile, ...saved };
        profileChanged = true;
      }
    }

    checkBadges(true);
    save(); refreshStatus();
    if (manual) {
      const parts = [];
      if (fresh) parts.push(`${fresh} meal${fresh === 1 ? '' : 's'} came from your account`);
      if (profileChanged) parts.push('your profile was updated from your account');
      toast(parts.length ? `Synced. ${parts.join(' and ')}.` : 'Everything is in sync');
    }
    if (pages[currentPage()]) show(currentPage());  // reflect synced meals, targets and streak
  } catch (e) {
    refreshStatus();
    if (manual) toast('Sync failed. ' + reasonFor(e));
  }
}

// The dashboard renders twice on load (local data, then after the sync); both share one AI request.
let insightRequest = null;

async function loadInsight() {
  const box = $('#ai-insight');
  if (!box) return;
  try {
    const d = await (insightRequest ||= fetchInsight().finally(() => { insightRequest = null; }));
    const el = $('#ai-insight');
    if (!el) return;
    const tone = { on_track: 'good', over: 'warn', under: 'info', no_data: 'info' }[d.health_status] || 'info';
    el.innerHTML = `<p class="insight-head ${tone}">${esc(d.headline)}</p><p class="insight-body">${esc(d.summary)}</p>
      <ul class="tips">${d.tips.map(t => `<li>${icon('check')}<span>${esc(t)}</span></li>`).join('')}</ul><p class="sub small">${esc(d.disclaimer)}</p>`;
  } catch (e) {
    const el = $('#ai-insight');
    if (el) el.innerHTML = `<div class="empty-inline">${icon('info')}<p>The AI's read on your day isn't available right now. ${esc(reasonFor(e))}</p></div>`;
  }
  refreshStatus();
}

// ---------- Actions ----------
const csvCell = v => { let s = String(v ?? ''); if (/^[=+\-@]/.test(s)) s = "'" + s; return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };

function setFile(f) {
  if (!f) return;
  if (!f.type.startsWith('image/')) return toast('Choose an image file (JPG, PNG or WebP)');
  if (f.size > 20 * 1024 * 1024) return toast('That photo is over 20 MB. Choose a smaller one');
  if (scan.url) URL.revokeObjectURL(scan.url);
  scan = { ...scan, file: f, url: URL.createObjectURL(f), result: null, chat: [], added: false };
  const img = $('#preview'); if (img) { img.src = scan.url; img.hidden = false; }
  const d = $('.drop'); if (d) d.classList.add('has-img');
  const n = $('#fname'); if (n) n.textContent = f.name;
  const r = $('#result'); if (r) r.innerHTML = resultSlot();
  refreshAnalyze();
}

async function askAbout(text) {
  const general = currentPage() === 'ask', thread = general ? askThread : scan;
  const box = $('#q');
  if (!text || (!general && !scan.result) || thread.busy) return;
  if (box) box.value = '';
  thread.busy = true;
  thread.chat.push({ me: true, text });
  thread.chat.push({ text: 'Thinking…', pending: true });
  const paint = () => { const msgs = $('#msgs'); if (msgs) { msgs.innerHTML = chatHtml(thread.chat); msgs.scrollTop = msgs.scrollHeight; } };
  paint();
  const a = await askBot(text, general ? {} : scan.result);
  thread.busy = false;
  thread.chat = thread.chat.filter(m => !m.pending);
  thread.chat.push({ text: a.text, error: a.error, markdown: a.markdown, tools: a.tools });
  if ((a.tools || []).some(t => t.name === 'log_meal')) { if (!general) scan.added = true; syncNow(false); toast('Logged to your meals'); }
  refreshStatus();
  paint();
}

const actions = {
  async analyze() {
    if (!scan.file) return toast('Choose a photo first');
    if (scan.busy) return;
    scan.busy = true; scan.since = Date.now();
    refreshAnalyze();
    const loading = $('#result');
    loading.innerHTML = loadingHtml('scan', scan.since);
    loading.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    const mode = document.querySelector('[name=mode]:checked').value;
    try {
      scan.mode = mode;
      scan.chat = []; scan.added = false;
      try {
        scan.result = await analyzeImage(scan.file, mode, $('#meal-type') ? $('#meal-type').value : 'auto');
        state.stats[mode === 'label' ? 'labelScans' : 'mealScans']++;
        checkBadges(); // the first scan (and the first label) unlock a badge right here
      } catch (e) {
        scan.result = { error: e.code === 'NOT_FOOD'
          ? "We couldn't spot any food in that photo. Try a clearer, closer photo of the plate or packet."
          : 'The scan did not finish. ' + reasonFor(e) };
      }
      refreshStatus();
    } finally { scan.busy = false; }
    const box = $('#result');
    refreshAnalyze(); // first: on phones this collapses the options, which moves the result up
    if (box) {
      box.innerHTML = resultHtml();
      box.scrollIntoView({ behavior: 'smooth', block: 'start' });
      $('#result h3')?.focus({ preventScroll: true });  // errors are a role="alert" banner and speak for themselves
    }
    const said = $('#scan-said'), f = scan.result;
    if (said && !f.error) said.textContent = `Result ready: ${f.name}, about ${Math.round(f.cal)} kcal${f.health ? `, health score ${f.health.score} out of 100` : ''}.`;
  },
  // Clears the result and opens the photo picker straight away.
  scanAnother() {
    if (scan.url) URL.revokeObjectURL(scan.url);
    scan = { ...scan, file: null, url: '', result: null, chat: [], added: false };
    show('scan');
    const input = $('#file'); if (input) input.click();
  },
  toggleStreet(box) { scan.result.street = box.checked; const tag = $('#result .tag'); if (tag) tag.hidden = !box.checked; },
  addMeal() {
    if (scan.added) return;
    const before = Math.round(sum(todayMeals(), 'cal'));
    scan.added = true;
    logMeal(newMeal(scan.result, { source: scan.mode, scanId: scan.result.scanId, mealType: scan.result.mealType }));
    const row = $('#result-act');
    if (row) {
      row.innerHTML = resultActHtml(before);
      // Next frame: let the new part of the bar fill in from where the day was.
      requestAnimationFrame(() => requestAnimationFrame(() => row.querySelector('.day-bar .now')?.classList.add('in')));
    }
  },
  swapFor() { cook.focus = scan.result.name; show('cook', { focus: true, push: true }); },
  ask(btn) { return askAbout(btn.dataset.q); },
  send() { const box = $('#q'); return askAbout(box ? box.value.trim() : ''); },
  cooked(btn) {
    const r = [...RECIPES, ...(cook.results ? cook.results.meals : [])].find(x => x.id === btn.dataset.rid);
    if (!r) return;
    logMeal(newMeal({ name: r.meal, cal: r.cal, protein: r.protein, carbs: r.carbs, fat: r.fat, fibre: r.fibre, sodium: r.sodium, sugar: r.sugar, street: false }, { home: true, source: 'swap' }));
    toast('Logged. Nice cooking.');
  },
  pantryAdd(btn) {
    const box = $('#pantry'), items = ingredientTokens(box.value);
    if (!items.includes(stem(btn.dataset.v))) box.value = (box.value.trim().replace(/,$/, '') + ', ' + btn.dataset.v).replace(/^,\s*/, '');
    cook.pantry = box.value;
  },
  async suggest(btn) {
    cook.pantry = $('#pantry').value.trim();
    const items = cook.pantry.split(/,|\n|;/).map(s => s.trim()).filter(Boolean);
    if (!items.length) return toast('Add at least one ingredient');
    if (cook.busy) return;
    cook.busy = true; cook.since = Date.now();
    busyButton(btn, true, 'Finding meals…'); $('#suggestions').innerHTML = suggestionsHtml();
    try { cook.results = await suggestMeals(items, state.profile); } finally { cook.busy = false; }
    const box = $('#suggestions'), b = $('#suggest');
    if (b) { busyButton(b, false); b.innerHTML = 'Suggest meals'; }
    if (box) box.innerHTML = suggestionsHtml();
    refreshStatus();
  },
  filter(btn) { ui.histFilter = btn.dataset.v; show('history'); },
  addManual() {
    const name = $('#m-name').value.trim(), cal = Math.round(+$('#m-cal').value);
    if (!name) return toast('Enter a meal name');
    if (!(cal >= 0 && cal <= 3000) || $('#m-cal').value === '') return toast('Enter calories between 0 and 3000');
    const macro = id => { const v = $('#m-' + id).value; return v === '' ? 0 : +v; };
    const protein = macro('protein'), carbs = macro('carbs'), fat = macro('fat');
    if ([protein, carbs, fat].some(v => !(v >= 0 && v <= 500))) return toast('Protein, carbs and fat should be between 0 and 500 g');
    logMeal(newMeal({ name, cal, protein, carbs, fat, street: $('#m-street').checked || isStreetFood(name) }, { source: 'manual' }));
    toast('Meal added');
    show('history');
  },
  relog(btn) {
    const m = state.meals.find(x => x.id === btn.dataset.id);
    if (!m) return;
    logMeal(newMeal(m, { source: 'manual', mealType: mealTypeAt(Date.now()), home: !!m.home }));
    toast(`Logged ${m.name} again`);
    show(currentPage());
  },
  // Gone from the list at once, but only deleted on the server once the Undo window closes.
  remove(btn) {
    const m = state.meals.find(x => x.id === btn.dataset.id);
    if (!m) return;
    flushRemoval();
    // Where keyboard focus lands once the Undo toast closes: the row that took this one's place.
    const at = [...document.querySelectorAll('[data-act="remove"]')].indexOf(btn);
    state.meals = state.meals.filter(x => x !== m);
    save(); show('history');
    toast(`Removed ${m.name}`, {
      label: 'Undo',
      run: () => {
        pendingRemoval = null; state.meals.push(m); save(); show(currentPage());
        document.querySelector(`[data-act="remove"][data-id="${CSS.escape(m.id)}"]`)?.focus();
        toast('Meal restored');
      },
      expire: flushRemoval,
      refocus: () => { const rows = document.querySelectorAll('[data-act="remove"]'); return rows[at] || rows[at - 1] || $('#main h2'); },
    });
    pendingRemoval = m;  // after the toast: replacing the previous toast finishes the previous removal
  },
  exportCsv() {
    const head = ['date', 'time', 'meal', 'calories', 'protein_g', 'carbs_g', 'fat_g', 'fibre_g', 'sodium_mg', 'sugar_g', 'street_food', 'home_cooked'];
    const rows = [...state.meals].sort((a, b) => a.at - b.at).map(m => {
      const d = new Date(m.at);
      return [d.toLocaleDateString('en-CA'), d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }), m.name, m.cal, m.protein, m.carbs, m.fat, m.fibre ?? '', m.sodium ?? '', m.sugar ?? '', m.street ? 'yes' : 'no', m.home ? 'yes' : 'no'].map(csvCell).join(',');
    });
    const url = URL.createObjectURL(new Blob([[head.join(','), ...rows].join('\n')], { type: 'text/csv' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: 'nutriscan-history.csv' });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
  claim() {
    if (!claimable()) return;
    state.claims.push(Date.now());
    save(); toast('Weekly reward claimed: +50 points');
    show('rewards');
  },
  async suggestGoal() {
    if (signedIn()) {
      const f = k => $('#p-' + k).value;
      try {
        await pushProfile({ age: f('age'), sex: f('sex'), height: f('height'), weight: f('weight'), activity: f('activity'), goalDir: f('goalDir'), diet: f('diet') });
        const t = await fetchTargets();
        $('#p-goal').value = Math.min(4000, Math.max(1200, Math.round(t.calories)));
        toast(`Suggested ${Math.round(t.calories)} kcal a day for your goal. Save to keep it.`);
        return;
      } catch (e) { toast('Could not ask the server: ' + reasonFor(e)); }
    }
    const v = k => +$('#p-' + k).value, sex = $('#p-sex').value, act = { sitting: 1.3, light: 1.5, active: 1.7 }[$('#p-activity').value];
    const bmr = 10 * v('weight') + 6.25 * v('height') - 5 * v('age') + { male: 5, female: -161, other: -78 }[sex];
    const goal = Math.round(bmr * act / 50) * 50;
    if (!Number.isFinite(goal) || goal < 1000) return toast('Fill in age, weight and height first');
    $('#p-goal').value = Math.min(4000, Math.max(1200, goal));
    toast(`Estimated daily need: about ${goal} kcal. Adjust it if you like, then save.`);
  },
  async saveProfile() {
    const val = k => $('#p-' + k).value, p = {};
    const ranges = { age: [13, 100, 'Age'], weight: [25, 250, 'Weight'], height: [100, 230, 'Height'], goal: [1200, 4000, 'Calorie goal'] };
    for (const [k, [lo, hi, label]] of Object.entries(ranges)) {
      const n = +val(k);
      if (!(n >= lo && n <= hi)) return toast(`${label} should be between ${lo} and ${hi}`);
      p[k] = n;
    }
    ['name', 'sex', 'activity', 'goalDir', 'diet', 'kitchen'].forEach(k => { p[k] = val(k).trim(); });
    const allergies = [...new Set(val('allergies').split(',').map(a => a.trim().toLowerCase()).filter(Boolean))];
    if (allergies.length > 20) return toast('List up to 20 allergies');
    if (allergies.some(a => a.length > 60)) return toast('Keep each allergy under 60 characters');
    p.allergies = allergies;
    state.profile = { ...state.profile, ...p };
    state.profileTouched = true;
    save();
    if (canSync() && CFG.endpoints.profile) {
      try { await pushProfile(state.profile); await refreshServerNumbers(); toast('Profile saved and synced'); refreshStatus(); }
      catch (e) { toast('Profile saved on this device. ' + reasonFor(e)); refreshStatus(); }
    } else toast('Profile saved on this device');
    if (currentPage() === 'profile') show('profile');  // don't pull the person back if they moved on meanwhile
  },
  async saveSetup(btn) {
    const picked = Object.fromEntries(Object.keys(SETUP_CHOICES).map(k => [k, document.querySelector(`input[name="setup-${k}"]:checked`)?.value]));
    Object.assign(state.profile, picked);
    state.setupDone = true;
    save();
    const said = `Saved. Suggestions now fit your ${picked.diet.toLowerCase()} diet.`;
    if (canSync() && CFG.endpoints.profile) {
      busyButton(btn, true, 'Saving…');
      try { await pushProfileChoices(state.profile); await refreshServerNumbers(); toast(said); }
      catch (e) { state.profileTouched = true; save(); toast('Saved on this device. ' + reasonFor(e)); }  // keep these over the server's copy
      refreshStatus();
    } else toast(said);
    if (currentPage() === 'dashboard') show('dashboard', { focus: true });
  },
  skipSetup() {
    state.setupDone = true; save();
    toast('Using the defaults. Change them any time in Health profile.');
    show('dashboard', { focus: true });
  },
  syncNow() { return syncNow(true); },
  signOut() { return signOut(); },
  clearMeals() {
    if (!confirm('Remove all logged meals and restart your streak?')) return;
    if (state.sample) dropSample(Date.now());
    state.meals = []; state.startedOn = Date.now();
    save(); toast('Cleared. Your log is empty.');
    show(currentPage() || 'dashboard');
  },
};

// ---------- Events ----------
document.addEventListener('click', e => {
  const t = e.target.closest('[data-page],[data-act]');
  if (!t || t.disabled) return;
  if (t.dataset.page) return show(t.dataset.page, { focus: true, push: true });
  if (t.tagName === 'INPUT') return;
  run(t.dataset.act, t);
});

document.addEventListener('change', e => {
  if (e.target.id === 'file') return setFile(e.target.files[0]);
  if (e.target.dataset.act === 'toggleStreet') run('toggleStreet', e.target);
  if (e.target.name === 'mode') scan.mode = e.target.value;
});

document.addEventListener('dragover', e => { if (e.target.closest('.drop')) { e.preventDefault(); e.target.closest('.drop').classList.add('over'); } });
document.addEventListener('dragleave', e => { const z = e.target.closest && e.target.closest('.drop'); if (z) z.classList.remove('over'); });
document.addEventListener('drop', e => {
  const z = e.target.closest('.drop');
  if (!z) return;
  e.preventDefault(); z.classList.remove('over');
  setFile(e.dataTransfer.files[0]);
});

document.addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  if (e.target.id === 'q') run('send', e.target);
  if (e.target.id === 'pantry') run('suggest', $('#suggest'));
});

function run(name, el) {
  if (!actions[name]) return;
  Promise.resolve(actions[name](el)).catch(err => { console.error(err); toast('Something went wrong. Please try again.'); });
}

window.addEventListener('hashchange', () => { const p = currentPage(); if (pages[p] && $('#main')) show(p); });

// ---------- Start ----------
// While the server is unreachable, check every 10 s and update the sidebar as soon as it is back.
function watchServer() {
  setInterval(async () => {
    if (net.state !== 'offline') return;
    if (await pingServer()) { refreshStatus(); toast('Connected to the server again'); }
  }, 10000);
}

// Nothing here waits on the network before the first render: every server round trip goes to the database
// (hundreds of ms each, seconds on a far-away region), and waiting for them in a row used to leave the page
// blank. The page renders from this device's data first; syncNow then fills in the server's numbers.
(async function boot() {
  refreshStatus(); // "Connecting to the server…"
  pingServer().then(refreshStatus); // only for the sidebar status
  watchServer();
  try {
    await startAuth();
    refreshStatus(); // show who is signed in straight away
    loadState();
    checkBadges(true);
  } catch (err) {
    console.error(err);
    if (!state) state = emptyState();
  }
  show(pages[currentPage()] ? currentPage() : 'dashboard');
  syncNow(false);
})();
