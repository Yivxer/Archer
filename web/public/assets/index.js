const scene = document.getElementById('scene');
let ritualActive = false;

// 视差跟随
scene.addEventListener('mousemove', (e) => {
  if (ritualActive) return;
  const x = (e.clientX / window.innerWidth  - 0.5) * 16;
  const y = (e.clientY / window.innerHeight - 0.5) * 12;
  scene.style.setProperty('--mx', `${x}px`);
  scene.style.setProperty('--my', `${y}px`);
});
scene.addEventListener('mouseleave', () => {
  scene.style.setProperty('--mx', '0px');
  scene.style.setProperty('--my', '0px');
});

// 主题切换
document.getElementById('themeToggle').addEventListener('click', () => {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  if (isDark) {
    document.documentElement.removeAttribute('data-theme');
    localStorage.setItem('archer-theme', 'light');
  } else {
    document.documentElement.setAttribute('data-theme', 'dark');
    localStorage.removeItem('archer-theme');
  }
});

const SOUL_STORAGE_KEY = 'archer-soul-state-v1';
const INVITE_CODES = [
  'YIVXER',
  'HAHQ-GVFT','E8QN-7V6C','UB42-77ZX','8DDC-D6S4','7M9M-VJ3D',
  'TDQQ-3VAS','62ET-T5CE','FMQB-N6XA','2TDM-EH5N','2GJJ-VCHC',
  'FEZV-DRBV','HJVY-D9UT','DQAS-R72Y','W6PK-65XZ','KJVM-25B5',
  'F2DM-QBA6','465N-766K','7G56-66W7','YE5F-7RYD','D478-R3XH',
  'HC8R-WCWY','2DXD-3KR2','G8AF-TMRJ','S3MG-D5SZ','EMVG-5RM2',
  'VHQB-U7AM','Q62C-752V','6BGW-XAG4','RTN8-N4D6','8CWR-BWD8'
];
const INVITE_KEY = 'archer_invite_verified';
const RESET_KEYS = [SOUL_STORAGE_KEY, 'archer_soul', 'archer_soul_answers', INVITE_KEY];
const SUPABASE_URL = 'https://lwtgagkykcilomdfynkj.supabase.co';
const SUPABASE_KEY = 'sb_publishable_xJiGJ0eERe7WbvCnp_m9ng_7yTkbbzG';
const sb = window.supabase ? supabase.createClient(SUPABASE_URL, SUPABASE_KEY) : null;
let inviteSession = null;

function webAuthOrigin() {
  return location.protocol === 'file:' ? 'http://127.0.0.1:4174' : location.origin;
}

if (new URLSearchParams(window.location.search).has('reset')) {
  RESET_KEYS.forEach((key) => localStorage.removeItem(key));
  history.replaceState(null, '', window.location.pathname);
}

function loadSoulState() {
  try {
    return JSON.parse(localStorage.getItem(SOUL_STORAGE_KEY) || '{}');
  } catch (e) {
    return {};
  }
}

function saveSoulState(patch) {
  const next = {
    ...loadSoulState(),
    ...patch,
    updatedAt: new Date().toISOString()
  };
  localStorage.setItem(SOUL_STORAGE_KEY, JSON.stringify(next));
  setHomeProgress();
  return next;
}

