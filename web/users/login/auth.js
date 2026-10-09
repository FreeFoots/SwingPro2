const state = {
  apiBase: window.__API_BASE__ || localStorage.getItem('platformApiBase') || window.location.origin,
  auth: loadAuth(),
  registerOtpCooldown: 0,
  registerOtpTimer: null,
  loginOtpCooldown: 0,
  loginOtpTimer: null,
  mode: 'login',
  loginMethod: 'password',
  qr: {
    token: null,
    mode: 'login',
    expiresAt: 0,
    pollTimer: null,
    expireTimer: null,
    qrUrl: null,
  },
};

const HOME_URL = window.__HOME_URL__ || `${window.location.origin}/platform.html`;

const dom = {};
const ALLOWED_WEB_ROLES = new Set(['admin', 'super_admin', 'system_admin']);
const PASSWORD_PATTERN = /^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{8,16}$/;
const PHONE_PATTERN = /^\d{11}$/;
const INVITE_CODE_PATTERN = /^[a-zA-Z]{8}$/;

document.addEventListener('DOMContentLoaded', () => {
  cacheDom();
  if (state.auth) {
    if (ALLOWED_WEB_ROLES.has(state.auth.role)) {
      redirectHome();
      return;
    }
    saveAuth(null);
  }
  bindSwitchers();
  bindLoginForm();
  bindRegisterForm();
  bindSendOtp();
  bindLoginOtp();
  bindLoginMethodSwitch();
  bindInviteCodePaste();
  bindPhoneInputListeners();
  initQrLogin();
  window.addEventListener('beforeunload', clearQrTimers);
  updateRegisterOtpButton();
  updateLoginOtpButton();
  setMode('login');
});

function cacheDom() {
  dom.authCard = document.getElementById('auth-card');
  dom.authTitle = document.getElementById('auth-title');
  dom.authSubtitle = document.getElementById('auth-subtitle');
  dom.loginForm = document.getElementById('login-form');
  dom.loginSuccess = document.getElementById('login-success');
  dom.loginSwitch = document.getElementById('login-switch');
  dom.loginSwitchButtons = dom.loginSwitch ? Array.from(dom.loginSwitch.querySelectorAll('button[data-method]')) : [];
  dom.loginPasswordRow = document.getElementById('login-password-row');
  dom.loginOtpRow = document.getElementById('login-otp-row');
  dom.loginOtpInput = document.getElementById('login-otp-input');
  dom.loginSendOtp = document.getElementById('login-send-otp');
  dom.registerForm = document.getElementById('register-form');
  dom.switchRegister = document.getElementById('switch-register');
  dom.switchLogin = document.getElementById('switch-login');
  dom.loginLinks = document.getElementById('login-links-bottom');
  dom.loginError = document.getElementById('login-error');
  dom.registerError = document.getElementById('register-error');
  dom.registerSuccess = document.getElementById('register-success');
  dom.sendOtp = document.getElementById('send-otp');
  dom.inviteCodeInput = dom.registerForm?.querySelector('input[name="invite_code"]');
  dom.loginPhoneInput = dom.loginForm?.querySelector('input[name="telephone"]');
  dom.registerPhoneInput = dom.registerForm?.querySelector('input[name="telephone"]');
  dom.qrSection = document.getElementById('qr-login');
  dom.qrFrame = document.getElementById('qr-frame');
  dom.qrExpired = document.getElementById('qr-expired');
}

function bindSwitchers() {
  dom.switchRegister?.addEventListener('click', () => {
    setMode('register');
  });
  dom.switchLogin?.addEventListener('click', () => {
    setMode('login');
  });
}

