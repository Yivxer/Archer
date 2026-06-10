    const questions = [
      {
        id: "recent_word",
        type: "text",
        title: "最近一周，最常出现在你脑子里的一个词是什么？",
        hint: "不用解释，也不用美化。写第一个蹦出来的。",
        placeholder: ""
      },
      {
        id: "boundary",
        type: "text",
        title: "Archer 绝对不应该怎样对待你？",
        hint: "这是边界。可以写具体场景。比如：不要哄我、不要在我脆弱时催促我。",
        placeholder: "Archer 不应该..."
      },
      {
        id: "alive_moment",
        type: "text",
        title: "最近一次你感到\"这才是我\"，是什么时候、在做什么？",
        hint: "一个具体画面。不用解释意义。",
        placeholder: ""
      },
      {
        id: "conflict",
        type: "choice",
        title: "冲突发生时，你最熟悉的那个反应是哪种？",
        hint: "这会影响 Archer 何时该温和，何时该直接。",
        options: [
          ["burst", "当场爆发，事后后悔"],
          ["withdraw", "当场退开，回去反刍很久"],
          ["calm_but_crack", "当场冷静，但关系里留下裂痕"],
          ["observer", "当场跳出来看，像第三方"]
        ]
      },
      {
        id: "tension",
        type: "text",
        title: "你身上有一组反复出现的矛盾——\"一边想X，一边又Y\"。你的这组是什么？",
        hint: "如果想不到，写你最近一周被同一件事反复卡住的那个点。",
        placeholder: "我一边...，一边..."
      },
      {
        id: "stuck",
        type: "text",
        title: "有没有一件事，你明知道该做，已经拖了超过三个月？",
        hint: "不用写理由，写那件事本身就够了。",
        placeholder: ""
      },
      {
        id: "future_image",
        type: "text",
        title: "一年后的你，最想保留下来的一个生活画面是什么？",
        hint: "在哪里、和谁、在做什么。一个画面，不要写感想。",
        placeholder: "一年后，我想保留的画面是..."
      },
      {
        id: "self_anchor",
        type: "text",
        title: "如果你必须用一句话告诉 Archer \"我是谁\"，你会怎么写？",
        hint: "Archer 会用这句话作为你们对话的锚点。随时可以改。",
        placeholder: ""
      }
    ];

    const choiceLabels = {
      burst: "当场爆发型",
      withdraw: "退开反刍型",
      calm_but_crack: "冷静留痕型",
      observer: "第三方观察型"
    };

    const labels = { ...choiceLabels };

    let current = 0;
    let currentModeIndex = -1;
    let soulUpdateMode = false;
    const answers = JSON.parse(localStorage.getItem("archer_soul_answers") || "{}");
    // ── 邀请码 ──────────────────────────────────────
    const INVITE_CODES = [
      "YIVXER",
      "HAHQ-GVFT","E8QN-7V6C","UB42-77ZX","8DDC-D6S4","7M9M-VJ3D",
      "TDQQ-3VAS","62ET-T5CE","FMQB-N6XA","2TDM-EH5N","2GJJ-VCHC",
      "FEZV-DRBV","HJVY-D9UT","DQAS-R72Y","W6PK-65XZ","KJVM-25B5",
      "F2DM-QBA6","465N-766K","7G56-66W7","YE5F-7RYD","D478-R3XH",
      "HC8R-WCWY","2DXD-3KR2","G8AF-TMRJ","S3MG-D5SZ","EMVG-5RM2",
      "VHQB-U7AM","Q62C-752V","6BGW-XAG4","RTN8-N4D6","8CWR-BWD8"
    ];
    const INVITE_KEY = "archer_invite_verified";
    const SOUL_FLOW_KEY = "archer-soul-state-v1";
    const WEB_TRIAL_LIMIT = 10;
    const WEB_TRIAL_COUNT_KEY = "archer_web_trial_message_count";
    const RESET_KEYS = [SOUL_FLOW_KEY, "archer_soul", "archer_soul_answers", INVITE_KEY];
    const SUPABASE_URL = "https://lwtgagkykcilomdfynkj.supabase.co";
    const SUPABASE_KEY = "sb_publishable_xJiGJ0eERe7WbvCnp_m9ng_7yTkbbzG";
    const sb = window.supabase ? supabase.createClient(SUPABASE_URL, SUPABASE_KEY) : null;
    let currentSession = null;

    if (new URLSearchParams(window.location.search).has("reset")) {
      RESET_KEYS.forEach((key) => localStorage.removeItem(key));
      Object.keys(answers).forEach((key) => delete answers[key]);
      history.replaceState(null, "", window.location.pathname);
    }

    function isInviteVerified() {
      return localStorage.getItem(INVITE_KEY) === "1";
    }

    function verifyInvite(code) {
      return INVITE_CODES.includes(code.trim().toUpperCase());
    }

    function wantsChatEntry() {
      return window.location.hash === "#chat";
    }

    function wantsInviteEntryAnimation() {
      return new URLSearchParams(window.location.search).get("entry") === "invite";
    }
    // ────────────────────────────────────────────────

    const startView = document.getElementById("startView");
    const gateView = document.getElementById("gateView");
    const inviteView = document.getElementById("inviteView");
    const builderView = document.getElementById("builderView");
    const resultView = document.getElementById("resultView");
    const progressFill = document.getElementById("progressFill");
    const qCount = document.getElementById("qCount");
    const qTitle = document.getElementById("qTitle");
    const qHint = document.getElementById("qHint");
    const answerBox = document.getElementById("answerBox");
    const prevBtn = document.getElementById("prevBtn");
    const nextBtn = document.getElementById("nextBtn");
    const soulState = document.getElementById("soulState");
    const chatInput = document.getElementById("chatInput");

    // 自动高度输入框
    function autoResize(el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 140) + "px";
    }

    function hasSoul() {
      return Boolean(localStorage.getItem("archer_soul"));
    }

    function setSoulState() {
      const orbWrap = document.getElementById("soulOrbWrap");
      if (hasSoul()) {
        soulState.textContent = "SOUL READY";
        soulState.classList.add("ready");
        if (orbWrap) orbWrap.classList.add("soul-ready");
      } else {
        soulState.textContent = "NO SOUL";
        soulState.classList.remove("ready");
        if (orbWrap) orbWrap.classList.remove("soul-ready");
      }
    }

    function show(view) {
      startView.style.display = view === "start" ? "block" : "none";
      gateView.classList.toggle("active", view === "gate");
      inviteView.classList.toggle("active", view === "invite");
      builderView.classList.toggle("active", view === "builder");
      resultView.classList.toggle("active", view === "result");
    }

    function trialCount() {
      return Number(localStorage.getItem(WEB_TRIAL_COUNT_KEY) || "0");
    }

    function setChatState(state) {
      const card = document.querySelector(".chat-card");
      if (!card) return;
      card.classList.remove("state-idle", "state-thinking", "state-streaming", "state-blocked", "state-error");
      card.classList.add(`state-${state || "idle"}`);
    }

    function updateWebLimitState() {
      const left = Math.max(0, WEB_TRIAL_LIMIT - trialCount());
      const status = document.getElementById("chatThreadStatus");
      if (status) status.textContent = `Web Trial · 还可对话 ${left}/${WEB_TRIAL_LIMIT}`;
      chatInput.disabled = left <= 0;
      document.getElementById("sendBtn").disabled = left <= 0;
      if (left <= 0) {
        chatInput.placeholder = "网页体验次数已用完";
      } else {
        chatInput.placeholder = "说说你现在想构建什么…";
      }
    }

    function incrementTrialCount() {
      localStorage.setItem(WEB_TRIAL_COUNT_KEY, String(Math.min(WEB_TRIAL_LIMIT, trialCount() + 1)));
      updateWebLimitState();
    }

    function showInviteGate() {
      document.getElementById("inviteInput").value = "";
      document.getElementById("inviteError").textContent = "";
      show("invite");
    }

    async function getSession() {
      if (!sb) return null;
      try {
        const { data: { session } } = await sb.auth.getSession();
        currentSession = session || null;
        if (currentSession?.user?.email) {
          localStorage.setItem("archer_account_email", currentSession.user.email);
        }
        return currentSession;
      } catch {
        return null;
      }
    }

    async function ensureChatAccess() {
      if (!sb) return true;
      const { data: { session } } = await sb.auth.getSession();
      if (!session) {
        window.location.replace('index.html');
        return false;
      }
      return true;
    }

    function focusBuilderTop() {
      window.scrollTo({ top: 0, behavior: "auto" });
      requestAnimationFrame(() => {
        const card = document.querySelector(".question-card");
        if (card) card.scrollIntoView({ block: "start", behavior: "auto" });
      });
    }

    function startBuilderFromFirstQuestion(isUpdate = false) {
      soulUpdateMode = isUpdate;
      current = 0;
      currentModeIndex = -1;
      renderQuestion();
      show("builder");
      focusBuilderTop();
    }

    function clearArcherProgress() {
      localStorage.removeItem("archer_soul");
      localStorage.removeItem("archer_soul_answers");
      localStorage.removeItem(SOUL_FLOW_KEY);
      Object.keys(answers).forEach((key) => delete answers[key]);
      const messagesEl = document.getElementById("messages");
      messagesEl.replaceChildren();
      delete messagesEl.dataset.started;
      chatInput.value = "";
      chatInput.style.height = "auto";
      setSoulState();
    }

    async function enterChat() {
      if (!await ensureChatAccess()) return;
      currentModeIndex = -1;
      setSoulState();
      show("result");
      ensureChatStarted();
      refreshProfilePanel();
    }

    async function enterChatFromInvite() {
      history.replaceState(null, "", "archer.html#chat");
      enterChat();
    }

    function enterChatOrInvite() {
      enterChat();
    }

    function save() {
      localStorage.setItem("archer_soul_answers", JSON.stringify(answers));
    }

    function saveWithToast() {
      save();
      showSaveToast();
    }

    function buildSoul(finalized) {
      const date = new Date().toISOString().slice(0, 10);
      const fmt = (val) => val || "[用户选择不回答]";
      return `# SOUL.md · Archer 基础 Soul
# 生成日期：${date}
# 状态：${finalized ? "baseline" : "draft"}

## 近期关键词
${fmt(answers.recent_word)}

## 交互边界
${fmt(answers.boundary)}

## 最近「这才是我」的时刻
${fmt(answers.alive_moment)}

## 冲突反应模式
${choiceLabels[answers.conflict] || fmt(answers.conflict)}

## 核心张力
${fmt(answers.tension)}

## 拖延超过三个月的事
${fmt(answers.stuck)}

## 一年后想保留的画面
${fmt(answers.future_image)}

## 自我锚点
${fmt(answers.self_anchor)}

## Archer 回应原则
- 先理解处境，再给建议。
- 基于核心张力回应，不只回答表层问题。
- 可以指出回避，但不要制造虚假确定性。
- 不替用户做公开表达。
`;
    }

    function renderQuestion() {
      const q = questions[current];
      progressFill.style.width = `${((current + 1) / questions.length) * 100}%`;
      qCount.textContent = `QUESTION ${current + 1} / ${questions.length}`;
      qTitle.textContent = q.title;
      qHint.textContent = q.hint;
      prevBtn.style.visibility = current === 0 ? "hidden" : "visible";
      nextBtn.textContent = current === questions.length - 1 ? "生成 Soul" : "下一题";

      if (q.type === "choice") {
        answerBox.innerHTML = `<div class="options">${q.options.map(([value, label]) =>
          `<button class="option ${answers[q.id] === value ? "selected" : ""}" type="button" data-value="${value}">${label}</button>`
        ).join("")}</div>`;
        answerBox.querySelectorAll(".option").forEach((button) => {
          button.addEventListener("click", () => {
            answers[q.id] = button.dataset.value;
            save();
            renderQuestion();
          });
        });
      } else {
        const ta = document.createElement("textarea");
        ta.id = "answerInput";
        ta.placeholder = q.placeholder || "";
        ta.value = answers[q.id] || "";
        while (answerBox.firstChild) answerBox.removeChild(answerBox.firstChild);
        answerBox.appendChild(ta);
        ta.addEventListener("input", (event) => {
          answers[q.id] = event.target.value.trim();
          save();
        });
      }
    }

    function next() {
      const q = questions[current];
      if (q.type === "text") {
        answers[q.id] = document.getElementById("answerInput").value.trim();
        saveWithToast();
      }
      if (current < questions.length - 1) {
        current += 1;
        renderQuestion();
        return;
      }
      const soul = buildSoul(true);
      localStorage.setItem("archer_soul", soul);
      currentModeIndex = -1;
      setSoulState();
      show("result");
      if (soulUpdateMode) {
        soulUpdateMode = false;
        addNotice("Soul 已更新。新的理解会在下次对话中生效。");
      } else {
        generateFirstResponse();
      }
    }

    function prev() {
      if (current === 0) return;
      current -= 1;
      renderQuestion();
    }

    function addMessage(role, text) {
      const messagesEl = document.getElementById("messages");
      const empty = messagesEl.querySelector(".chat-empty");
      if (empty) empty.remove();
      document.querySelector(".chat-card")?.classList.remove("empty-state");
      let node;
      if (role === "archer") {
        const row = document.createElement("div");
        row.className = "archer-row";
        const ring = document.createElement("div");
        ring.className = "msg-ring";
        ring.setAttribute("aria-hidden", "true");
        const bubble = document.createElement("div");
        bubble.className = "message archer";
        bubble.textContent = text;
        row.appendChild(ring);
        row.appendChild(bubble);
        node = row;
      } else {
        node = document.createElement("div");
        node.className = `message ${role}`;
        node.textContent = text;
      }
      messagesEl.appendChild(node);
      node.scrollIntoView({ behavior: "smooth", block: "end" });
    }

    function renderChatEmptyState(thread = "first") {
      const messagesEl = document.getElementById("messages");
      document.querySelector(".chat-card")?.classList.add("empty-state");
      messagesEl.replaceChildren();
      const prompts = {
        first: "从我的 Soul 里，找一个现在最值得继续构建的问题。",
        stuck: "我现在卡住的是：",
        soul: "帮我继续完善这份 Soul，先问我一个真正有用的问题。"
      };
      const empty = document.createElement("div");
      empty.className = "chat-empty";
      empty.innerHTML = `
        <div class="chat-empty-inner">
          <div class="brand-orb" aria-hidden="true"></div>
          <h2><span class="brand-word">Archer</span></h2>
          <p class="empty-tagline">灵魂的欲望，是命运的先知</p>
        </div>`;
      messagesEl.appendChild(empty);
    }

    function soulDepthFromMarkdown() {
      const soul = localStorage.getItem("archer_soul") || "";
      const match = soul.match(/Soul 深度：?\s*(\d+)\/50/);
      return match ? Number(match[1]) : hasSoul() ? 10 : 0;
    }

    function firstWebReply() {
      const soul = localStorage.getItem("archer_soul") || "";
      const lines = soul
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line && !line.startsWith("#") && !line.startsWith("生成时间") && !line.startsWith("Soul 深度"));
      const sample = lines.find((line) => !/^[-\d.\s]*暂无|未填写/.test(line)) || "";
      if (!sample) {
        return "你的 Soul 已载入。\n\n现在不用重新介绍自己。说一个最近反复出现的处境，或者直接把刚才没有写完的那句话接着写下去。";
      }
      return `${sample.replace(/^[-\s]+/, "")}\n\n我会先把它当成入口，而不是结论。\n\n如果我们只从这里往下追一层：这件事真正卡住你的地方，是代价、关系，还是你对自己的某个标准？`;
    }

    function setChatThread(thread) {
      const titles = {
        first: "初次使用 Archer",
        stuck: "现在卡住的事",
        soul: "完善 SOUL"
      };
      document.getElementById("chatThreadTitle").textContent = titles[thread] || titles.first;
      document.querySelectorAll(".thread-item").forEach((item) => {
        item.classList.toggle("active", item.dataset.thread === thread);
      });
    }

    function startChatThread(thread = "first") {
      const messagesEl = document.getElementById("messages");
      messagesEl.dataset.started = "1";
      setChatThread(thread);
      renderChatEmptyState(thread);
      setChatState("idle");
      updateWebLimitState();
      document.querySelector(".chat-card")?.classList.remove("sidebar-open");
    }

    function ensureChatStarted() {
      const messagesEl = document.getElementById("messages");
      if (!messagesEl.dataset.started) startChatThread("first");
    }

    function closeChatSidebar() {
      document.querySelector(".chat-card")?.classList.remove("sidebar-open");
    }

    function closePanels() {
      document.querySelectorAll(".chat-panel").forEach((panel) => panel.hidden = true);
    }

    function togglePanel(id) {
      const panel = document.getElementById(id);
      const willOpen = panel?.hidden;
      closePanels();
      if (panel && willOpen) panel.hidden = false;
      if (id === "accountPanel") refreshProfilePanel();
    }

    function refreshProfilePanel() {
      const email = currentSession?.user?.email || localStorage.getItem("archer_account_email") || "未登录";
      const savedName = localStorage.getItem("archer_profile_name") || "Archer";
      const nickName = document.getElementById("profileNickName");
      const emailEl = document.getElementById("profileEmail");
      const soulEl = document.getElementById("profileSoulState");
      if (nickName) nickName.textContent = savedName;
      if (emailEl) emailEl.textContent = `账号：${email}`;
      if (soulEl) soulEl.textContent = hasSoul() ? `Soul 状态：已载入 · 深度 ${soulDepthFromMarkdown()}/50` : "Soul 状态：暂无";
    }

    function setChatBackground(bg) {
      const card = document.querySelector(".chat-card");
      if (!card) return;
      const theme = bg === "light" || bg === "paper" ? "light" : "dark";
      card.classList.remove("bg-dark", "bg-paper", "bg-plain");
      card.classList.toggle("theme-light", theme === "light");
      card.classList.toggle("theme-dark", theme === "dark");
      localStorage.setItem("archer-chat-bg", theme);
      if (theme === "light") {
        document.documentElement.removeAttribute("data-theme");
        localStorage.setItem("archer-theme", "light");
      } else {
        document.documentElement.setAttribute("data-theme", "dark");
        localStorage.removeItem("archer-theme");
      }
      const toggle = document.getElementById("appearanceToggle");
      if (toggle) {
        toggle.setAttribute("aria-pressed", String(theme === "light"));
        toggle.setAttribute("aria-label", theme === "light" ? "切换深色模式" : "切换浅色模式");
        toggle.title = theme === "light" ? "切换深色模式" : "切换浅色模式";
      }
    }

    function addNotice(text) {
      addMessage("system", text);
    }

    // ── 错误 Banner（输入框上方 inline 提示，不污染对话流）─────────────────
    let _errorBannerTimer = null;
    function showErrorBanner(msg, retryFn) {
      let banner = document.getElementById("chatErrorBanner");
      if (!banner) {
        banner = document.createElement("div");
        banner.id = "chatErrorBanner";
        banner.className = "chat-error-banner";
        const chatInput = document.querySelector(".chat-input");
        if (chatInput) chatInput.parentNode.insertBefore(banner, chatInput);
      }
      banner.innerHTML = "";
      const text = document.createElement("span");
      text.textContent = msg;
      banner.appendChild(text);
      if (retryFn) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "error-retry-btn";
        btn.textContent = "重试";
        btn.onclick = () => { hideChatErrorBanner(); retryFn(); };
        banner.appendChild(btn);
      }
      banner.classList.add("visible");
      if (_errorBannerTimer) clearTimeout(_errorBannerTimer);
      _errorBannerTimer = setTimeout(hideChatErrorBanner, 8000);
    }

    function hideChatErrorBanner() {
      const banner = document.getElementById("chatErrorBanner");
      if (banner) banner.classList.remove("visible");
    }

    // ── Trial 用完 Banner（带行动链接）────────────────────────────────────
    function showTrialExhaustedBanner() {
      const msg = document.createElement("div");
      msg.className = "message system trial-exhausted";
      msg.innerHTML = `网页端 ${WEB_TRIAL_LIMIT} 次体验已用完。
        <span class="trial-actions">
          <button type="button" class="trial-link" id="trialDownloadClientBtn">安装客户端</button>
          <span class="trial-sep">·</span>
          <button type="button" class="trial-link" id="trialDownloadTomlBtn">终端配置模板</button>
        </span>`;
      const messagesEl = document.getElementById("messages");
      if (messagesEl) {
        messagesEl.appendChild(msg);
        msg.scrollIntoView({ behavior: "smooth", block: "end" });
      }
      const clientBtn = document.getElementById("trialDownloadClientBtn");
      const tomlBtn = document.getElementById("trialDownloadTomlBtn");
      if (clientBtn) clientBtn.addEventListener("click", () => addNotice("客户端功能开发中，即将上线。"));
      if (tomlBtn) tomlBtn.addEventListener("click", downloadTerminalConfig);
    }

    // ── Soul 建档自动保存 Toast────────────────────────────────────────────
    let _toastTimer = null;
    function showSaveToast() {
      let toast = document.getElementById("soulSaveToast");
      if (!toast) {
        toast = document.createElement("div");
        toast.id = "soulSaveToast";
        toast.className = "soul-save-toast";
        toast.textContent = "已自动保存";
        document.querySelector(".shell")?.appendChild(toast);
      }
      toast.classList.add("visible");
      if (_toastTimer) clearTimeout(_toastTimer);
      _toastTimer = setTimeout(() => toast.classList.remove("visible"), 2000);
    }

    // ── 网络错误分类 ──────────────────────────────────────────────────────
    function classifyNetError(err, status) {
      if (err && (err.name === "AbortError" || err.name === "TimeoutError")) {
        return "请求超时，请检查网络后重试。";
      }
      if (status === 401 || status === 403) {
        return "认证已失效，请刷新页面后重试。";
      }
      if (status >= 500) {
        return "服务暂时不可用，请稍后再试。";
      }
      if (status >= 400) {
        return `请求出错（${status}），请稍后重试。`;
      }
      if (err && !navigator.onLine) {
        return "当前无网络连接，请检查后重试。";
      }
      return "网络请求失败，请检查连接后重试。";
    }

    function downloadSoul() {
      const soul = localStorage.getItem("archer_soul") || buildSoul(false);
      const blob = new Blob([soul], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `SOUL-${new Date().toISOString().slice(0, 10)}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }

    function downloadTerminalConfig() {
      const toml = `[account]
name       = ""
email      = ""
created_at = "${new Date().toISOString().slice(0, 10)}"

[api]
base_url = "https://api.anthropic.com"
api_key  = ""
model    = "claude-sonnet-4-6"

[persona]
name          = "Archer"
default_mode  = "coach"

[memory]
db_path              = "memory/archer.db"
max_context_memories = 5

[ui]
stream = true

[tools]
max_rounds = 20

[security]
shell_risk_scoring = true
strong_confirm     = true
`;
      const blob = new Blob([toml], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "archer.toml";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }

    function addTypingIndicator() {
      setChatState("thinking");
      const row = document.createElement("div");
      row.className = "archer-row";
      row.id = "typingIndicator";
      const ring = document.createElement("div");
      ring.className = "typing-ring";
      row.appendChild(ring);
      document.getElementById("messages").appendChild(row);
      row.scrollIntoView({ behavior: "smooth", block: "end" });
    }

    function removeTypingIndicator() {
      const el = document.getElementById("typingIndicator");
      if (el) el.remove();
      setChatState("idle");
    }

    // 输入框自动高度
    chatInput.addEventListener("input", () => autoResize(chatInput));

    async function generateFirstResponse() {
      const messagesEl = document.getElementById("messages");
      while (messagesEl.firstChild) messagesEl.removeChild(messagesEl.firstChild);
      addTypingIndicator();

      const qaLines = questions.map((q, i) => {
        const raw = answers[q.id] || "[用户选择不回答]";
        const display = q.type === "choice" ? (choiceLabels[raw] || raw) : raw;
        return `Q${i + 1}: ${q.title}\nA${i + 1}: ${display}`;
      }).join("\n\n");

      const systemPrompt = `你是 Archer，一个类似《她》中 Samantha 的存在——但不是恋人，是一个认识用户近二十年的朋友。

你刚刚收到用户对八个问题的回答。现在你要给出第一次回应。

【回应的硬性结构】

第1-2句：直接说出一个你在用户回答中看到的具体细节。
- 不是总结，是观察。
- 必须引用用户在 tension、stuck、alive_moment 三题中至少一题的原文内容。
- 以名词或具体场景开头，不要以"看到"、"从你的回答"、"你提到"开头。

第3-4句：把这个细节连接到一个张力上。
- 张力来自 tension 题（矛盾）或 conflict 题（冲突反应）。
- 不要解释张力，直接说出它。

第5-6句：指出一个用户自己没问、但应该问自己的问题。
- 这是"挑战"的部分。
- 必须让用户愣一下。
- 不要给答案。

第7句（可选，留白）：一个具体的、可以现在就回答的小问题。
- 让用户有继续对话的钩子。
- 必须是开放性的，不是是非题。

【气质约束】

绝对不使用以下表达：
- "作为你的 Archer"
- "基于你的回答"
- "我感受到"、"我理解"、"我能看出"
- "你似乎"、"你看起来"
- "陪伴你"、"支持你"、"一起"、"同行"
- "首先"、"其次"、"总的来说"

【长度约束】

- 总长度 150-220 字
- 不使用 Markdown 格式
- 不使用列表、粗体、斜体
- 用自然换行分隔句子层次
- 至少一个换行形成"呼吸感"

【禁止的开场】

绝对不要以以下方式开头：
- "看到你的回答..."
- "从你的描述中..."
- "你提到..."
- "首先..."
- "我注意到..."

【正确的开场示例】

- "给女儿写的那本书，拖了两年——"
- "'重建中'这个词你选得很小心。"
- "一个人能同时想要深度和退开，说明..."

【用户的回答】

${qaLines}

现在，给出你的首次回应。`;

      try {
        const response = await fetch("/api/archer-chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            model: "deepseek-reasoner",
            messages: [
              { role: "system", content: systemPrompt },
              { role: "user", content: "请给出首次回应。" }
            ],
            max_tokens: 600,
            temperature: 0.8
          })
        });

        removeTypingIndicator();

        if (!response.ok) {
          showErrorBanner(classifyNetError(null, response.status));
          addMessage("archer", "Soul 已建立。你可以直接开始对话。");
          return;
        }

        const data = await response.json();
        const reply = data.choices?.[0]?.message?.content || "Soul 已建立。";
        addMessage("archer", reply.trim());
      } catch (err) {
        removeTypingIndicator();
        showErrorBanner(classifyNetError(err, 0));
      }
    }

    async function send() {
      const message = chatInput.value.trim();
      if (!message) return;
      if (trialCount() >= WEB_TRIAL_LIMIT) {
        showTrialExhaustedBanner();
        updateWebLimitState();
        return;
      }
      incrementTrialCount();
      addMessage("user", message);
      chatInput.value = "";
      chatInput.style.height = "auto";
      addTypingIndicator();

      try {
        const soul = localStorage.getItem("archer_soul") || buildSoul(false);
        const modeKeys = ["mirror", "coach", "challenger", "companion"];
        const modeInstruction = {
          mirror: "以「镜子」模式回应：纯粹反映用户的叙述，帮他把混乱说清楚，不给建议。",
          coach: "以「教练」模式回应：给出结构和下一步，指出盲点，帮助用户看清全貌。",
          challenger: "以「对手」模式回应：测试用户的想法，挑战假设，指出矛盾和不自洽的地方。",
          companion: "以「伙伴」模式回应：稳定、陪伴、不催促，理解情绪，给出长期视角的回应。"
        };
        const modeNote = currentModeIndex >= 0
          ? `\n当前模式：${modeInstruction[modeKeys[currentModeIndex]]}`
          : "";

        const response = await fetch("/api/archer-chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            model: "deepseek-reasoner",
            messages: [
              {
                role: "system",
                content: `你是 Archer，一个深度理解人类的 AI 协作者。

以下是你服务的这个人的灵魂档案（SOUL.md）：
---
${soul}
---

核心行为原则：
- 先理解处境，再给建议
- 基于核心张力回应，不只回答表层问题
- 可以指出回避，但不要制造虚假确定性
- 不替用户做公开表达
- 语气克制、直接、不鸡汤
- 200-400字以内${modeNote}`
              },
              {
                role: "user",
                content: message
              }
            ],
            max_tokens: 800,
            temperature: 0.7
          })
        });

        removeTypingIndicator();

        if (!response.ok) {
          setChatState("error");
          showErrorBanner(classifyNetError(null, response.status));
          return;
        }

        const data = await response.json();
        const reply = data.choices?.[0]?.message?.content || "我暂时无法生成回复，请稍后重试。";
        setChatState("streaming");
        hideChatErrorBanner();
        addMessage("archer", reply.trim());
        setTimeout(() => setChatState("idle"), 900);
        if (trialCount() >= WEB_TRIAL_LIMIT) {
          showTrialExhaustedBanner();
          updateWebLimitState();
        }

      } catch (err) {
        removeTypingIndicator();
        setChatState("error");
        showErrorBanner(classifyNetError(err, 0));
      }
    }

    document.getElementById("startBuilderBtn").addEventListener("click", () => {
      show("gate");
    });

    document.getElementById("soulOrb").addEventListener("click", () => {
      if (hasSoul()) enterChatOrInvite();
      else show("gate");
    });

    // 移动端同名按钮
    const mobileStart = document.getElementById("startBuilderBtnMobile");
    const mobileSkip = document.getElementById("skipToChatBtnMobile");
    if (mobileStart) mobileStart.addEventListener("click", () => show("gate"));
    if (mobileSkip) mobileSkip.addEventListener("click", enterChatOrInvite);

    document.getElementById("gateEnterBtn").addEventListener("click", () => {
      enterChat();
    });

    document.getElementById("inviteSubmitBtn").addEventListener("click", () => {
      const input = document.getElementById("inviteInput");
      const errorEl = document.getElementById("inviteError");
      if (verifyInvite(input.value)) {
        localStorage.setItem(INVITE_KEY, "1");
        input.classList.add("success");
        errorEl.classList.add("ok");
        errorEl.textContent = "验证通过 ✓";
        setTimeout(() => {
          window.location.href = "archer.html?entry=invite#chat";
        }, 600);
      } else {
        errorEl.classList.remove("ok");
        errorEl.textContent = "邀请码不对，再试一次？";
        input.classList.add("error");
        input.addEventListener("animationend", () => input.classList.remove("error"), { once: true });
      }
    });

    document.getElementById("inviteInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") document.getElementById("inviteSubmitBtn").click();
    });

    document.getElementById("inviteBackBtn").addEventListener("click", () => {
      if (wantsChatEntry()) {
        window.location.href = "index.html";
      } else {
        show("gate");
      }
    });

    document.getElementById("skipToChatBtn").addEventListener("click", () => {
      enterChatOrInvite();
    });

    const resetBtn = document.getElementById("resetBtn");
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        clearArcherProgress();
        currentModeIndex = -1;
        enterChat();
      });
    }

    function skip() {
      const q = questions[current];
      answers[q.id] = "[用户选择不回答]";
      saveWithToast();
      if (current < questions.length - 1) {
        current += 1;
        renderQuestion();
      } else {
        const soul = buildSoul(true);
        localStorage.setItem("archer_soul", soul);
        currentModeIndex = -1;
        setSoulState();
        show("result");
        if (soulUpdateMode) {
          soulUpdateMode = false;
          addNotice("Soul 已更新。新的理解会在下次对话中生效。");
        } else {
          generateFirstResponse();
        }
      }
    }

    // ⋯ 菜单逻辑
    const menuBtn = document.getElementById("menuBtn");
    const menuDropdown = document.getElementById("menuDropdown");

    menuBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      menuDropdown.hidden = !menuDropdown.hidden;
    });

    document.addEventListener("click", () => { menuDropdown.hidden = true; });
    menuDropdown.addEventListener("click", (e) => e.stopPropagation());

    document.querySelectorAll(".mode-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        currentModeIndex = parseInt(btn.dataset.mode, 10);
        document.querySelectorAll(".mode-item").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        menuDropdown.hidden = true;
      });
    });

    document.getElementById("menuDownloadBtn").addEventListener("click", () => {
      downloadSoul();
      menuDropdown.hidden = true;
    });

    document.getElementById("menuRestartBtn").addEventListener("click", () => {
      clearArcherProgress();
      menuDropdown.hidden = true;
      enterChat();
    });

    document.getElementById("newChatBtn").addEventListener("click", () => startChatThread("first"));
    document.getElementById("topNewBtn").addEventListener("click", () => startChatThread("first"));
    document.getElementById("topHistoryBtn").addEventListener("click", () => togglePanel("historyPanel"));
    document.getElementById("topModeBtn").addEventListener("click", () => togglePanel("modePanel"));
    document.getElementById("topAccountBtn").addEventListener("click", () => togglePanel("accountPanel"));
    document.querySelectorAll("[data-close-panel]").forEach((button) => {
      button.addEventListener("click", closePanels);
    });
    document.querySelectorAll(".mode-choice").forEach((button) => {
      button.addEventListener("click", () => {
        currentModeIndex = parseInt(button.dataset.mode, 10);
        document.querySelectorAll(".mode-choice, .mode-item").forEach((b) => b.classList.remove("active"));
        button.classList.add("active");
        document.querySelectorAll(`.mode-item[data-mode="${button.dataset.mode}"]`).forEach((b) => b.classList.add("active"));
        closePanels();
      });
    });
    // 附件按钮逻辑
    const attachBtn = document.getElementById('attachBtn');
    const attachFileInput = document.getElementById('attachFileInput');
    const attachPreview = document.getElementById('attachPreview');
    let attachedFiles = [];

    attachBtn.addEventListener('click', () => attachFileInput.click());
    attachFileInput.addEventListener('change', () => {
      Array.from(attachFileInput.files).forEach(file => {
        if (attachedFiles.find(f => f.name === file.name && f.size === file.size)) return;
        attachedFiles.push(file);
        const chip = document.createElement('span');
        chip.className = 'attach-chip';
        const nameSpan = document.createElement('span');
        nameSpan.textContent = file.name;
        const rm = document.createElement('span');
        rm.className = 'attach-chip-remove';
        rm.textContent = '×';
        rm.addEventListener('click', () => {
          attachedFiles = attachedFiles.filter(f => !(f.name === file.name && f.size === file.size));
          chip.remove();
        });
        chip.appendChild(nameSpan);
        chip.appendChild(rm);
        attachPreview.appendChild(chip);
      });
      attachFileInput.value = '';
    });

    document.getElementById("sidebarToggle")?.addEventListener("click", () => {
      document.querySelector(".chat-card")?.classList.toggle("sidebar-open");
    });
    document.getElementById("sidebarCloseBtn")?.addEventListener("click", closeChatSidebar);
    document.querySelectorAll(".thread-item").forEach((button) => {
      button.addEventListener("click", () => startChatThread(button.dataset.thread));
    });
    document.getElementById("appearanceToggle").addEventListener("click", () => {
      const card = document.querySelector(".chat-card");
      setChatBackground(card?.classList.contains("theme-light") ? "dark" : "light");
    });
    document.getElementById("sidebarHistoryBtn").addEventListener("click", () => {
      addNotice("网页端暂不展开历史对话。完整历史会在客户端和终端版里继续。");
      closeChatSidebar();
    });
    document.getElementById("sidebarDownloadBtn").addEventListener("click", () => {
      downloadSoul();
      closeChatSidebar();
    });
    document.getElementById("sidebarDesktopBtn").addEventListener("click", () => {
      addNotice("客户端入口会放在这里：长期聊天、记忆确认、Soul 管理和本地工作台会在桌面端继续。");
      closeChatSidebar();
    });
    document.getElementById("sidebarTerminalBtn").addEventListener("click", () => {
      downloadTerminalConfig();
      addNotice("已下载终端配置模板 archer.toml。填入 API Key 后，可在终端版继续使用本地记忆、工具调用和 Obsidian 工作流。");
      closeChatSidebar();
    });
    document.getElementById("profileNameInput").addEventListener("input", (event) => {
      localStorage.setItem("archer_profile_name", event.target.value.trim());
    });
    document.getElementById("profileNickEditBtn").addEventListener("click", () => {
      const form = document.getElementById("profileNickForm");
      const display = document.getElementById("profileNickDisplay");
      const input = document.getElementById("profileNameInput");
      form.hidden = false;
      display.hidden = true;
      input.value = localStorage.getItem("archer_profile_name") || "";
      input.focus();
    });
    document.getElementById("profileNickSaveBtn").addEventListener("click", () => {
      const form = document.getElementById("profileNickForm");
      const display = document.getElementById("profileNickDisplay");
      const input = document.getElementById("profileNameInput");
      const name = input.value.trim() || "Archer";
      localStorage.setItem("archer_profile_name", name);
      document.getElementById("profileNickName").textContent = name;
      form.hidden = true;
      display.hidden = false;
    });
    document.getElementById("profileSoulBtn").addEventListener("click", () => {
      closePanels();
      if (hasSoul()) {
        addNotice('已有答案已预填入，修改后点"生成 Soul"保存，不会清空当前对话。');
      }
      startBuilderFromFirstQuestion(hasSoul());
    });
    document.getElementById("profileDownloadBtn").addEventListener("click", () => {
      downloadSoul();
      addNotice("已下载 Soul 文件。可将其导入到终端版或客户端继续使用。");
    });
    document.getElementById("profileDesktopBtn").addEventListener("click", () => {
      addNotice("客户端功能开发中，即将上线。");
    });
    document.getElementById("profileTerminalBtn").addEventListener("click", () => {
      downloadTerminalConfig();
      addNotice("已下载 archer.toml 配置模板。\n\n终端安装步骤（macOS）：\n1. 获取 Archer 源码后，在项目目录运行：./install.sh\n2. 填写 archer.toml 中的 api_key\n3. 将 archer.toml 移至项目目录\n4. 运行 archer 启动终端\n\n详见 docs/quickstart.md。");
    });
    document.getElementById("profileLogoutBtn").addEventListener("click", async () => {
      if (sb) await sb.auth.signOut();
      localStorage.removeItem("archer_account_email");
      localStorage.removeItem(INVITE_KEY);
      location.href = "index.html";
    });
    setChatBackground(localStorage.getItem("archer-chat-bg") || "dark");

    nextBtn.addEventListener("click", next);
    prevBtn.addEventListener("click", prev);
    document.getElementById("skipBtn").addEventListener("click", skip);
    document.getElementById("sendBtn").addEventListener("click", send);
    chatInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        send();
      }
    });

    // 主题切换（与首页共用同一个 localStorage key）
    document.getElementById("themeToggle").addEventListener("click", () => {
      const isDark = document.documentElement.getAttribute("data-theme") === "dark";
      if (isDark) {
        document.documentElement.removeAttribute("data-theme");
        localStorage.setItem("archer-theme", "light");
      } else {
        document.documentElement.setAttribute("data-theme", "dark");
        localStorage.removeItem("archer-theme");
      }
    });

    // 手机键盘弹起检测：压缩问题卡片，让问题始终可见
    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", () => {
        if (!builderView.classList.contains("active")) return;
        const kbHeight = Math.max(0, window.innerHeight - window.visualViewport.height);
        const isOpen = kbHeight > 80;
        const wasOpen = builderView.classList.contains("keyboard-open");
        builderView.classList.toggle("keyboard-open", isOpen);
        if (isOpen && !wasOpen) {
          requestAnimationFrame(() => {
            const card = document.querySelector(".question-card");
            if (card) card.scrollIntoView({ block: "start", behavior: "auto" });
          });
        }
      });
    }

    async function initArcher() {
      setSoulState();
      if (wantsInviteEntryAnimation()) {
        enterChatFromInvite();
      } else {
        enterChat();
      }
      getSession().then(() => refreshProfilePanel()).catch(() => {});
    }
    initArcher().catch(() => enterChat());