function uniqueDeepAnswers(state = loadSoulState()) {
  const answers = Array.isArray(state.deepAnswers) ? state.deepAnswers : [];
  const seen = new Set();
  return answers.filter(item => {
    if (!item || seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
}

function soulDepth(state = loadSoulState()) {
  const deepCount = uniqueDeepAnswers(state).length;
  return (state.initialComplete ? 10 : 0) + deepCount;
}

function formatMdValue(value) {
  return String(value || '').trim() || '未填写';
}

function buildSoulMarkdown() {
  const state = loadSoulState();
  const depth = soulDepth(state);
  const soulAnswers = state.soulAnswers || {};
  const initialAnswers = Array.isArray(state.initialAnswers) ? state.initialAnswers : [];
  const deepAnswers = uniqueDeepAnswers(state);
  const generatedAt = new Date().toLocaleString('zh-CN', { hour12: false });

  const lines = [
    '# Soul.md',
    '',
    `生成时间：${generatedAt}`,
    `Soul 深度：${depth}/50`,
    '',
    '## 初始信息',
    '',
    `- 称呼：${formatMdValue(soulAnswers[1])}`,
    `- 最近常想：${formatMdValue(soulAnswers[2])}`,
    `- 希望 Archer 如何对你：${formatMdValue(soulAnswers[3])}`,
    '',
    '## 灵魂十问',
    ''
  ];

  if (initialAnswers.length) {
    initialAnswers.forEach((item, index) => {
      lines.push(`### ${index + 1}. ${formatMdValue(item.q)}`, '');
      lines.push(formatMdValue(item.a), '');
    });
  } else {
    lines.push('暂无回答。', '');
  }

  lines.push('## 深度问题', '');
  if (deepAnswers.length) {
    deepAnswers.forEach((item, index) => {
      lines.push(`### ${index + 11}. ${formatMdValue(item.q)}`, '');
      lines.push(formatMdValue(item.a), '');
    });
  } else {
    lines.push('暂无回答。', '');
  }

  return `${lines.join('\n').trim()}\n`;
}

function syncSoulForChat() {
  localStorage.setItem('archer_soul', buildSoulMarkdown());
}

function getLiveChatEls() {
  return {
    view: document.getElementById('liveChatView'),
    messages: document.getElementById('liveChatMessages'),
    input: document.getElementById('liveChatInput'),
    send: document.getElementById('liveChatSendBtn'),
    status: document.getElementById('liveChatStatus')
  };
}

function addLiveMessage(role, text) {
  const { messages } = getLiveChatEls();
  const bubble = document.createElement('div');
  bubble.className = `live-message ${role}`;
  bubble.textContent = text;
  messages.appendChild(bubble);
  bubble.scrollIntoView({ block: 'end', behavior: 'smooth' });
  return bubble;
}

function compactText(value, fallback = '未填写') {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return fallback;
  return text.length > 62 ? `${text.slice(0, 62)}…` : text;
}

function answerAt(index, fallback = '') {
  const state = loadSoulState();
  const answers = Array.isArray(state.initialAnswers) ? state.initialAnswers : [];
  return answers[index]?.a || fallback;
}

function updateWorkspaceContext() {
  const state = loadSoulState();
  const depth = soulDepth(state);
  document.getElementById('liveChatStatus').textContent = `Web Trial · ${depth >= 50 ? '深度 Soul' : '临时 Soul'} 已载入`;
}

function buildFirstWorkspaceReply() {
  const grounded = compactText(answerAt(0), '');
  const unsaid = compactText(answerAt(1), '');
  const release = compactText(answerAt(2), '');
  const feeling = compactText(answerAt(4), '');
  const standard = compactText(answerAt(5), '');
  const tonight = compactText(answerAt(9), '');

  if (!grounded && !unsaid && !standard) {
    return '你的 Soul 已经载入。\n\n现在不用重新介绍自己。说一个最近反复出现的处境，或者直接把刚才没有写完的那句话接着写下去。';
  }

  const first = unsaid || standard || grounded;
  const second = standard || release || feeling || tonight;
  const question = standard
    ? '那个标准如果今晚先放低一点，你最怕失去的是什么？'
    : unsaid
      ? '这件还放在心上的事，如果不再被你压低声音，它真正要你承认什么？'
      : '那个让你踏实的时刻，为什么不是你生活里的常态？';

  return `${first}，这不像一个可以随手放下的念头。\n\n${second ? `它和「${second}」之间有一条线：你并不是不知道自己想要什么，而是还在判断代价。` : '它更像一个还没有被你完整说出来的判断。'}\n\n${question}`;
}

function openLiveChat() {
  syncSoulForChat();
  const { view, messages, input } = getLiveChatEls();
  updateWorkspaceContext();
  view.classList.add('shown');
  view.setAttribute('aria-hidden', 'false');
  closeInviteModal();
  $ending?.classList?.remove('shown');
  $deepCheckpoint?.classList?.remove('shown');
  $sceneChat?.classList?.remove('shown');
  $miniRing?.classList?.remove('shown');
  if (!messages.dataset.started) {
    startWorkspaceThread('first');
  }
  setTimeout(() => input.focus({ preventScroll: true }), 80);
}

function closeLiveChat() {
  const { view, input } = getLiveChatEls();
  input.blur();
  view.classList.remove('shown');
  view.setAttribute('aria-hidden', 'true');
  setHomeProgress();
}

async function sendLiveChat() {
  const { input, send } = getLiveChatEls();
  const text = input.value.trim();
  if (!text || send.disabled) return;
  addLiveMessage('user', text);
  input.value = '';
  input.style.height = 'auto';
  send.disabled = true;
  const typing = addLiveMessage('archer', '我收到了。\n\n这条内容现在先停留在网页端的临时会话里。等 Web Chat 后端接入后，Archer 会基于你的 Soul 继续往下追问；如果你想把这份上下文带走，可以先下载 Soul.md，或之后在客户端继续。');
  typing.scrollIntoView({ block: 'end', behavior: 'smooth' });
  send.disabled = false;
}

function addWorkspaceNotice(text) {
  addLiveMessage('system', text);
}

function showDesktopNotice() {
  addWorkspaceNotice('客户端入口会放在这里：长期聊天、记忆确认、Soul 管理和本地工作台会在桌面端继续。当前版本先保留为下载入口占位。');
}

function showTerminalNotice() {
  addWorkspaceNotice('终端版入口会放在这里：适合连接 Obsidian、Shell、GitHub 和自动化工作流。等终端侧稳定后，这里会放安装方式。');
}

function startWorkspaceThread(thread = 'first') {
  const { messages, input } = getLiveChatEls();
  messages.replaceChildren();
  messages.dataset.started = '1';
  input.value = '';
  input.style.height = 'auto';
  const titles = {
    first: '初次使用 Archer',
    current: '现在卡住的事',
    soul: '继续完善 Soul'
  };
  document.getElementById('liveThreadTitle').textContent = titles[thread] || titles.first;
  document.querySelectorAll('.conversation-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.thread === thread);
  });
  const depth = soulDepth();
  const companion = window.ArcherWebCompanion;
  const systemNote = companion?.buildWebCompanionSystemNote?.(depth)
    || `临时 Soul 已载入 · 当前深度 ${depth}/50 · 内容只保存在这个浏览器`;
  addLiveMessage('system', systemNote);
  if (thread === 'current') {
    addLiveMessage('archer', companion?.buildWebThreadOpening?.('current') || '说一个现在卡住的处境就好。\n\n不需要把前因后果讲完整，先从最不舒服的那一处开始。');
  } else if (thread === 'soul') {
    addLiveMessage('archer', companion?.buildWebThreadOpening?.('soul') || '如果你想让 Archer 更稳定地理解你，可以继续完善 Soul。\n\n也可以先告诉我：刚才那些问题里，哪一题最不像普通问卷？');
  } else {
    addLiveMessage('archer', buildFirstWorkspaceReply());
  }
  document.querySelector('.live-chat-card')?.classList.remove('sidebar-open');
  setTimeout(() => input.focus({ preventScroll: true }), 80);
}

function setWorkspaceBackground(bg) {
  const card = document.querySelector('.live-chat-card');
  if (!card) return;
  card.classList.remove('bg-deep', 'bg-paper', 'bg-plain');
  card.classList.add(`bg-${bg}`);
  localStorage.setItem('archer-web-bg', bg);
  document.querySelectorAll('.bg-choice').forEach((button) => {
    button.classList.toggle('active', button.dataset.bg === bg);
  });
}

function downloadSoulMarkdown() {
  syncSoulForChat();
  const blob = new Blob([buildSoulMarkdown()], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'Soul.md';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 500);
}

function buildSoulJson() {
  const state = loadSoulState();
  const exporter = window.ArcherSoulProfile?.buildSoulExport;
  const payload = typeof exporter === 'function'
    ? exporter(state)
    : {
      version: 2,
      exportedAt: new Date().toISOString(),
      depth: soulDepth(state),
      soulAnswers: state.soulAnswers || {},
      initialAnswers: Array.isArray(state.initialAnswers) ? state.initialAnswers : [],
      deepAnswers: uniqueDeepAnswers(state),
      soulProfile: {},
    };
  return JSON.stringify(payload, null, 2);
}

function downloadSoulJson() {
  const blob = new Blob([buildSoulJson()], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'archer-soul.json';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 500);
}

function isInviteVerified() {
  return localStorage.getItem(INVITE_KEY) === '1';
}

function verifyInvite(code) {
  return INVITE_CODES.includes(String(code || '').trim().toUpperCase());
}

async function refreshInviteAuth() {
  const status = document.getElementById('inviteAuthStatus');
  const form = document.getElementById('inviteEmailForm');
  const googleSection = document.getElementById('inviteGoogleSection');
  const userLine = document.getElementById('inviteUserLine');
  const emailLine = document.getElementById('inviteUserEmail');
  const emailInput = document.getElementById('inviteEmailInput');
  const otpInput = document.getElementById('inviteOtpInput');
  status.classList.remove('ok', 'error');
  if (!sb) {
    status.classList.add('error');
    status.textContent = '登录服务暂不可用，请稍后再试。';
    return null;
  }
  const { data: { session } } = await sb.auth.getSession();
  inviteSession = session || null;
  const isLoginOnly = document.getElementById('inviteModal')?.dataset?.loginOnly === '1';
  if (inviteSession?.user?.email) {
    if (googleSection) googleSection.style.display = 'none';
    form.style.display = 'none';
    userLine.classList.add('shown');
    emailLine.textContent = `已登录：${inviteSession.user.email}`;
    emailInput.value = inviteSession.user.email;
    otpInput.value = '';
    otpInput.placeholder = '已验证';
    otpInput.disabled = true;
    status.classList.add('ok');
    status.textContent = '点击确认进入对话。';
  } else {
    if (googleSection) googleSection.style.display = '';
    form.style.display = 'grid';
    userLine.classList.remove('shown');
    otpInput.disabled = false;
    otpInput.placeholder = '验证码';
    status.textContent = isLoginOnly ? '输入邮箱获取验证码以登录。' : '输入邮箱获取验证码，再填写邀请码。';
  }
  return inviteSession;
}

let inviteSendCooldown = 0;

/* ── 输入框状态工具 ────────────────────────────────────────── */
function setInputState(input, state) {
  input.classList.remove('error', 'success');
  input.removeAttribute('aria-invalid');
  if (state === 'error') {
    input.classList.add('error');
    input.setAttribute('aria-invalid', 'true');
  } else if (state === 'success') {
    input.classList.add('success');
  }
}

function clearInputState(input) {
  input.classList.remove('error', 'success');
  input.removeAttribute('aria-invalid');
}

/* ── 邮箱格式校验 ────────────────────────────────────────── */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
function validateEmail(email) {
  return EMAIL_RE.test(email);
}

/* ── OTP 格式校验（4-8 位纯数字） ─────────────────────────── */
function validateOtp(token) {
  return /^\d{4,8}$/.test(token);
}

async function sendInviteLoginCode() {
  const emailInput = document.getElementById('inviteEmailInput');
  const status = document.getElementById('inviteAuthStatus');
  const button = document.getElementById('inviteLoginBtn');
  const email = emailInput.value.trim();
  status.classList.remove('ok', 'error');
  clearInputState(emailInput);

  if (!email || !validateEmail(email)) {
    status.classList.add('error');
    status.textContent = '请输入有效的邮箱地址。';
    setInputState(emailInput, 'error');
    emailInput.focus({ preventScroll: true });
    return;
  }
  if (!sb) return;

  // 冷却计时防刷
  if (inviteSendCooldown > 0) {
    status.classList.add('error');
    status.textContent = `请 ${inviteSendCooldown} 秒后再试。`;
    return;
  }

  button.disabled = true;
  button.textContent = '发送中';
  localStorage.setItem('archer_auth_return_to', `${webAuthOrigin()}/index.html?auth=1`);
  const { error } = await sb.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: `${webAuthOrigin()}/auth.html?return_to=${encodeURIComponent('/index.html?auth=1')}` }
  });
  if (error) {
    status.classList.add('error');
    status.textContent = error.message || '发送失败，请稍后再试。';
    setInputState(emailInput, 'error');
    button.disabled = false;
    button.textContent = '发送验证码';
    return;
  }
  status.classList.add('ok');
  status.textContent = '验证码已发送，请查收邮件。';
  setInputState(emailInput, 'success');

  // 60 秒冷却倒计时
  inviteSendCooldown = 60;
  button.disabled = true;
  const tick = () => {
    inviteSendCooldown--;
    if (inviteSendCooldown <= 0) {
      button.disabled = false;
      button.textContent = '重新发送';
      return;
    }
    button.textContent = `${inviteSendCooldown}s`;
    setTimeout(tick, 1000);
  };
  button.textContent = '60s';
  setTimeout(tick, 1000);
}

