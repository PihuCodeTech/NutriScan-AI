// ScanMyFood web: sign-in against the NutriScan AI backend (email + password → JWT bearer token, 7-day expiry).
// Everyone uses the server, so scans, chat, meal ideas and insights always come from Gemini.
// "Continue as guest" creates a throw-away guest account on the server (POST /auth/guest): no sign-up, same AI.
//
// The sign-in screen shows every time the app is opened. The session token lives in sessionStorage, so it
// survives reloads in the same tab but is gone when the tab or browser is closed. Ticking "Keep me signed in"
// stores it in localStorage instead, so this browser skips the sign-in screen until "Sign out" (or 7 days).
const auth = { mode: 'none', user: null }; // mode: 'none' (not signed in yet) | 'account'
const TOKEN_KEY = 'smf_token';
const USER_KEY = 'smf_user';
const REMEMBER_KEY = 'smf_remember';
const EXPIRED_FLAG = 'smf_expired';
const LEGACY_KEYS = ['smf_guest']; // older versions auto-started guest mode from this flag

const remembered = () => localStorage.getItem(REMEMBER_KEY) === '1';
const sessionStore = () => (remembered() ? localStorage : sessionStorage);
const readJson = (store, key) => { try { return JSON.parse(store.getItem(key)); } catch { return null; } };
const isGuestUser = () => !!auth.user?.is_guest;
const authLabel = () => auth.mode !== 'account' ? 'Not signed in' : isGuestUser() ? 'Guest' : (auth.user?.name || auth.user?.email || 'Signed in');
const authUid = () => auth.mode === 'account' ? auth.user.id : 'none';
const userFields = u => ({ id: u.id, email: u.email, name: u.name, is_guest: !!u.is_guest });

function clearSession() {
  for (const store of [localStorage, sessionStorage]) { store.removeItem(TOKEN_KEY); store.removeItem(USER_KEY); }
  localStorage.removeItem(REMEMBER_KEY);
}

window.getAuthToken = () => (auth.mode === 'account' ? sessionStore().getItem(TOKEN_KEY) : null);

// Called by callApi on a 401 with a token: the token expired or the account is gone.
window.onSessionExpired = () => {
  if (auth.mode !== 'account') return;
  clearSession();
  sessionStorage.setItem(EXPIRED_FLAG, '1');
  location.reload();
};

function loginMarkup() {
  return `<div class="login-card" role="dialog" aria-modal="true" aria-labelledby="login-title">
    <h2 id="login-title">ScanMyFood</h2>
    <p>Photograph what you eat and see what it does to your gut, skin, liver and kidneys. Sign in to keep your meals on every device, or continue as a guest: the AI scanner and chat work the same way.</p>
    <form id="lg-form">
      <label>Email<input id="lg-email" type="email" autocomplete="email" required></label>
      <label>Password<input id="lg-pass" type="password" autocomplete="current-password" minlength="8" required></label>
      <label id="lg-name-row" hidden>Your name<input id="lg-name" type="text" autocomplete="name" maxlength="100"></label>
      <label class="lg-keep"><input id="lg-keep" type="checkbox"> Keep me signed in on this device</label>
      <div class="login-row"><button class="btn" type="submit" data-mode="in">Sign in</button>
      <button class="btn alt" type="submit" data-mode="up">Create account</button></div>
    </form>
    <p id="login-msg" role="alert" class="login-msg"></p>
    <button class="btn ghost-ink" id="lg-guest" type="button">Continue as guest</button>
    <p class="sub small">Guest sessions end when you close this tab. Create an account to keep your meals.</p>
  </div>`;
}

const authRequest = (path, body) => callApi(path, { method: 'POST', ...jsonBody(body) });

// Guests are never remembered: each "Continue as guest" is a fresh, throw-away session.
function saveSession(r, remember) {
  clearSession();
  if (remember) localStorage.setItem(REMEMBER_KEY, '1');
  const store = remember ? localStorage : sessionStorage;
  store.setItem(TOKEN_KEY, r.access_token);
  store.setItem(USER_KEY, JSON.stringify(userFields(r.user)));
}

function showLogin(onDone, startMessage) {
  const box = document.getElementById('login');
  box.innerHTML = loginMarkup();
  box.hidden = false;
  const msg = text => { document.getElementById('login-msg').textContent = text || ''; };
  if (startMessage) msg(startMessage);
  const finish = user => { box.hidden = true; box.innerHTML = ''; onDone(user); };
  const buttons = () => [...document.querySelectorAll('#login button')];

  document.getElementById('lg-guest').onclick = async () => {
    msg('');
    buttons().forEach(b => { b.disabled = true; });
    try {
      const r = await authRequest(endpoint('guest'), {});
      saveSession(r, false);
      finish(r.user);
    } catch (e) { msg('Could not start a guest session. ' + reasonFor(e)); }
    finally { buttons().forEach(b => { b.disabled = false; }); }
  };
  document.getElementById('lg-form').onsubmit = async ev => {
    ev.preventDefault(); msg('');
    const create = ev.submitter && ev.submitter.dataset.mode === 'up';
    const email = document.getElementById('lg-email').value.trim(), password = document.getElementById('lg-pass').value;
    const nameRow = document.getElementById('lg-name-row'), nameBox = document.getElementById('lg-name');
    if (create && nameRow.hidden) { nameRow.hidden = false; nameBox.focus(); return msg('Add your name, then choose "Create account" again.'); }
    const name = nameBox.value.trim() || email.split('@')[0];
    buttons().forEach(b => { b.disabled = true; });
    try {
      const r = create
        ? await authRequest(endpoint('register'), { email, password, name })
        : await authRequest(endpoint('login'), { email, password });
      saveSession(r, document.getElementById('lg-keep').checked);
      finish(r.user);
    } catch (e) {
      if (e.code === 'VALIDATION_ERROR' && e.details?.length) {
        const field = e.details[0].loc?.slice(-1)[0];
        msg(field === 'password' ? 'Use a password with at least 8 characters.' : field === 'email' ? 'Enter a valid email address.' : e.serverMessage);
      } else if (e.code === 'EMAIL_TAKEN') msg('That email already has an account. Choose "Sign in".');
      else msg(reasonFor(e));
    } finally { buttons().forEach(b => { b.disabled = false; }); }
  };
  document.getElementById('lg-email').focus();
}

// Resolves once the person has signed in, created an account or chosen guest.
async function startAuth() {
  LEGACY_KEYS.forEach(k => localStorage.removeItem(k));
  // A token left in localStorage by an older version (which always remembered) is dropped unless the person
  // ticked "Keep me signed in".
  if (!remembered()) { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); }

  const store = sessionStore();
  const token = store.getItem(TOKEN_KEY), cached = readJson(store, USER_KEY);
  if (token && cached?.id) {
    auth.mode = 'account'; auth.user = cached;
    try {
      const me = await callApi(endpoint('me'));
      auth.user = userFields(me);
      store.setItem(USER_KEY, JSON.stringify(auth.user));
      return;
    } catch (e) {
      if (e.offline) return; // keep working from this device; calls retry when the server is back
      auth.mode = 'none'; auth.user = null;
      clearSession();
    }
  }
  const expired = sessionStorage.getItem(EXPIRED_FLAG) === '1';
  sessionStorage.removeItem(EXPIRED_FLAG);
  const first = net.state === 'offline' ? reasonFor({ offline: true }) : expired ? 'Your session expired. Please sign in again.' : '';
  await new Promise(resolve => showLogin(user => {
    auth.mode = 'account';
    auth.user = userFields(user);
    resolve();
  }, first));
}

async function signOut() {
  clearSession();
  location.reload();
}