function bindLoginForm() {
  dom.loginForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearLoginMessages();
    const form = new FormData(dom.loginForm);
    try {
      const telephone = form.get('telephone').toString().trim();
      if (!telephone) {
        throw new Error('请填写手机号');
      }
      if (!PHONE_PATTERN.test(telephone)) {
        throw new Error('请输入完整的11位手机号');
      }
      const payload = { telephone };
      if (state.loginMethod === 'password') {
        const password = form.get('password')?.toString() || '';
        if (!password) {
          throw new Error('请填写密码');
        }
        if (!isPasswordValid(password)) {
          throw new Error('密码需 8-16 位，包含字母和数字，且仅支持字母数字');
        }
        payload.password = password;
      } else {
        const otp = form.get('login_otp')?.toString().trim();
        if (!otp) {
          throw new Error('请填写短信验证码');
        }
        payload.otp = otp;
      }
      const res = await apiFetch('/auth/login', { method: 'POST', body: payload });
      setSession(res, payload.telephone);
      redirectHome();
    } catch (err) {
      dom.loginError.textContent = err.message;
      dom.loginError.hidden = false;
    }
  });
}

function bindLoginMethodSwitch() {
  if (!dom.loginSwitch) return;
  dom.loginSwitch.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-method]');
    if (!btn) return;
    setLoginMethod(btn.dataset.method);
  });
}

function setLoginMethod(method = 'password') {
  if (!['password', 'otp', 'wechat'].includes(method)) {
    method = 'password';
  }
  state.loginMethod = method;
  dom.loginSwitchButtons?.forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.method === method);
  });
  const isWechat = method === 'wechat';
  if (dom.loginForm) dom.loginForm.hidden = isWechat;
  if (dom.loginPasswordRow) {
    dom.loginPasswordRow.hidden = method !== 'password';
    const pwdInput = dom.loginPasswordRow.querySelector('input[name="password"]');
    if (pwdInput) pwdInput.required = method === 'password';
  }
  if (dom.loginOtpRow) {
    dom.loginOtpRow.hidden = method !== 'otp';
  }
  if (dom.loginOtpInput) dom.loginOtpInput.required = method === 'otp';
  if (dom.qrSection) {
    dom.qrSection.hidden = !isWechat;
    if (isWechat) {
      if (!state.qr.token) {
        createQrCode();
      } else {
        startQrTimers();
      }
    }
    if (!isWechat) {
      clearQrTimers();
    }
  }
  clearLoginMessages();
}

function bindLoginOtp() {
  dom.loginSendOtp?.addEventListener('click', async () => {
    if (state.loginOtpCooldown > 0) return;
    clearLoginMessages();
    const form = new FormData(dom.loginForm);
    const telephone = form.get('telephone')?.toString().trim();
    if (!telephone) {
      dom.loginError.textContent = '请先填写手机号';
      dom.loginError.hidden = false;
      return;
    }
    if (!PHONE_PATTERN.test(telephone)) {
      dom.loginError.textContent = '请输入完整的11位手机号';
      dom.loginError.hidden = false;
      return;
    }
    try {
      const res = await apiFetch('/auth/send-code', {
        method: 'POST',
        body: { telephone },
      });
      if (dom.loginSuccess) {
        dom.loginSuccess.textContent = `验证码已发送，${res.mock_otp ? `测试环境验证码：${res.mock_otp}` : '请查收短信'}`;
        dom.loginSuccess.hidden = false;
      }
      startLoginOtpCountdown();
    } catch (err) {
      dom.loginError.textContent = `发送验证码失败：${err.message}`;
      dom.loginError.hidden = false;
    }
  });
}

function bindRegisterForm() {
  dom.registerForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearRegisterMessages();
    const form = new FormData(dom.registerForm);
    try {
      const telephone = form.get('telephone')?.toString().trim();
      if (!telephone) {
        throw new Error('请填写手机号');
      }
      if (!PHONE_PATTERN.test(telephone)) {
        throw new Error('请输入完整的11位手机号');
      }

      const password = form.get('password')?.toString().trim();
      if (!isPasswordValid(password)) {
        throw new Error('密码需 8-16 位，包含字母和数字，且仅支持字母数字');
      }
      const confirmPassword = form.get('confirm_password')?.toString().trim();
      if (!confirmPassword) {
        throw new Error('请再次输入密码');
      }
      if (password !== confirmPassword) {
        throw new Error('两次输入的密码不一致');
      }

      const invite_code = form.get('invite_code')?.toString().trim();
      if (!INVITE_CODE_PATTERN.test(invite_code)) {
        throw new Error('邀请码格式错误（8位大小写字母）');
      }

      const otp = form.get('otp')?.toString().trim();
      if (!otp) {
        throw new Error('请填写验证码');
      }

      const payload = {
        telephone,
        password,
        invite_code,
        otp,
      };

      const res = await apiFetch('/auth/register', { method: 'POST', body: payload });
      setSession(res, payload.telephone);
      dom.registerSuccess.hidden = false;
      dom.registerSuccess.textContent = '注册成功，正在跳转…';
      setTimeout(redirectHome, 400);
    } catch (err) {
      dom.registerError.textContent = err.message;
      dom.registerError.hidden = false;
    }
  });
}