async function verifyInviteEmailCode() {
  const emailInput = document.getElementById('inviteEmailInput');
  const otpInput = document.getElementById('inviteOtpInput');
  const email = emailInput.value.trim();
  const token = otpInput.value.trim().replace(/\s/g, '');
  const status = document.getElementById('inviteAuthStatus');
  const submitBtn = document.getElementById('inviteSubmitBtn');
  status.classList.remove('ok', 'error');
  clearInputState(emailInput);
  clearInputState(otpInput);

  if (!email || !validateEmail(email)) {
    status.classList.add('error');
    status.textContent = '请输入有效的邮箱地址。';
    setInputState(emailInput, 'error');
    emailInput.focus({ preventScroll: true });
    return null;
  }
  if (!token) {
    status.classList.add('error');
    status.textContent = '请输入邮箱验证码。';
    setInputState(otpInput, 'error');
    otpInput.focus({ preventScroll: true });
    return null;
  }
  if (!validateOtp(token)) {
    status.classList.add('error');
    status.textContent = '验证码为 4-8 位数字。';
    setInputState(otpInput, 'error');
    otpInput.focus({ preventScroll: true });
    return null;
  }
  if (!sb) return null;
  submitBtn.disabled = true;
  submitBtn.textContent = '验证中…';
  const { data, error } = await sb.auth.verifyOtp({ email, token, type: 'email' });
  submitBtn.disabled = false;
  submitBtn.textContent = '确认';
  if (error) {
    status.classList.add('error');
    status.textContent = error.message || '验证码不正确或已过期。';
    setInputState(otpInput, 'error');
    return null;
  }
  inviteSession = data.session || null;
  if (inviteSession?.user?.email) localStorage.setItem('archer_account_email', inviteSession.user.email);
  setInputState(otpInput, 'success');
  await refreshInviteAuth();
  return inviteSession;
}

async function openInviteModal() {
  const modal = document.getElementById('inviteModal');
  const dialog = modal.querySelector('.invite-dialog');
  const input = document.getElementById('inviteInput');
  const error = document.getElementById('inviteError');
  const inviteNote = modal.querySelector('.invite-request-note');
  const emailInput = document.getElementById('inviteEmailInput');
  const otpInput = document.getElementById('inviteOtpInput');
  modal.dataset.loginOnly = '1';
  input.style.display = 'none';
  if (inviteNote) inviteNote.style.display = 'none';
  // 重置输入框状态
  clearInputState(emailInput);
  clearInputState(otpInput);
  emailInput.value = '';
  otpInput.value = '';
  // 重置冷却
  inviteSendCooldown = 0;
  const sendBtn = document.getElementById('inviteLoginBtn');
  sendBtn.disabled = false;
  sendBtn.textContent = '发送验证码';
  modal.classList.add('shown');
  modal.setAttribute('aria-hidden', 'false');
  dialog.classList.remove('request-mode');
  document.getElementById('inviteRequest').classList.remove('shown');
  error.textContent = '';
  error.classList.remove('ok');
  await refreshInviteAuth();
  setTimeout(() => {
    emailInput?.focus({ preventScroll: true });
  }, 80);
}

function closeInviteModal() {
  const modal = document.getElementById('inviteModal');
  modal.classList.remove('shown');
  modal.setAttribute('aria-hidden', 'true');
  modal.querySelector('.invite-dialog')?.classList.remove('request-mode');
}

function enterArcherChat() {
  openLiveChat();
}

function enterSoulUpdateFlow() {
  const state = loadSoulState();
  const depth = soulDepth(state);
  if (state.initialComplete && depth < 50) {
    startDeepFlow();
  } else if (depth >= 50) {
    showDeepComplete();
  } else {
    startSoulFlow();
  }
}

async function enterArcherChatWithGate() {
  const { data: { session } } = sb ? await sb.auth.getSession() : { data: { session: null } };
  if (session) {
    enterArcherChat();
  } else {
    openInviteModal();
  }
}

function hideFlowPanels() {
  document.getElementById('returnGate')?.classList.remove('shown');
  document.getElementById('returnGate')?.setAttribute('aria-hidden', 'true');
  document.getElementById('soulReview')?.classList.remove('shown');
  document.getElementById('soulReview')?.setAttribute('aria-hidden', 'true');
  document.getElementById('endingView')?.classList.remove('shown');
  document.getElementById('deepCheckpoint')?.classList.remove('shown');
  document.getElementById('sceneChat')?.classList.remove('shown');
  document.getElementById('thresholdView')?.classList.remove('shown');
}

function enterFlowShell() {
  document.body.classList.add('ritual-on');
  document.getElementById('voidStage')?.classList.add('shown');
  [
    '.logo-wrap', '.brand', '.title', '.subtitle', '.actions',
    '.site-mark', '.theme-toggle', '.flow-layer',
    '.float-layer', '.noise', '.site-footer', '.progress-note'
  ].forEach(sel => {
    const el = document.querySelector(sel);
    if (!el) return;
    el.style.opacity = '0';
    el.style.pointerEvents = 'none';
  });
}

function showReturnGate() {
  enterFlowShell();
  syncSoulForChat();
  hideFlowPanels();
  const state = loadSoulState();
  const depth = soulDepth(state);
  const gate = document.getElementById('returnGate');
  const title = document.getElementById('returnGateTitle');
  const text = document.getElementById('returnGateText');
  const improveBtn = document.getElementById('returnImproveSoulBtn');
  const pinpoint = document.getElementById('voidPinpoint');

  if (depth >= 50) {
    title.textContent = '完整 Soul 已生成';
    text.innerHTML = '你已经完成了五十问。<br>现在可以开始聊天，或重新回答 Soul。';
    improveBtn.textContent = '更新 Soul';
  } else {
    title.textContent = 'Soul 已生成';
    text.innerHTML = '你已经完成了基础十问。<br>现在可以开始聊天，或重新回答 Soul。';
    improveBtn.textContent = '完善 Soul';
  }

  const revealGate = () => {
    gate.classList.add('shown');
    gate.setAttribute('aria-hidden', 'false');
  };

  if (pinpoint.classList.contains('lit')) {
    pinpoint.classList.remove('dispersing');
    pinpoint.classList.add('handoff');
    setTimeout(() => {
      pinpoint.classList.remove('lit', 'handoff');
    }, 950);
    setTimeout(revealGate, 420);
  } else {
    revealGate();
  }
}

function showSoulReview() {
  hideFlowPanels();
  const review = document.getElementById('soulReview');
  document.getElementById('soulReviewBody').textContent = buildSoulMarkdown();
  review.classList.add('shown');
  review.setAttribute('aria-hidden', 'false');
}

function restartSoulFlow() {
  const ok = window.confirm('重新回答会清空当前本地 Soul 进度，并从头开始。确定继续吗？');
  if (!ok) return;
  RESET_KEYS.forEach((key) => localStorage.removeItem(key));
  hideFlowPanels();
  startSoulFlow();
}

