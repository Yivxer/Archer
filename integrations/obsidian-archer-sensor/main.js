const {
  MarkdownView,
  Notice,
  Plugin,
  PluginSettingTab,
  Setting,
  requestUrl,
} = require("obsidian");

const DEFAULT_SETTINGS = {
  endpoint: "http://127.0.0.1:8765",
  token: "",
  sendOnFileOpen: true,
  includeSelection: true,
  contentPreviewChars: 2000,
  debounceMs: 1200,
};

module.exports = class ArcherSensorPlugin extends Plugin {
  async onload() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    this.pendingTimer = null;

    this.addSettingTab(new ArcherSensorSettingTab(this.app, this));

    this.addCommand({
      id: "send-current-note-focus",
      name: "Send current note focus to Archer",
      callback: async () => {
        const result = await this.sendCurrentFocus({ manual: true });
        new Notice(result.ok ? "Archer focus sent" : `Archer focus failed: ${result.reason || result.error || "unknown"}`);
      },
    });

    this.registerEvent(
      this.app.workspace.on("file-open", () => {
        if (!this.settings.sendOnFileOpen) return;
        this.scheduleFocusSend();
      })
    );

    this.registerEvent(
      this.app.workspace.on("active-leaf-change", () => {
        if (!this.settings.sendOnFileOpen) return;
        this.scheduleFocusSend();
      })
    );
  }

  onunload() {
    if (this.pendingTimer) {
      window.clearTimeout(this.pendingTimer);
      this.pendingTimer = null;
    }
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  scheduleFocusSend() {
    if (this.pendingTimer) {
      window.clearTimeout(this.pendingTimer);
    }
    this.pendingTimer = window.setTimeout(() => {
      this.pendingTimer = null;
      this.sendCurrentFocus({ manual: false }).catch(() => {});
    }, Math.max(250, Number(this.settings.debounceMs) || DEFAULT_SETTINGS.debounceMs));
  }

  async sendCurrentFocus({ manual }) {
    const endpoint = cleanEndpoint(this.settings.endpoint);
    const token = String(this.settings.token || "").trim();
    if (!endpoint) {
      return { ok: false, reason: "endpoint is required" };
    }
    if (!token) {
      return { ok: false, reason: "desktop API token is required" };
    }

    const payload = await this.buildFocusPayload();
    if (!payload) {
      return { ok: false, reason: "no active markdown note" };
    }

    try {
      const response = await requestUrl({
        url: `${endpoint}/sensors/obsidian/focus`,
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
        throw: false,
      });
      const json = parseJson(response.text);
      if (response.status >= 200 && response.status < 300 && json && json.ok !== false) {
        return { ok: true, response: json };
      }
      return {
        ok: false,
        status: response.status,
        reason: (json && (json.reason || json.message || json.error)) || response.text,
      };
    } catch (error) {
      if (manual) console.error("[archer-sensor] send failed", error);
      return { ok: false, reason: error instanceof Error ? error.message : String(error) };
    }
  }

  async buildFocusPayload() {
    const view = this.app.workspace.getActiveViewOfType(MarkdownView);
    const file = view && view.file;
    if (!file || file.extension !== "md") return null;

    const content = await this.app.vault.cachedRead(file);
    const cache = this.app.metadataCache.getFileCache(file) || {};
    const basePath = this.app.vault.adapter && this.app.vault.adapter.basePath;
    const absolutePath = basePath ? `${basePath}/${file.path}` : "";
    const selectedText = this.settings.includeSelection && view.editor
      ? String(view.editor.getSelection() || "")
      : "";
    const tags = collectTags(cache);

    return {
      source: "obsidian-archer-sensor",
      vaultName: this.app.vault.getName(),
      file_path: absolutePath || file.path,
      relativePath: file.path,
      title: titleFromCache(cache) || file.basename,
      selected_text: trimText(selectedText, 1000),
      visible_headings: collectHeadings(cache),
      tags,
      content_preview: trimText(selectedText || firstMeaningfulExcerpt(content), this.settings.contentPreviewChars),
      sent_at: new Date().toISOString(),
    };
  }
};