function bindSendOtp() {
  dom.sendOtp?.addEventListener('click', async () => {
    if (state.registerOtpCooldown > 0) return;
    clearRegisterMessages();
    const form = new FormData(dom.registerForm);
    const telephone = form.get('telephone')?.toString().trim();
    if (!telephone) {
      dom.registerError.textContent = '请先填写手机号';
      dom.registerError.hidden = false;
      return;
    }
    if (!PHONE_PATTERN.test(telephone)) {
      dom.registerError.textContent = '请输入完整的11位手机号';
      dom.registerError.hidden = false;
      return;
    }
    try {
      const res = await apiFetch('/auth/send-code', {
        method: 'POST',
        body: { telephone },
      });
      dom.registerSuccess.textContent = `验证码已发送，${res.mock_otp ? `测试环境验证码：${res.mock_otp}` : '请查收短信'}`;
      dom.registerSuccess.hidden = false;
      startRegisterOtpCountdown();
    } catch (err) {
      dom.registerError.textContent = `发送验证码失败：${err.message}`;
      dom.registerError.hidden = false;
    }
  });
}

function bindInviteCodePaste() {
  if (!dom.inviteCodeInput) return;
  dom.inviteCodeInput.addEventListener('paste', (e) => {
    e.preventDefault();
    const text = (e.clipboardData || window.clipboardData).getData('text');
    // Extract 8-char alphanumeric code.
    // The user example: "您的邀请码为 rCMFLxjN，有效期截止..."
    // We look for exactly 8 alphanumeric chars surrounded by non-alphanumeric or boundary.
    // Or just the first 8-char alphanumeric sequence.
    const match = text.match(/[a-zA-Z0-9]{8}/);
    if (match) {
      dom.inviteCodeInput.value = match[0];
    } else {
      dom.inviteCodeInput.value = text;
    }
  });
}

function bindPhoneInputListeners() {
  const checkPhone = (input, btn) => {
    if (!input || !btn) return;
    const val = input.value.trim();
    const isValid = PHONE_PATTERN.test(val);
    btn.disabled = !isValid || (btn === dom.loginSendOtp ? state.loginOtpCooldown > 0 : state.registerOtpCooldown > 0);
  };

  if (dom.loginPhoneInput && dom.loginSendOtp) {
    dom.loginPhoneInput.addEventListener('input', () => checkPhone(dom.loginPhoneInput, dom.loginSendOtp));
    // Initial check
    checkPhone(dom.loginPhoneInput, dom.loginSendOtp);
  }

  if (dom.registerPhoneInput && dom.sendOtp) {
    dom.registerPhoneInput.addEventListener('input', () => checkPhone(dom.registerPhoneInput, dom.sendOtp));
    // Initial check
    checkPhone(dom.registerPhoneInput, dom.sendOtp);
  }
}

function isPasswordValid(pwd) {
  return PASSWORD_PATTERN.test(pwd || '');
}

function apiFetch(path, { method = 'GET', body, headers = {} } = {}) {
  if (!state.apiBase) {
    return Promise.reject(new Error('API 地址未设置'));
  }
  const opts = { method, headers: { ...headers } };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  return fetch(`${state.apiBase}${path}`, opts).then(async (res) => {
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `请求失败：${res.status}`);
    }
    if (res.status === 204) return null;
    return res.json();
  });
}