function setHomeProgress() {
  const state = loadSoulState();
  const depth = soulDepth(state);
  const btn = document.querySelector('.btn-enter');
  const note = document.getElementById('homeProgressNote');
  if (!btn || !note) return;

  btn.textContent = '进入 Archer';
  note.textContent = state.initialComplete ? (depth >= 50 ? '完整 Soul 已生成' : `Soul 深度 ${depth}/50`) : '';
}

setHomeProgress();

// ════════════════════════════════════════════
// 唤醒仪式 v2 —— 圆环的呼吸、绽放与隐没
// ════════════════════════════════════════════
//
// 节奏设计：
//   A. 充能       0.0 — 0.5s   按钮按下，圆环光晕骤亮
//   B. 周遭隐去   0.5 — 2.3s   全场淡出，只剩圆环（含 brand 文字）
//   C. 圆环绽放   2.3 — 4.0s   圆环放大盛开 + 光晕扩散
//   D. 缓缓旋转   4.0 — 7.0s   保持放大态，悠长旋转
//   E. 凝聚收缩   7.0 — 9.5s   边转边缩，向中心退去
//   F. 余烬消散   9.5 —10.8s   缩成光点，光晕收敛
//   G. 静默       10.8—12.3s  纯黑场，什么都不做
//   H. 跳转       12.3s
//
// 总长 ~12.3s。比之前慢一倍，但每一段都有戏。
// ════════════════════════════════════════════
(function () {
  const btn = document.querySelector('.btn-enter');

  function runEntryRitual(trigger, nextStep = enterSoulUpdateFlow) {
    if (ritualActive) return;
    ritualActive = true;
    document.body.classList.add('ritual-on');

    // 冻结视差
    scene.style.setProperty('--mx', '0px');
    scene.style.setProperty('--my', '0px');

    const logoWrap = document.querySelector('.logo-wrap');
    const ringWrap = document.querySelector('.ring-wrap');
    const ringBase = document.querySelector('.ring-base');
    const ringShine = document.querySelector('.ring-shine');
    const aurora = document.querySelector('.aurora');
    const pinpoint = document.getElementById('voidPinpoint');
    pinpoint.classList.remove('lit', 'dispersing', 'handoff');

    // 临时停掉 logoWrap 的视差跟随，避免动画期间被 transform 干扰
    logoWrap.style.transform = 'none';
    logoWrap.style.opacity = '1';

    // ───────── A. 文字淡出，背景保持原样 ─────────
    trigger.style.transition = 'transform 0.4s ease, opacity 0.4s ease';
    trigger.style.transform  = 'scale(0.94)';
    ringWrap.style.transition = 'filter 0.5s ease';
    ringWrap.style.filter = [
      'drop-shadow(0 -8px 34px rgba(77,217,212,0.88))',
      'drop-shadow(0 12px 42px rgba(245,97,42,0.70))',
      'drop-shadow(0  0  62px rgba(30,123,232,0.42))'
    ].join(' ');

    setTimeout(() => {
      const fadeTargets = [
        '.brand', '.title', '.subtitle', '.actions',
        '.site-mark', '.theme-toggle', '.flow-layer',
        '.float-layer', '.noise', '.site-footer', '.progress-note'
      ];
      fadeTargets.forEach(sel => {
        const el = document.querySelector(sel);
        if (!el) return;
        el.style.transition = 'opacity 1.25s cubic-bezier(0.65, 0, 0.35, 1)';
        el.style.opacity = '0';
        el.style.pointerEvents = 'none';
      });
    }, 180);

    // ───────── B. 圆环缓缓放大 ─────────
    setTimeout(() => {
      logoWrap.style.transition = 'transform 1.85s cubic-bezier(0.22, 1, 0.36, 1)';
      logoWrap.style.transform = 'scale(1.55)';
      ringWrap.style.transition = 'filter 1.85s cubic-bezier(0.22, 1, 0.36, 1)';
      ringWrap.style.filter = [
        'drop-shadow(0 -10px 62px rgba(77,217,212,0.82))',
        'drop-shadow(0 16px 80px rgba(245,97,42,0.60))',
        'drop-shadow(0  0  110px rgba(30,123,232,0.38))',
        'drop-shadow(0  0  150px rgba(245,200,66,0.18))'
      ].join(' ');
      ringBase.style.animationDuration = '6s';
      ringShine.style.animationDuration = '6s';
    }, 850);

    // ───────── C. 旋转着慢慢缩小 ─────────
    setTimeout(() => {
      logoWrap.style.transition = 'transform 2.25s cubic-bezier(0.55, 0, 0.45, 1), opacity 2.25s ease';
      logoWrap.style.transform = 'scale(0.05) rotate(300deg)';
      logoWrap.style.opacity = '0.18';
      ringWrap.style.transition = 'filter 2.25s cubic-bezier(0.55, 0, 0.45, 1)';
      ringWrap.style.filter = [
        'drop-shadow(0 0 24px rgba(255,255,255,0.95))',
        'drop-shadow(0 0 44px rgba(77,217,212,0.58))',
        'drop-shadow(0 0 72px rgba(245,200,66,0.18))'
      ].join(' ');
    }, 2700);

    // ───────── D. 露出白光，进入交互层 ─────────
    setTimeout(() => {
      const voidStage = document.getElementById('voidStage');
      voidStage.classList.add('shown');
      pinpoint.classList.remove('dispersing', 'handoff');
      pinpoint.classList.add('lit');
      logoWrap.style.transition = 'opacity 0.7s ease-out';
      logoWrap.style.opacity = '0';
      ringWrap.style.filter = 'drop-shadow(0 0 12px rgba(255,255,255,0.4))';
      aurora.style.transition = 'opacity 1.1s ease';
      aurora.style.opacity = 'var(--aurora-op)';
    }, 5000);

    setTimeout(() => {
      ritualActive = false;
      nextStep();
    }, 6100);
  }

  btn.addEventListener('click', function (e) {
    e.preventDefault();
    if (loadSoulState().initialComplete || soulDepth() >= 50) {
      showReturnGate();
      return;
    }
    runEntryRitual(btn, startSoulFlow);
  });
})();

// ════════════════════════════════════════════
// 后续流程：Soul 创建 → 八问 → 终章
// ════════════════════════════════════════════
const sleep = ms => new Promise(r => setTimeout(r, ms));

const $void     = document.getElementById('voidStage');
const $pinpoint = document.getElementById('voidPinpoint');
const $sceneSoul     = document.getElementById('sceneSoul');
const $sceneChat     = document.getElementById('sceneChat');
const $threshold     = document.getElementById('thresholdView');
const $ending        = document.getElementById('endingView');
const $deepCheckpoint = document.getElementById('deepCheckpoint');
const $deepCheckpointDepth = document.getElementById('deepCheckpointDepth');
const $miniRing      = document.getElementById('chatMiniRing');
const $chatTopbar    = document.querySelector('#sceneChat .chat-topbar');
const $silenceHint   = document.getElementById('silenceHint');

// ──────── Soul 创建：一次一问 ────────
const soulSteps = $sceneSoul.querySelectorAll('.soul-step');
const $soulContinue = document.getElementById('soulContinueBtn');
let currentSoulStep = -1;
const soulAnswers = { ...(loadSoulState().soulAnswers || {}) };

async function startSoulFlow() {
  // 光点散开成场景
  $pinpoint.classList.add('dispersing');
  await sleep(600);

  $sceneSoul.classList.add('shown');
  await sleep(400);

  goToSoulStep(0);
}

function goToSoulStep(idx) {
  soulSteps.forEach((el, i) => {
    if (i === idx) {
      el.classList.remove('leaving');
      el.classList.add('shown');
      const input = el.querySelector('[data-soul-input]');
      if (input) {
        setTimeout(() => input.focus({ preventScroll: true }), 700);
      }
    } else if (i === currentSoulStep) {
      el.classList.remove('shown');
      el.classList.add('leaving');
    } else {
      el.classList.remove('shown', 'leaving');
    }
  });
  currentSoulStep = idx;
  $soulContinue.classList.remove('shown');

  const input = soulSteps[idx].querySelector('[data-soul-input]');
  if (input) {
    const onInput = () => {
      if (input.value.trim().length > 0) $soulContinue.classList.add('shown');
      else $soulContinue.classList.remove('shown');
    };
    input.removeEventListener('input', input._archerOnInput || (() => {}));
    input._archerOnInput = onInput;
    input.addEventListener('input', onInput);

    const onKey = (e) => {
      if (e.key === 'Enter' && input.value.trim().length > 0) {
        e.preventDefault();
        soulNext();
      }
    };
    input.removeEventListener('keydown', input._archerOnKey || (() => {}));
    input._archerOnKey = onKey;
    input.addEventListener('keydown', onKey);
  }
}