class ArcherSensorSettingTab extends PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();

    new Setting(containerEl)
      .setName("Archer API endpoint")
      .setDesc("Usually http://127.0.0.1:8765.")
      .addText((text) => text
        .setPlaceholder(DEFAULT_SETTINGS.endpoint)
        .setValue(this.plugin.settings.endpoint)
        .onChange(async (value) => {
          this.plugin.settings.endpoint = value.trim();
          await this.plugin.saveSettings();
        }));

    new Setting(containerEl)
      .setName("Desktop API token")
      .setDesc("Use the token from Archer Desktop settings or the local desktop token file.")
      .addText((text) => {
        text.inputEl.type = "password";
        text
          .setPlaceholder("Bearer token without the Bearer prefix")
          .setValue(this.plugin.settings.token)
          .onChange(async (value) => {
            this.plugin.settings.token = value.trim();
            await this.plugin.saveSettings();
          });
      });

    new Setting(containerEl)
      .setName("Send when opening notes")
      .setDesc("Keeps Archer aware of the note currently in focus.")
      .addToggle((toggle) => toggle
        .setValue(Boolean(this.plugin.settings.sendOnFileOpen))
        .onChange(async (value) => {
          this.plugin.settings.sendOnFileOpen = value;
          await this.plugin.saveSettings();
        }));

    new Setting(containerEl)
      .setName("Include selected text")
      .setDesc("Selected text is preferred over the note excerpt when present.")
      .addToggle((toggle) => toggle
        .setValue(Boolean(this.plugin.settings.includeSelection))
        .onChange(async (value) => {
          this.plugin.settings.includeSelection = value;
          await this.plugin.saveSettings();
        }));

    new Setting(containerEl)
      .setName("Preview characters")
      .setDesc("Caps the context sent to Archer.")
      .addText((text) => text
        .setPlaceholder(String(DEFAULT_SETTINGS.contentPreviewChars))
        .setValue(String(this.plugin.settings.contentPreviewChars))
        .onChange(async (value) => {
          const parsed = Number(value);
          this.plugin.settings.contentPreviewChars = Number.isFinite(parsed)
            ? Math.max(300, Math.min(5000, Math.floor(parsed)))
            : DEFAULT_SETTINGS.contentPreviewChars;
          await this.plugin.saveSettings();
        }));

    new Setting(containerEl)
      .setName("Test send")
      .setDesc("Sends the active note focus to Archer now.")
      .addButton((button) => button
        .setButtonText("Send")
        .onClick(async () => {
          const result = await this.plugin.sendCurrentFocus({ manual: true });
          new Notice(result.ok ? "Archer focus sent" : `Archer focus failed: ${result.reason || result.error || "unknown"}`);
        }));
  }
}

function cleanEndpoint(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function parseJson(text) {
  try {
    return JSON.parse(text || "{}");
  } catch (_) {
    return null;
  }
}

function titleFromCache(cache) {
  const frontmatter = cache.frontmatter || {};
  return typeof frontmatter.title === "string" ? frontmatter.title.trim() : "";
}

function collectHeadings(cache) {
  const headings = Array.isArray(cache.headings) ? cache.headings : [];
  return headings
    .map((heading) => String(heading.heading || "").trim())
    .filter(Boolean)
    .slice(0, 12);
}

function collectTags(cache) {
  const found = new Set();
  const frontmatterTags = cache.frontmatter && cache.frontmatter.tags;
  if (Array.isArray(frontmatterTags)) {
    frontmatterTags.forEach((tag) => addTag(found, tag));
  } else if (typeof frontmatterTags === "string") {
    frontmatterTags.split(",").forEach((tag) => addTag(found, tag));
  }
  const inlineTags = Array.isArray(cache.tags) ? cache.tags : [];
  inlineTags.forEach((tag) => addTag(found, tag.tag));
  return Array.from(found).slice(0, 20);
}

function addTag(found, raw) {
  const tag = String(raw || "").trim().replace(/^#/, "");
  if (tag) found.add(tag);
}

function firstMeaningfulExcerpt(content) {
  const lines = [];
  let inFrontmatter = false;
  let seenFrontmatterStart = false;
  for (const line of String(content || "").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (trimmed === "---" && !seenFrontmatterStart) {
      seenFrontmatterStart = true;
      inFrontmatter = true;
      continue;
    }
    if (trimmed === "---" && inFrontmatter) {
      inFrontmatter = false;
      continue;
    }
    if (inFrontmatter || !trimmed || trimmed.startsWith("%%")) continue;
    lines.push(trimmed);
    if (lines.join("\n").length >= 2000) break;
  }
  return lines.join("\n");
}

function trimText(value, limit) {
  const text = String(value || "").trim();
  const max = Math.max(0, Number(limit) || 0);
  if (!max || text.length <= max) return text;
  return `${text.slice(0, max).trim()}\n\n...(truncated, ${text.length} chars)`;
}