function setSession(res, telephone) {
  const payload = decodeJwt(res.access_token);
  const userId = res.user_id || payload?.sub;
  const role = payload?.role || 'normal';
  const expiresAt = payload?.exp ? payload.exp * 1000 : null;
  if (!ALLOWED_WEB_ROLES.has(role)) {
    throw new Error('当前账号无权登录 Web 平台，请使用管理端账号');
  }
  const data = {
    accessToken: res.access_token,
    refreshToken: res.refresh_token,
    userId,
    role,
    telephone,
    expiresAt,
  };
  saveAuth(data);
}

function decodeJwt(token) {
  if (!token) return null;
  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const decoded = decodeURIComponent(atob(base64).split('').map((c) => `%${(`00${c.charCodeAt(0).toString(16)}`).slice(-2)}`).join(''));
    return JSON.parse(decoded);
  } catch (err) {
    console.warn('decode error', err);
    return null;
  }
}

function loadAuth() {
  try {
    const raw = localStorage.getItem('platformAuth');
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (err) {
    console.warn('loadAuth error', err);
    return null;
  }
}

function saveAuth(data) {
  if (!data) {
    localStorage.removeItem('platformAuth');
    state.auth = null;
  } else {
    state.auth = data;
    localStorage.setItem('platformAuth', JSON.stringify(data));
  }
}

function redirectHome() {
  if (!HOME_URL) return;
  const isAbsolute = /^https?:\/\//i.test(HOME_URL);
  if (isAbsolute) {
    if (window.location.href === HOME_URL) return;
  } else if (window.location.pathname === HOME_URL) {
    return;
  }
  window.location.replace(HOME_URL);
}

function startRegisterOtpCountdown(seconds = 60) {
  clearInterval(state.registerOtpTimer);
  state.registerOtpCooldown = seconds;
  updateRegisterOtpButton();
  state.registerOtpTimer = setInterval(() => {
    state.registerOtpCooldown -= 1;
    updateRegisterOtpButton();
    if (state.registerOtpCooldown <= 0) {
      clearInterval(state.registerOtpTimer);
      state.registerOtpTimer = null;
      state.registerOtpCooldown = 0;
      updateRegisterOtpButton();
    }
  }, 1000);
}

function updateRegisterOtpButton() {
  if (!dom.sendOtp) return;
  if (state.registerOtpCooldown > 0) {
    dom.sendOtp.disabled = true;
    dom.sendOtp.textContent = `${state.registerOtpCooldown}s 后重发`;
  } else {
    dom.sendOtp.disabled = false;
    dom.sendOtp.textContent = '发送验证码';
  }
}

function startLoginOtpCountdown(seconds = 60) {
  clearInterval(state.loginOtpTimer);
  state.loginOtpCooldown = seconds;
  updateLoginOtpButton();
  state.loginOtpTimer = setInterval(() => {
    state.loginOtpCooldown -= 1;
    updateLoginOtpButton();
    if (state.loginOtpCooldown <= 0) {
      clearInterval(state.loginOtpTimer);
      state.loginOtpTimer = null;
      state.loginOtpCooldown = 0;
      updateLoginOtpButton();
    }
  }, 1000);
}

function updateLoginOtpButton() {
  if (!dom.loginSendOtp) return;
  if (state.loginOtpCooldown > 0) {
    dom.loginSendOtp.disabled = true;
    dom.loginSendOtp.textContent = `${state.loginOtpCooldown}s 后重发`;
  } else {
    dom.loginSendOtp.disabled = false;
    dom.loginSendOtp.textContent = '发送验证码';
  }
}

function initQrLogin() {
  // QR setup happens lazily when user switches to WeChat login.
}

async function createQrCode() {
  if (!dom.qrSection) return;
  clearQrTimers();
  if (dom.qrExpired) dom.qrExpired.hidden = true;
  if (dom.qrFrame) dom.qrFrame.src = '';
  setQrStatus('loading', '正在获取二维码…');
  try {
    const res = await apiFetch('/auth/wechat-qr/login', { method: 'POST' });
    state.qr.token = res.qr_token;
    state.qr.mode = 'login';
    state.qr.expiresAt = Date.now() + (res.expires_in || 180) * 1000;
    state.qr.qrUrl = res.qrcode_url || res.qr_image_url;
    if (!state.qr.qrUrl) {
      throw new Error('未返回二维码地址');
    }
    if (dom.qrFrame) dom.qrFrame.src = state.qr.qrUrl;
    setQrStatus('waiting', '请使用微信扫描二维码登录');
    startQrTimers();
  } catch (err) {
    setQrStatus('error', err.message || '获取二维码失败');
    if (dom.qrExpired) dom.qrExpired.hidden = false;
  }
}

function startQrTimers() {
  clearQrTimers();
  state.qr.pollTimer = setInterval(pollQrCode, 1800);
  state.qr.expireTimer = setInterval(() => {
    if (state.qr.expiresAt && Date.now() >= state.qr.expiresAt) {
      markQrExpired();
    }
  }, 1000);
}

async function pollQrCode() {
  if (!state.qr.token || state.loginMethod !== 'wechat') return;
  const url = `/auth/wechat-web/poll?qr_token=${encodeURIComponent(state.qr.token)}&mode=${encodeURIComponent(state.qr.mode)}`;
  try {
    const res = await apiFetch(url);
    if (res.status === 'pending') return;
    if (res.status === 'error') {
      setQrStatus('error', res.message || '扫码失败');
      markQrExpired(true);
      return;
    }
    if (res.status === 'ready') {
      clearQrTimers();
      setSession(res, res.telephone || '');
      redirectHome();
      return;
    }
  } catch (err) {
    setQrStatus('error', err.message || '扫码失败');
    markQrExpired(true);
  }
}

function markQrExpired(showMessage = false) {
  clearQrTimers();
  state.qr.token = null;
  state.qr.expiresAt = 0;
  state.qr.qrUrl = null;
  if (dom.qrExpired) dom.qrExpired.hidden = false;
  if (showMessage) setQrStatus('error', '二维码已失效，请刷新重试');
}

function setQrStatus(status, text) {
  // Status text removed from UI; keep hook for future logging if needed.
}

function clearQrTimers() {
  if (state.qr.pollTimer) {
    clearInterval(state.qr.pollTimer);
    state.qr.pollTimer = null;
  }
  if (state.qr.expireTimer) {
    clearInterval(state.qr.expireTimer);
    state.qr.expireTimer = null;
  }
}

function parseError(err) {
  if (!err) return '请求失败';
  if (typeof err === 'string') return err;
  return err.message || '请求失败';
}

function setMode(mode) {
  state.mode = mode;
  const isLogin = mode === 'login';
  if (dom.loginForm) {
    dom.loginForm.hidden = !isLogin;
  }
  if (dom.loginError) dom.loginError.hidden = true;
  if (dom.loginSuccess) dom.loginSuccess.hidden = true;
  if (dom.loginLinks) dom.loginLinks.hidden = !isLogin;
  if (dom.registerForm) {
    dom.registerForm.hidden = isLogin;
  }
  clearRegisterMessages();
  if (dom.authTitle) dom.authTitle.textContent = isLogin ? '登录账户' : '注册账户';
  if (dom.authSubtitle) dom.authSubtitle.textContent = isLogin ? '欢迎回到 Golf 视频平台' : '填写信息以创建新账户';
  dom.authCard?.classList.toggle('mode-register', !isLogin);
  if (dom.switchRegister) dom.switchRegister.setAttribute('aria-pressed', (!isLogin).toString());
  if (isLogin) {
    setLoginMethod('password');
  }
  if (!isLogin && dom.qrSection) {
    dom.qrSection.hidden = true;
    clearQrTimers();
  }
}

function clearRegisterMessages() {
  if (dom.registerError) dom.registerError.hidden = true;
  if (dom.registerSuccess) dom.registerSuccess.hidden = true;
}

function clearLoginMessages() {
  if (dom.loginError) dom.loginError.hidden = true;
  if (dom.loginSuccess) dom.loginSuccess.hidden = true;
}