// Step 0 的"好"按钮
document.querySelectorAll('[data-soul-next]').forEach(btn => {
  btn.addEventListener('click', () => soulNext());
});
$soulContinue.addEventListener('click', () => soulNext());

async function soulNext() {
  const cur = soulSteps[currentSoulStep];
  const input = cur.querySelector('[data-soul-input]');
  if (input) {
    soulAnswers[currentSoulStep] = input.value.trim();
    saveSoulState({ soulAnswers });
  }

  if (currentSoulStep < soulSteps.length - 1) {
    goToSoulStep(currentSoulStep + 1);
  } else {
    // Soul 完成 → 进入 threshold
    $soulContinue.classList.remove('shown');
    soulSteps.forEach(s => { s.classList.remove('shown'); s.classList.add('leaving'); });
    await sleep(900);
    $sceneSoul.classList.remove('shown');

    // 短暂的光点重燃
    $pinpoint.classList.remove('dispersing');
    await sleep(50);
    $pinpoint.classList.add('lit');
    await sleep(1600);

    // 光点散开 → threshold 出现
    $pinpoint.classList.add('dispersing');
    await sleep(400);
    $threshold.classList.add('shown');
  }
}

// ──────── Threshold ────────
document.getElementById('thresholdStartBtn').addEventListener('click', async () => {
  $threshold.classList.remove('shown');
  await sleep(1100);
  startChat();
});
document.getElementById('thresholdWaitBtn').addEventListener('click', async () => {
  $threshold.classList.remove('shown');
  await sleep(800);
  // 简单回到首页：刷新
  location.reload();
});

// ──────── 十问对话 ────────
// 结构走向：外在可见 → 内在不可见 → 行动出口
//   1. 踏实时刻（入口）
//   2. 在乎但藏起的事（第一层防御）
//   3. 想暂时放下的负担
//   4. 关系里的期待
//   5. 说「我没事」时的真实感觉（内在声音） ← 沉默问
//   6. 让自己疲惫的标准（自我施压）
//   7. 不用证明时的自由想象
//   8. 照见陌生自己的瞬间
//   9. 反复出现却没说出口的念头
//   10. 今晚能落地的一件小事（行动出口）
//
// 文案说明：不用 <br> 强制换行，让浏览器根据屏宽自然换行
const initialQuestions = [
  {
    n: '第 一 问',
    q: '最近一次让你觉得踏实的，是哪个时刻？',
    hint: '一个画面，一段时间，或一句话',
  },
  {
    n: '第 二 问',
    q: '有没有一件事，你说不在乎，其实还放在心上？',
    hint: '可以模糊一点，但尽量诚实',
  },
  {
    n: '第 三 问',
    q: '如果现在能先放下一件事，你最想放下什么？',
    hint: '一件事，一个人，或一种状态',
  },
  {
    n: '第 四 问',
    q: '那个你最在意的人，你希望他怎样看见你？',
    hint: '不需要写他是谁',
  },
  {
    n: '第 五 问',
    q: '最近一次说「我没事」时，你心里真正的感觉是什么？',
    hint: '说给现在的自己听',
    silentAfter: true,   // 沉默问挪到这里
  },
  {
    n: '第 六 问',
    q: '哪一个你给自己的标准，已经让你累了很久？',
    hint: '一个动作、一个数字，或一种身份',
  },
  {
    n: '第 七 问',
    q: '如果明天不用再证明自己，你醒来后想先做什么？',
    hint: '从睁开眼那一刻开始想',
  },
  {
    n: '第 八 问',
    q: '有没有一个瞬间，你忽然觉得自己有点陌生？',
    hint: '写那个瞬间，或只写那个感觉',
  },
  {
    n: '第 九 问',
    q: '有没有一个反复出现的念头，你一直没有说出口？',
    hint: '如果不想说完整，说一半也可以',
  },
  {
    n: '第 十 问',
    q: '这场对话之后，今晚你想为自己做哪件小事？',
    hint: '小到今晚就能做完',
  },
];

const deepQuestions = [
  { id: 11, theme: 'origin', intensity: 2, q: '你小时候最常被误解的是什么？', hint: '一个称呼、一件事，或一种感觉' },
  { id: 12, theme: 'origin', intensity: 1, q: '你小时候最常被夸的是什么？', hint: '一句评价，或一个反复出现的场景' },
  { id: 13, theme: 'origin', intensity: 1, q: '你现在身上，有哪一点其实很早就出现了？', hint: '一个习惯、一个反应，或一种天性' },
  { id: 14, theme: 'origin', intensity: 2, q: '有哪句话，你到现在还会在心里反复听见？', hint: '可以是别人说的，也可以是你对自己说的' },
  { id: 15, theme: 'origin', intensity: 3, q: '你从什么时候开始，学会隐藏自己的某一部分？', hint: '一个年龄、一段关系，或一件事' },
  { id: 16, theme: 'origin', intensity: 3, q: '你最熟悉的一种委屈是什么？', hint: '那种感觉通常怎么出现' },
  { id: 17, theme: 'origin', intensity: 2, q: '你最不想变成哪种大人？', hint: '一个样子，或一种生活方式' },
  { id: 18, theme: 'origin', intensity: 2, q: '你身上有哪一点，是你慢慢争取回来的？', hint: '一种能力、自由，或表达方式' },
  { id: 19, theme: 'origin', intensity: 2, q: '如果给过去的自己留一句话，你会说什么？', hint: '说给那个时候的你听' },
  { id: 20, theme: 'origin', intensity: 1, q: '你希望 Archer 记住你早年的哪一个画面？', hint: '一个很小的画面也可以' },

  { id: 21, theme: 'relation', intensity: 1, q: '你最容易被哪种人吸引？', hint: '一种气质、状态，或相处方式' },
  { id: 22, theme: 'relation', intensity: 2, q: '你最容易被哪种人消耗？', hint: '不用写具体是谁' },
  { id: 23, theme: 'relation', intensity: 3, q: '你在关系里最怕发生什么？', hint: '一个场景，或一种结局' },
  { id: 24, theme: 'relation', intensity: 1, q: '你通常怎样判断一个人是否值得靠近？', hint: '一个细节、动作，或长期感受' },
  { id: 25, theme: 'relation', intensity: 2, q: '你最想被别人理解的，是哪一部分？', hint: '可以是不常说出口的那部分' },
  { id: 26, theme: 'relation', intensity: 2, q: '当你开始疏远一个人，通常是因为什么？', hint: '一个信号，或一次失望' },
  { id: 27, theme: 'relation', intensity: 3, q: '你有没有一种关系模式，反复出现过？', hint: '只写你观察到的循环就好' },
  { id: 28, theme: 'relation', intensity: 2, q: '你希望别人怎样对待你的脆弱？', hint: '一种语气、距离，或陪伴方式' },
  { id: 29, theme: 'relation', intensity: 2, q: '你最难开口提出的需求是什么？', hint: '一个请求，或一句一直没说的话' },
  { id: 30, theme: 'relation', intensity: 1, q: '如果关系可以更轻一点，你想先放下什么？', hint: '期待、证明、担心，或别的东西' },

  { id: 31, theme: 'desire', intensity: 1, q: '你羡慕别人时，通常在羡慕什么？', hint: '一种生活、一个状态，或一个选择' },
  { id: 32, theme: 'desire', intensity: 3, q: '你有一个一直不敢认真承认的愿望吗？', hint: '可以只说一半' },
  { id: 33, theme: 'desire', intensity: 1, q: '如果不考虑现实压力，你会把时间花在哪里？', hint: '一件事、一个地方，或一种节奏' },
  { id: 34, theme: 'desire', intensity: 1, q: '你想要的生活里，最不可缺少的感觉是什么？', hint: '一个词，或一句话' },
  { id: 35, theme: 'desire', intensity: 2, q: '你现在追求的东西，有多少真的是你想要的？', hint: '不需要精确，只说直觉' },
  { id: 36, theme: 'desire', intensity: 2, q: '你最怕自己浪费掉什么？', hint: '时间、天赋、关系，或别的东西' },
  { id: 37, theme: 'desire', intensity: 1, q: '有哪件事，你明明喜欢，却总是推迟？', hint: '小事也可以' },
  { id: 38, theme: 'desire', intensity: 2, q: '如果未来一年只改变一件事，你希望是哪件？', hint: '尽量具体一点' },
  { id: 39, theme: 'desire', intensity: 2, q: '你想成为的人，身上最重要的三个词是什么？', hint: '三个词就够' },
  { id: 40, theme: 'desire', intensity: 2, q: '你愿意为那个未来的自己，先付出什么？', hint: '一个行动、代价，或承诺' },

  { id: 41, theme: 'self', intensity: 1, q: '你什么时候最像真正的自己？', hint: '一个场景，或一种状态' },
  { id: 42, theme: 'self', intensity: 2, q: '你什么时候最不像自己？', hint: '那个时候你通常在扮演什么' },
  { id: 43, theme: 'self', intensity: 1, q: '你的身体最常用什么方式提醒你：够了？', hint: '疲惫、疼痛、失眠，或别的信号' },
  { id: 44, theme: 'self', intensity: 1, q: '你最近最需要的一种休息是什么？', hint: '不是应该休息，而是真的需要' },
  { id: 45, theme: 'self', intensity: 2, q: '你希望 Archer 在你低落时怎么陪你？', hint: '安静、提醒、提问，或别的方式' },
  { id: 46, theme: 'self', intensity: 2, q: '你希望 Archer 在你逃避时怎么提醒你？', hint: '温柔一点，还是直接一点' },
  { id: 47, theme: 'self', intensity: 1, q: '你最想保留的一个习惯是什么？', hint: '一个让你更像自己的习惯' },
  { id: 48, theme: 'self', intensity: 2, q: '你最想慢慢戒掉的一个习惯是什么？', hint: '不用批判自己，只描述它' },
  { id: 49, theme: 'self', intensity: 2, q: '你希望自己的 Soul 一年后变成什么样？', hint: '一个方向，或一种气质' },
  { id: 50, theme: 'self', intensity: 3, fixed: true, q: '如果 Archer 只能永远记住一句关于你的话，那句话是什么？', hint: '一句你希望它永远不要忘记的话' },
];

const $qNumber       = document.getElementById('qNumber');
const $questionText  = document.getElementById('questionText');
const $myAnswer      = document.getElementById('myAnswer');
const $chatStage     = document.querySelector('#sceneChat .chat-stage');
const $chatInputWrap = document.getElementById('chatInputWrap');
const $chatTextarea  = document.getElementById('chatTextarea');
const $chatSendBtn   = document.getElementById('chatSendBtn');
const $keyboardQuestion = document.getElementById('keyboardQuestion');

let qIdx = 0;
const chatAnswers = [...(loadSoulState().initialAnswers || [])];
let activeQuestions = initialQuestions;
let chatMode = 'initial';
let activeDeepBatch = [];
let isAnswerSubmitting = false;
const isTouchViewport = () => window.matchMedia('(max-width: 700px), (pointer: coarse)').matches;

function updateKeyboardOffset() {
  if (!window.visualViewport) {
    scene.style.setProperty('--keyboard-bottom', '0px');
    return 0;
  }
  const viewport = window.visualViewport;
  const keyboardBottom = Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop);
  scene.style.setProperty('--keyboard-bottom', `${Math.round(keyboardBottom)}px`);
  return keyboardBottom;
}

function setKeyboardOpen(open) {
  const keyboardBottom = updateKeyboardOffset();
  const shouldOpen = open && isTouchViewport();
  scene.classList.toggle('keyboard-open', shouldOpen);
  requestAnimationFrame(resizeChatTextarea);
  if (!shouldOpen && keyboardBottom <= 0) {
    scene.style.setProperty('--keyboard-bottom', '0px');
    requestAnimationFrame(positionChatInput);
  }
}

function positionChatInput() {
  if (!window.matchMedia('(max-width: 900px)').matches && !isTouchViewport()) return;
  if (scene.classList.contains('keyboard-open')) return;
  if (!$questionText.classList.contains('shown') || !$chatInputWrap.classList.contains('shown')) return;

  const questionRect = $questionText.getBoundingClientRect();
  const inputHeight = $chatInputWrap.offsetHeight || 112;
  const gap = isTouchViewport() ? 34 : 46;
  const bottomRoom = isTouchViewport() ? 44 : 72;
  const minTop = questionRect.bottom + gap;
  const maxTop = window.innerHeight - inputHeight - bottomRoom;
  const top = Math.max(0, Math.min(minTop, maxTop));

  scene.style.setProperty('--chat-input-top', `${Math.round(top)}px`);
}

function resizeChatTextarea() {
  const maxHeight = scene.classList.contains('keyboard-open') ? 142 : 176;
  $chatTextarea.style.height = 'auto';
  const nextHeight = Math.min($chatTextarea.scrollHeight, maxHeight);
  $chatTextarea.style.height = `${nextHeight}px`;
  $chatTextarea.style.overflowY = $chatTextarea.scrollHeight > maxHeight ? 'auto' : 'hidden';
  positionChatInput();
}

function questionLabel(item, index) {
  if (chatMode === 'deep') {
    const state = loadSoulState();
    const answered = uniqueDeepAnswers(state).length;
    return `Soul 深度 ${Math.min(50, 10 + answered + 1)}/50`;
  }
  return item.n || `第 ${index + 1} 问`;
}

function shuffle(list) {
  const arr = [...list];
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

function buildDeepQueue() {
  const fixed = deepQuestions.find(q => q.fixed);
  const pools = {
    origin: shuffle(deepQuestions.filter(q => q.theme === 'origin' && !q.fixed)),
    relation: shuffle(deepQuestions.filter(q => q.theme === 'relation' && !q.fixed)),
    desire: shuffle(deepQuestions.filter(q => q.theme === 'desire' && !q.fixed)),
    self: shuffle(deepQuestions.filter(q => q.theme === 'self' && !q.fixed)),
  };
  const themes = Object.keys(pools);
  const queue = [];

  while (themes.some(theme => pools[theme].length)) {
    const last = queue[queue.length - 1];
    const options = themes.filter(theme => {
      if (!pools[theme].length) return false;
      if (last && last.theme === theme) return false;
      if (last && last.intensity >= 3 && pools[theme][0].intensity >= 3) return false;
      return true;
    });
    const fallback = themes.filter(theme => pools[theme].length && (!last || last.theme !== theme));
    const source = options.length ? options : fallback.length ? fallback : themes.filter(theme => pools[theme].length);
    const theme = source[Math.floor(Math.random() * source.length)];
    queue.push(pools[theme].shift());
  }

  return fixed ? [...queue, fixed].map(q => q.id) : queue.map(q => q.id);
}

function getDeepQueue(state = loadSoulState()) {
  if (Array.isArray(state.deepQueue) && state.deepQueue.length) return state.deepQueue;
  const deepQueue = buildDeepQueue();
  saveSoulState({ deepQueue, deepAnswers: uniqueDeepAnswers(state) });
  return deepQueue;
}

function getDeepBatch() {
  const state = loadSoulState();
  const queue = getDeepQueue(state);
  const answeredIds = new Set(uniqueDeepAnswers(state).map(item => item.id));
  const ids = queue.filter(id => !answeredIds.has(id)).slice(0, 5);
  return ids.map(id => deepQuestions.find(q => q.id === id)).filter(Boolean);
}

async function startChat() {
  chatMode = 'initial';
  activeQuestions = initialQuestions;
  $sceneChat.classList.add('shown');
  $miniRing.classList.add('shown');
  qIdx = 0;
  await sleep(400);
  await showQuestion(qIdx);
}

async function showQuestion(idx) {
  const item = activeQuestions[idx];
  const { q, hint } = item;

  $qNumber.textContent = questionLabel(item, idx);
  $questionText.innerHTML = q;
  $keyboardQuestion.textContent = q.replace(/<br\s*\/?>/gi, ' ');
  $myAnswer.textContent = '';
  $chatStage.classList.remove('answer-review');
  $myAnswer.classList.remove('shown', 'leaving');
  $myAnswer.style.display = 'none';
  $questionText.classList.remove('shown', 'leaving');

  // 题号
  $qNumber.classList.add('shown');
  await sleep(chatMode === 'deep' ? 300 : 500);

  // 问题
  $questionText.classList.add('shown');
  await sleep(chatMode === 'deep' ? 550 : 900);

  // 输入区 + 针对性 placeholder
  $chatInputWrap.classList.remove('leaving');
  $chatInputWrap.classList.add('shown');
  $chatTextarea.value = '';
  $chatTextarea.placeholder = '';
  resizeChatTextarea();
  if (!isTouchViewport()) {
    $chatTextarea.focus({ preventScroll: true });
  }
}

async function handleAnswer() {
  if (isAnswerSubmitting) return;
  const val = $chatTextarea.value.trim();
  if (!val) return;
  isAnswerSubmitting = true;
  $chatSendBtn.disabled = true;

  const currentQuestion = activeQuestions[qIdx];
  const { silentAfter } = currentQuestion;
  if (chatMode === 'deep') {
    const state = loadSoulState();
    const deepAnswers = uniqueDeepAnswers(state);
    const answer = {
      id: currentQuestion.id,
      theme: currentQuestion.theme,
      q: currentQuestion.q,
      a: val
    };
    const existingIndex = deepAnswers.findIndex(item => item.id === currentQuestion.id);
    if (existingIndex >= 0) {
      deepAnswers[existingIndex] = answer;
    } else {
      deepAnswers.push(answer);
    }
    saveSoulState({ deepAnswers, initialComplete: true });
  } else {
    chatAnswers.push({ q: currentQuestion.q, a: val });
    saveSoulState({ initialAnswers: chatAnswers });
  }

  // 隐藏输入区
  $chatInputWrap.classList.remove('shown');
  $chatInputWrap.classList.add('leaving');
  $chatTextarea.blur();

  // 不再同时展示“问题 + 回答”，避免两段文字在同一区域重叠。
  // 回答已保存，当前问题保持居中并自然淡出。
  $chatStage.classList.remove('answer-review');
  $myAnswer.textContent = '';
  $myAnswer.style.display = 'none';
  await sleep(chatMode === 'deep' ? 220 : 360);

  $questionText.classList.add('leaving');
  $qNumber.classList.remove('shown');

  await sleep(chatMode === 'deep' ? 700 : 900);

  if (silentAfter) {
    // ── 沉默问：第五问之后 ──
    // 圆环落到屏幕中部，保留呼吸感；品牌字淡出，降低视觉噪音
    $chatTopbar.classList.add('descended');
    await sleep(1600); // 等圆环落位

    // 记录状态浮现
    $silenceHint.classList.add('shown');

    // 停 6 秒
    await sleep(6000);

    // 提示淡出
    $silenceHint.classList.remove('shown');
    await sleep(1100);

    // topbar 回到顶部
    $chatTopbar.classList.remove('descended');
    await sleep(1700);
  } else {
    // 普通过渡（约 4s 总长）：
    // 答案停留 1.2s + 淡出 1.1s + 这里 1.5s ≈ 3.8s
    $miniRing.classList.add('thinking');
    await sleep(chatMode === 'deep' ? 700 : (qIdx === 0 ? 1500 : 700));
    $miniRing.classList.remove('thinking');
  }

  qIdx++;
  if (qIdx < activeQuestions.length) {
    await showQuestion(qIdx);
  } else if (chatMode === 'deep') {
    await endDeepBatch();
  } else {
    await endChat();
  }
  isAnswerSubmitting = false;
  $chatSendBtn.disabled = false;
}

$chatSendBtn.addEventListener('click', handleAnswer);
$chatTextarea.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    handleAnswer();
  }
});
$chatTextarea.addEventListener('input', () => {
  resizeChatTextarea();
});
$chatTextarea.addEventListener('focus', () => setKeyboardOpen(true));
$chatTextarea.addEventListener('blur', () => setKeyboardOpen(false));
if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', () => {
    const keyboardLikelyOpen = updateKeyboardOffset() > 120;
    setKeyboardOpen(document.activeElement === $chatTextarea && keyboardLikelyOpen);
  });
  window.visualViewport.addEventListener('scroll', () => {
    if (document.activeElement === $chatTextarea) setKeyboardOpen(true);
  });
}
window.addEventListener('resize', positionChatInput);

document.getElementById('liveChatHomeBtn').addEventListener('click', closeLiveChat);
document.getElementById('liveNewChatBtn').addEventListener('click', () => startWorkspaceThread('first'));
document.getElementById('liveSidebarToggle').addEventListener('click', () => {
  document.querySelector('.live-chat-card')?.classList.toggle('sidebar-open');
});
document.querySelectorAll('.conversation-item').forEach((button) => {
  button.addEventListener('click', () => startWorkspaceThread(button.dataset.thread));
});
document.querySelectorAll('.bg-choice').forEach((button) => {
  button.addEventListener('click', () => setWorkspaceBackground(button.dataset.bg || 'deep'));
});
document.getElementById('workspaceLoginBtn').addEventListener('click', () => {
  closeLiveChat();
  setTimeout(() => openInviteModal(), 300);
});
document.getElementById('workspaceImproveSoulBtn').addEventListener('click', async () => {
  closeLiveChat();
  await sleep(300);
  enterSoulUpdateFlow();
});
document.getElementById('workspaceDownloadSoulBtn').addEventListener('click', downloadSoulMarkdown);
document.getElementById('workspaceExportSoulJsonBtn').addEventListener('click', downloadSoulJson);
document.getElementById('workspaceDesktopBtn').addEventListener('click', showDesktopNotice);
document.getElementById('workspaceTerminalBtn').addEventListener('click', showTerminalNotice);
setWorkspaceBackground(localStorage.getItem('archer-web-bg') || 'deep');
document.getElementById('liveChatSendBtn').addEventListener('click', sendLiveChat);
document.getElementById('liveChatInput').addEventListener('input', (event) => {
  const input = event.currentTarget;
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 138) + 'px';
});
document.getElementById('liveChatInput').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendLiveChat();
  }
});
document.getElementById('returnStartChatBtn').addEventListener('click', () => {
  // 优先使用 web trial 聊天，降低转化摩擦
  enterArcherChat();
});
document.getElementById('returnImproveSoulBtn').addEventListener('click', async () => {
  restartSoulFlow();
});
document.getElementById('soulReviewBackBtn').addEventListener('click', showReturnGate);
document.getElementById('soulRestartBtn').addEventListener('click', restartSoulFlow);

// ──────── 终章 ────────
async function endChat() {
  $sceneChat.classList.remove('shown');
  $miniRing.classList.remove('shown');
  saveSoulState({
    initialComplete: true,
    soulAnswers,
    initialAnswers: chatAnswers
  });
  await sleep(1200);
  $ending.classList.add('shown');

  // 让圆环和文字先被看见，再浮出分叉选择
  await sleep(900);
  const $choice = document.querySelector('.ending-choice');
  if ($choice) $choice.classList.add('shown');
}

async function startDeepFlow() {
  activeDeepBatch = getDeepBatch();
  if (!activeDeepBatch.length) {
    await showDeepComplete();
    return;
  }

  chatMode = 'deep';
  activeQuestions = activeDeepBatch;
  qIdx = 0;

  $ending.classList.remove('shown');
  $endingChoice.classList.remove('shown', 'hidden');
  $endingFarewell.classList.remove('shown');
  $deepCheckpoint.classList.remove('shown');
  $sceneSoul.classList.remove('shown');
  $threshold.classList.remove('shown');
  $pinpoint.classList.add('dispersing');
  $sceneChat.classList.add('shown');
  $miniRing.classList.add('shown');
  $chatTopbar.classList.remove('descended');
  $silenceHint.classList.remove('shown');

  await sleep(500);
  await showQuestion(qIdx);
}

async function endDeepBatch() {
  $sceneChat.classList.remove('shown');
  $miniRing.classList.remove('shown');
  await sleep(800);

  const depth = soulDepth();
  if (depth >= 50) {
    await showDeepComplete();
    return;
  }

  $deepCheckpointDepth.textContent = `Soul 深度 ${depth}/50`;
  $deepCheckpoint.classList.add('shown');
}

async function showDeepComplete() {
  $deepCheckpoint.classList.remove('shown');
  $sceneChat.classList.remove('shown');
  $miniRing.classList.remove('shown');
  await sleep(700);
  syncSoulForChat();
  $ending.classList.add('shown');
  document.querySelector('.ending-title').textContent = '五十问已尽';
  document.querySelector('.ending-text').innerHTML = 'Archer 已经拥有一份更完整的你。<br>你的完整 Soul 已生成。';
  $endingChoice.classList.add('hidden');
  $endingChoice.classList.remove('shown');
  $endingFarewell.classList.remove('compact');
  await sleep(1200);
  $endingFarewell.classList.add('shown');
}

// ── 分叉按钮 ──
const $endingChoice   = document.querySelector('.ending-choice');
const $endingFarewell = document.getElementById('endingFarewell');

// 继续深入：进入深度 Soul，每次 5 问
document.getElementById('endingContinueBtn').addEventListener('click', async () => {
  $endingChoice.classList.remove('shown');
  $endingChoice.classList.add('hidden');
  await sleep(500);
  startDeepFlow();
});

// 先到这里：保存基础 Soul，返回首页后再给“开始聊天 / 更新 Soul”
document.getElementById('endingStopBtn').addEventListener('click', async () => {
  $endingChoice.classList.remove('shown');
  $endingChoice.classList.add('hidden');
  await sleep(800);
  $endingFarewell.classList.remove('compact');
  $endingFarewell.classList.add('shown');
});

document.getElementById('deepContinueBtn').addEventListener('click', async () => {
  $deepCheckpoint.classList.remove('shown');
  await sleep(700);
  startDeepFlow();
});

document.getElementById('deepSaveBtn').addEventListener('click', async () => {
  $deepCheckpoint.classList.remove('shown');
  await sleep(700);
  document.querySelector('.ending-title').textContent = '已保存';
  document.querySelector('.ending-text').innerHTML = `Soul 深度 ${soulDepth()}/50。<br>你可以随时回来继续。`;
  $ending.classList.add('shown');
  $endingChoice.classList.add('hidden');
  $endingChoice.classList.remove('shown');
  $endingFarewell.classList.add('compact');
  $endingFarewell.classList.add('shown');
});

// 返回首页：保留当前 Soul 进度，只回到入口状态
document.getElementById('endingHomeBtn').addEventListener('click', () => {
  location.reload();
});

document.getElementById('endingStartChatBtn').addEventListener('click', () => {
  // 优先使用 web trial 聊天，降低转化摩擦
  // auth 升级入口放在侧栏"登录使用完整版"按钮中
  enterArcherChat();
});

document.getElementById('inviteSubmitBtn').addEventListener('click', async () => {
  const error = document.getElementById('inviteError');
  const submitBtn = document.getElementById('inviteSubmitBtn');
  const emailInput = document.getElementById('inviteEmailInput');
  const otpInput = document.getElementById('inviteOtpInput');

  // 未登录：先验证邮箱+验证码
  if (!inviteSession) {
    const email = emailInput.value.trim();
    const otp = otpInput.value.trim().replace(/\s/g, '');
    error.classList.remove('ok');

    if (!email || !validateEmail(email)) {
      error.textContent = '请先输入有效的邮箱地址。';
      setInputState(emailInput, 'error');
      emailInput.focus({ preventScroll: true });
      return;
    }
    if (!otp) {
      error.textContent = '请先输入邮箱验证码。';
      setInputState(otpInput, 'error');
      otpInput.focus({ preventScroll: true });
      return;
    }
    // 走 verifyInviteEmailCode 流程
    const session = await verifyInviteEmailCode();
    if (!session?.user) return;
    inviteSession = session;
  }

  if (!inviteSession?.user) {
    error.classList.remove('ok');
    error.textContent = '请先完成邮箱验证再继续。';
    return;
  }
  submitBtn.disabled = true;
  submitBtn.textContent = '进入中…';
  error.classList.add('ok');
  error.textContent = '验证通过 ✓';
  setTimeout(() => {
    submitBtn.disabled = false;
    submitBtn.textContent = '确认';
    window.location.href = 'archer.html?entry=invite#chat';
  }, 600);
});

document.getElementById('inviteInput').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    document.getElementById('inviteSubmitBtn').click();
  } else if (event.key === 'Escape') {
    closeInviteModal();
  }
});

document.getElementById('inviteBackBtn').addEventListener('click', closeInviteModal);
document.getElementById('inviteLoginBtn').addEventListener('click', sendInviteLoginCode);

// 邮箱输入框：Enter 发送验证码 + blur 实时校验 + input 清除错误
const _inviteEmailInput = document.getElementById('inviteEmailInput');
_inviteEmailInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    sendInviteLoginCode();
  }
});
_inviteEmailInput.addEventListener('blur', () => {
  const v = _inviteEmailInput.value.trim();
  if (v && !validateEmail(v)) {
    setInputState(_inviteEmailInput, 'error');
  } else if (v && validateEmail(v)) {
    setInputState(_inviteEmailInput, 'success');
  }
});
_inviteEmailInput.addEventListener('input', () => {
  clearInputState(_inviteEmailInput);
  const status = document.getElementById('inviteAuthStatus');
  if (status.classList.contains('error') && status.textContent.includes('邮箱')) {
    status.classList.remove('error');
    status.textContent = '';
  }
});

// OTP 输入框：Enter 确认 + input 清除错误
const _inviteOtpInput = document.getElementById('inviteOtpInput');
_inviteOtpInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    document.getElementById('inviteSubmitBtn').click();
  }
});
_inviteOtpInput.addEventListener('input', () => {
  clearInputState(_inviteOtpInput);
  const status = document.getElementById('inviteAuthStatus');
  if (status.classList.contains('error') && (status.textContent.includes('验证码') || status.textContent.includes('4-8'))) {
    status.classList.remove('error');
    status.textContent = '';
  }
});
document.getElementById('inviteLogoutBtn').addEventListener('click', async () => {
  if (sb) await sb.auth.signOut();
  inviteSession = null;
  refreshInviteAuth();
});

document.getElementById('inviteGoogleBtn').addEventListener('click', async () => {
  if (!sb) return;
  const btn = document.getElementById('inviteGoogleBtn');
  const btnText = document.getElementById('inviteGoogleBtnText');
  btn.disabled = true;
  btnText.textContent = '正在跳转…';
  const origin = webAuthOrigin();
  localStorage.setItem('archer_auth_return_to', `${origin}/archer.html?entry=invite`);
  const { error } = await sb.auth.signInWithOAuth({
    provider: 'google',
    options: { redirectTo: `${origin}/auth.html` }
  });
  if (error) {
    btn.disabled = false;
    btnText.textContent = '使用 Google 账号登录';
    localStorage.removeItem('archer_auth_return_to');
    document.getElementById('inviteAuthStatus').classList.add('error');
    document.getElementById('inviteAuthStatus').textContent = 'Google 登录暂时不可用，请使用邮箱验证码。';
  }
});

if (new URLSearchParams(location.search).get('auth') === '1') {
  openInviteModal();
  history.replaceState(null, '', location.pathname);
}

document.getElementById('inviteModal').addEventListener('click', (event) => {
  if (event.target.id === 'inviteModal') closeInviteModal();
});
