const launcher = document.querySelector(".launcher");
const versionChip = document.querySelector(".version-name");
const versionHero = document.querySelector(".version-hero");
const renameButton = document.querySelector(".rename-button");
const renameRow = document.querySelector(".rename-row");
const renameInput = document.querySelector(".rename-input");
const importButton = document.querySelector(".import-button");
const playButton = document.querySelector(".play-button");
const launchRingFill = document.querySelector(".launch-ring-fill");
const launchRingButton = document.querySelector(".launch-ring-button");
const launchStatus = document.querySelector(".launch-status");
const launchLogPanel = document.querySelector(".launch-log-panel");
const launchLogOutput = document.querySelector(".launch-log-output");
const folderList = document.querySelector(".folder-list");
const versionList = document.querySelector(".version-list");
const downloadView = document.querySelector(".download-view");
const downloadCategoryButtons = document.querySelectorAll(
  ".download-category-button"
);
const downloadBackButton = document.querySelector(
  ".download-back-button"
);
const downloadTitle = document.querySelector(".download-title");
const downloadLoading = document.querySelector(".download-loading");
const versionCategoryList = document.querySelector(
  ".version-category-list"
);
const downloadCatalogPanel = document.querySelector(
  ".download-catalog-panel"
);
const downloadLoaderPanel = document.querySelector(
  ".download-loader-panel"
);
const downloadBrowserPanel = document.querySelector(
  ".download-browser-panel"
);
const downloadSearchInput = document.querySelector(
  ".download-search-input"
);
const downloadVersionInput = document.querySelector(
  ".download-version-input"
);
const downloadVersionOptions = document.querySelector(
  ".download-version-options"
);
const downloadSearchButton = document.querySelector(
  ".download-search-button"
);
const downloadResultList = document.querySelector(
  ".download-result-list"
);
const downloadPagePrevButtons = document.querySelectorAll(
  ".download-page-prev"
);
const downloadPageNextButtons = document.querySelectorAll(
  ".download-page-next"
);
const downloadPageLabels = document.querySelectorAll(
  ".download-page-label"
);
const selectedDownloadVersion = document.querySelector(
  ".selected-download-version"
);
const loaderOptionList = document.querySelector(".loader-option-list");
const downloadPlaceholderPanel = document.querySelector(
  ".download-placeholder-panel"
);
const downloadPlaceholderTitle = document.querySelector(
  ".download-placeholder-title"
);
const downloadProgressPanel = document.querySelector(
  ".download-progress-panel"
);
const downloadProgressFill = document.querySelector(
  ".download-progress-fill"
);
const downloadProgressPercent = document.querySelector(
  ".download-progress-percent"
);
const downloadProgressMessage = document.querySelector(
  ".download-progress-message"
);
const downloadConfirmButton = document.querySelector(
  ".download-confirm-button"
);
const playerName = document.querySelector(".player-name");
const playerAvatar = document.querySelector(".player-avatar");
const accountMenu = document.querySelector(".account-menu");
const verifyPremiumButton = document.querySelector(".verify-premium-button");
const logoutAccountButton = document.querySelector(
  ".logout-account-button"
);
const cornerTile = document.querySelector(".corner-tile");
const cornerMenu = document.querySelector(".corner-menu");
const cornerPanel = document.querySelector(".corner-panel");
const cornerSettingsButton = document.querySelector(
  ".corner-settings-button"
);
const cornerDownloadButton = document.querySelector(
  ".corner-download-button"
);
const settingsView = document.querySelector(".settings-view");
const settingsHero = document.querySelector(".settings-hero");
const settingsSidebar = document.querySelector(".settings-sidebar");
const settingsNavItems = document.querySelectorAll(".settings-nav-item");
const settingsGeneralPanel = document.querySelector(
  ".settings-general-panel"
);
const settingsPersonalizationPanel = document.querySelector(
  ".settings-personalization-panel"
);
const settingsJavaPath = document.querySelector(".settings-java-path");
const settingsJavaStatus = document.querySelector(
  ".settings-java-status"
);
const settingsMemory = document.querySelector(".settings-memory");
const settingsDefaultVersion = document.querySelector(
  ".settings-default-version"
);
const settingsMinimize = document.querySelector(".settings-minimize");
const settingsAutoFolder = document.querySelector(".settings-auto-folder");
const settingsDarkMode = document.querySelector(".settings-dark-mode");
const settingsWallpaperPath = document.querySelector(
  ".settings-wallpaper-path"
);
const settingsWallpaperPreview = document.querySelector(
  ".settings-wallpaper-preview"
);
const settingsWallpaperButton = document.querySelector(
  ".settings-wallpaper-button"
);
const settingsBrowseButton = document.querySelector(
  ".settings-browse-button"
);
const saveSettingsButton = document.querySelector(".save-settings-button");
const settingsStatus = document.querySelector(".settings-status");

let currentVersion = "1.21.4";
let isEditing = false;
let isGameRunning = false;
let stopRequested = false;
let isCornerPanelOpen = false;
let cornerPanelCloseTimer = null;
let selectedWallpaperPath = "";
let selectedWallpaperUri = "";
let premiumLoginPending = false;
let premiumPollTimer = null;
let launchPollTimer = null;
let importedFolders = [];
let selectedSourceFolder = "";
let importedVersions = [];
let selectedVersionId = "";
let selectedGameVersion = "";
let folderSelectPending = false;
let versionSelectPending = false;
let nativeBootstrapped = false;
let downloadCatalog = [];
let selectedDownloadCategory = "vanilla";
let selectedDownloadVersionId = "";
let selectedDownloadLoaderId = "";
let downloadPollTimer = null;
let downloadFinished = false;
let activeDownloadTask = null;
let downloadRingVisible = false;
let downloadRingResetTimer = null;
let lastRingProgress = null;
let lastLaunchStatusMessage = null;
let lastLaunchStatusError = null;
let lastDownloadProgress = null;
let lastDownloadMessage = null;
let lastLaunchLogRevision = -1;
let currentJavaStatus = null;
let contentSearchPage = 1;
let contentSearchHasMore = false;
let contentSearchPending = false;
let contentGameVersion = "";
let contentVersionManual = false;
const contentTranslations = new Map();
const STORAGE_KEY = "minecraft-launcher-version";
const SETTINGS_STORAGE_KEY = "minecraft-launcher-settings";

async function saveVersion(value) {
  if (window.pywebview?.api?.save_version) {
    try {
      await window.pywebview.api.save_version(value);
      return;
    } catch {
      // Fall through to browser storage when the native bridge is unavailable.
    }
  }

  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Storage can be unavailable in restricted file contexts.
  }
}

async function loadSavedVersion() {
  let saved = null;

  if (window.pywebview?.api?.load_version) {
    try {
      saved = await window.pywebview.api.load_version();
    } catch {
      saved = null;
    }
  }

  if (!saved) {
    try {
      saved = localStorage.getItem(STORAGE_KEY);
    } catch {
      saved = null;
    }
  }

  if (saved && String(saved).trim()) {
    currentVersion = String(saved).trim();
    renderVersion(currentVersion);
  }
}

function formatVersion(value) {
  const text = String(value ?? "");

  return text.length > 12 ? `${text.slice(0, 12)}...` : text;
}

function renderVersion(value = currentVersion) {
  const display = formatVersion(value);

  versionChip.textContent = display;
  versionHero.textContent = display;

  if (!isEditing) {
    renameInput.value = currentVersion;
  }
}

function renderAccount(account) {
  if (account?.signed_in) {
    playerName.textContent = account.display_name || "Player";
    renderPremiumAvatar(account.avatar_path || "assets/player-avatar.png");
    logoutAccountButton.hidden = false;
  } else {
    playerName.textContent = "Steve";
    playerAvatar.src = "assets/player-avatar.png";
    logoutAccountButton.hidden = true;
  }
}

function renderPremiumAvatar(src) {
  const image = new Image();

  image.onload = () => {
    try {
      const sourceSize = Math.max(
        1,
        Math.floor(image.naturalWidth / 8)
      );
      const sourceX = sourceSize;
      const sourceY = sourceSize;
      const canvas = document.createElement("canvas");
      canvas.width = 128;
      canvas.height = 128;

      const context = canvas.getContext("2d");
      context.imageSmoothingEnabled = false;
      context.drawImage(
        image,
        sourceX,
        sourceY,
        sourceSize,
        sourceSize,
        0,
        0,
        128,
        128
      );
      playerAvatar.src = canvas.toDataURL("image/png");
    } catch {
      playerAvatar.src = "assets/player-avatar.png";
    }
  };

  image.onerror = () => {
    playerAvatar.src = "assets/player-avatar.png";
  };

  image.src = src;
}

async function loadAccount() {
  if (!window.pywebview?.api?.get_account_info) {
    return;
  }

  try {
    const result = await window.pywebview.api.get_account_info();
    renderAccount(result);
  } catch {
    // Keep the default player when the native account API is unavailable.
  }
}

function positionAccountMenu() {
  const rect = playerAvatar.getBoundingClientRect();
  const menuWidth = accountMenu.offsetWidth || 136;
  let left = rect.right + 14;

  if (left + menuWidth > window.innerWidth - 12) {
    left = Math.max(12, window.innerWidth - menuWidth - 12);
  }

  accountMenu.style.left = `${left}px`;
  accountMenu.style.top = `${rect.top + rect.height / 2}px`;
}

function openAccountMenu() {
  positionAccountMenu();
  accountMenu.classList.add("is-open");
  requestAnimationFrame(() => positionAccountMenu());
}

function toggleAccountMenu() {
  if (accountMenu.classList.contains("is-open")) {
    closeAccountMenu();
  } else {
    openAccountMenu();
  }
}

function closeAccountMenu() {
  accountMenu.classList.remove("is-open");
}

function openCornerPanel() {
  closeAccountMenu();
  clearTimeout(cornerPanelCloseTimer);
  isCornerPanelOpen = true;
  cornerPanel.classList.add("is-open");
  cornerTile.setAttribute("aria-expanded", "true");
}

function closeCornerPanel() {
  clearTimeout(cornerPanelCloseTimer);
  isCornerPanelOpen = false;
  cornerPanel.classList.remove("is-open");
  cornerTile.setAttribute("aria-expanded", "false");
}

function applySettings(settings) {
  if (!settings) {
    return;
  }

  document.documentElement.dataset.theme = settings.dark_mode
    ? "dark"
    : "light";
  settingsJavaPath.value = settings.java_path || "";
  settingsMemory.value = settings.memory_mb || 4096;
  settingsDefaultVersion.value = settings.default_version || "";
  settingsMinimize.checked = Boolean(settings.minimize_on_launch);
  settingsAutoFolder.checked = Boolean(
    settings.auto_select_last_folder ?? true
  );
  settingsDarkMode.checked = Boolean(settings.dark_mode);
  selectedWallpaperPath = settings.wallpaper_path || "";
  selectedWallpaperUri = settings.wallpaper_uri || "";

  if (selectedWallpaperUri) {
    launcher.style.backgroundImage = `url("${selectedWallpaperUri}")`;
    settingsWallpaperPreview.style.backgroundImage =
      `url("${selectedWallpaperUri}")`;
    settingsWallpaperPath.value =
      settings.wallpaper_name ||
      selectedWallpaperPath.split(/[\\/]/).pop() ||
      "已设置壁纸";
  } else {
    launcher.style.backgroundImage = "";
    settingsWallpaperPreview.style.backgroundImage = "";
    settingsWallpaperPath.value = "";
  }
}

async function loadSettings() {
  let settings = null;

  if (window.pywebview?.api?.get_settings) {
    try {
      settings = await window.pywebview.api.get_settings();
    } catch {
      settings = null;
    }
  }

  if (!settings) {
    try {
      settings = JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY));
    } catch {
      settings = null;
    }
  }

  applySettings(settings);
}

function renderJavaStatus(status) {
  currentJavaStatus = status;
  settingsJavaStatus.textContent = status?.message || "未找到 Java";
  settingsJavaStatus.classList.toggle(
    "is-ok",
    status?.state === "exact" || status?.state === "higher"
  );
  settingsJavaStatus.classList.toggle(
    "is-warning",
    status?.state === "lower" || status?.state === "missing"
  );
  settingsJavaStatus.title =
    status?.state === "missing" ? "点击安装 Java" : "";
}

async function refreshJavaStatus() {
  if (!window.pywebview?.api?.get_java_status) {
    return;
  }

  try {
    const status = await window.pywebview.api.get_java_status(
      selectedVersionId || currentVersion
    );
    renderJavaStatus(status);
  } catch {
    renderJavaStatus({
      state: "missing",
      message: "Java 状态检测失败",
    });
  }
}

async function installRequiredJava() {
  if (
    !currentJavaStatus ||
    currentJavaStatus.state !== "missing" ||
    !window.pywebview?.api?.install_java
  ) {
    return;
  }

  settingsJavaStatus.textContent = "正在安装 Java...";

  try {
    const status = await window.pywebview.api.install_java(
      selectedVersionId || currentVersion
    );
    renderJavaStatus(status);
  } catch (error) {
    renderJavaStatus({
      state: "missing",
      message: error?.message || "Java 安装失败",
    });
  }
}

async function saveSettings() {
  const settings = {
    java_path: settingsJavaPath.value.trim(),
    memory_mb: Number(settingsMemory.value) || 4096,
    default_version: settingsDefaultVersion.value.trim(),
    minimize_on_launch: settingsMinimize.checked,
    auto_select_last_folder: settingsAutoFolder.checked,
    dark_mode: settingsDarkMode.checked,
    wallpaper_path: selectedWallpaperPath,
    wallpaper_uri: selectedWallpaperUri,
  };

  if (window.pywebview?.api?.save_settings) {
    try {
      const result = await window.pywebview.api.save_settings(settings);
      settingsStatus.textContent = result.message || "设置已保存";
      applySettings(settings);
      await loadAppState();
      return;
    } catch (error) {
      settingsStatus.textContent = error?.message || "设置保存失败";
      return;
    }
  }

  try {
    localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify(settings)
    );
    settingsStatus.textContent = "设置已保存";
  } catch {
    settingsStatus.textContent = "设置保存失败";
  }
}

async function handleBrowseJava() {
  if (!window.pywebview?.api?.browse_java) {
    settingsStatus.textContent = "仅 exe 支持选择";
    return;
  }

  try {
    const result = await window.pywebview.api.browse_java();

    if (result.ok) {
      settingsJavaPath.value = result.java_path || "";
      settingsStatus.textContent = "已选择 Java";
    } else {
      settingsStatus.textContent = result.message || "未选择 Java";
    }
  } catch (error) {
    settingsStatus.textContent = error?.message || "选择 Java 失败";
  }
}

async function handleChangeWallpaper() {
  if (!window.pywebview?.api?.browse_wallpaper) {
    settingsStatus.textContent = "仅 exe 支持更换";
    return;
  }

  try {
    const result = await window.pywebview.api.browse_wallpaper();

    if (result.ok) {
      selectedWallpaperPath = result.wallpaper_path || "";
      selectedWallpaperUri = result.wallpaper_uri || "";
      launcher.style.backgroundImage =
        `url("${selectedWallpaperUri}")`;
      settingsWallpaperPreview.style.backgroundImage =
        `url("${selectedWallpaperUri}")`;
      settingsWallpaperPath.value =
        result.wallpaper_name || "已设置壁纸";
      settingsStatus.textContent = "保存后生效";
    } else {
      settingsStatus.textContent = result.message || "未选择图片";
    }
  } catch (error) {
    settingsStatus.textContent = error?.message || "更换壁纸失败";
  }
}

function activateSettingsTab(tab) {
  settingsNavItems.forEach((item) => {
    item.classList.toggle(
      "is-active",
      item.dataset.settingsTab === tab
    );
  });
  settingsGeneralPanel.hidden = tab !== "general";
  settingsPersonalizationPanel.hidden = tab !== "personalization";
}

function openSettings() {
  closeCornerPanel();
  settingsStatus.textContent = "";
  activateSettingsTab("general");
  launcher.dataset.view = "settings";
  loadSettings();
  refreshJavaStatus();
}

const DOWNLOAD_CATEGORY_LABELS = {
  vanilla: "原版",
  mods: "模组",
  shaders: "光影",
  resourcepacks: "材质包",
  datapacks: "数据包",
};

function formatDownloadDate(value) {
  if (!value) {
    return "";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value.slice(0, 10);
  }

  return parsed.toLocaleDateString("zh-CN");
}

function showDownloadPanel(panel) {
  downloadCatalogPanel.hidden = panel !== downloadCatalogPanel;
  downloadLoaderPanel.hidden = panel !== downloadLoaderPanel;
  downloadBrowserPanel.hidden = panel !== downloadBrowserPanel;
  downloadPlaceholderPanel.hidden =
    panel !== downloadPlaceholderPanel;
  downloadProgressPanel.hidden =
    panel !== downloadProgressPanel;
}

function appendDownloadVersions(list, versions) {
  if (list.dataset.rendered === "true") {
    return;
  }

  list.dataset.rendered = "true";
  const fragment = document.createDocumentFragment();

  for (const version of versions) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "download-version-button";
    item.dataset.versionId = version.id;

    const versionLabel = document.createElement("span");
    versionLabel.className = "download-version-id";
    versionLabel.textContent = version.id;

    const date = document.createElement("span");
    date.className = "download-version-date";
    date.textContent = formatDownloadDate(version.release_time);

    item.append(versionLabel, date);
    item.addEventListener("click", () => {
      openLoaderSelection(version.id);
    });
    fragment.appendChild(item);
  }

  list.appendChild(fragment);
}

function renderDownloadCatalog() {
  versionCategoryList.replaceChildren();
  downloadLoading.classList.add("is-hidden");
  const fragment = document.createDocumentFragment();

  downloadCatalog.forEach((group, index) => {
    const details = document.createElement("details");
    details.className = "version-category-group";
    details.open = index === 0;

    const summary = document.createElement("summary");
    const label = document.createElement("span");
    label.textContent = group.label;
    const count = document.createElement("span");
    count.className = "version-category-count";
    count.textContent = String(group.versions.length);
    summary.append(label, count);

    const list = document.createElement("div");
    list.className = "download-version-list";
    details.append(summary, list);

    details.addEventListener("toggle", () => {
      if (details.open) {
        appendDownloadVersions(list, group.versions);
      }
    });

    if (details.open) {
      appendDownloadVersions(list, group.versions);
    }

    fragment.appendChild(details);
  });

  versionCategoryList.appendChild(fragment);
}

async function loadDownloadCatalog() {
  if (!window.pywebview?.api?.get_minecraft_versions) {
    downloadLoading.textContent = "仅 exe 支持下载";
    downloadLoading.classList.remove("is-hidden");
    versionCategoryList.replaceChildren();
    return;
  }

  downloadLoading.textContent = "正在加载";
  downloadLoading.classList.remove("is-hidden");

  try {
    const result =
      await window.pywebview.api.get_minecraft_versions();

    if (!result.ok) {
      throw new Error(result.message || "读取版本列表失败");
    }

    downloadCatalog = Array.isArray(result.groups)
      ? result.groups
      : [];
    renderDownloadVersionOptions();
    renderDownloadCatalog();
  } catch (error) {
    downloadLoading.textContent =
      error?.message || "读取版本列表失败";
    downloadLoading.classList.remove("is-hidden");
    versionCategoryList.replaceChildren();
  }
}

function formatDownloadCount(value) {
  const count = Number(value) || 0;

  if (count >= 100000000) {
    return `${(count / 100000000).toFixed(1)}亿`;
  }

  if (count >= 10000) {
    return `${(count / 10000).toFixed(1)}万`;
  }

  return String(count);
}

function contentDisplayTitle(item) {
  const translation = contentTranslations.get(
    `${item.source}:${item.project_id}`
  );
  return translation ? `[${translation}] ${item.title}` : item.title;
}

function applyContentTranslations(translations) {
  let changed = false;

  Object.entries(translations || {}).forEach(([key, value]) => {
    if (!value || contentTranslations.get(key) === value) {
      return;
    }

    contentTranslations.set(key, value);
    changed = true;
  });

  if (!changed) {
    return;
  }

  downloadResultList
    .querySelectorAll(".download-result-item")
    .forEach((button) => {
      const translation = contentTranslations.get(
        button.dataset.resultKey
      );

      if (!translation) {
        return;
      }

      const title = button.querySelector(".download-result-title");

      if (title) {
        title.textContent = `[${translation}] ${button.dataset.title}`;
      }
    });
}

async function updateContentTranslations(items) {
  if (
    !window.pywebview?.api?.get_content_translations ||
    !items.length
  ) {
    return;
  }

  try {
    const result =
      await window.pywebview.api.get_content_translations(
        items.map((item) => ({
          source: item.source,
          project_id: item.project_id,
          title: item.title,
          slug: item.slug || "",
        }))
      );

    if (result?.ok) {
      applyContentTranslations(result.translations || {});
    }
  } catch {
    // 译名获取失败时保留英文原名。
  }
}

function renderDownloadVersionOptions() {
  if (!downloadVersionOptions) {
    return;
  }

  const ids = [];

  downloadCatalog.forEach((group) => {
    (group.versions || []).forEach((version) => {
      if (version.id) {
        ids.push(version.id);
      }
    });
  });

  const fragment = document.createDocumentFragment();

  ids.forEach((id) => {
    const option = document.createElement("option");
    option.value = id;
    fragment.appendChild(option);
  });

  downloadVersionOptions.replaceChildren(fragment);

  if (!contentGameVersion) {
    contentGameVersion = defaultContentGameVersion(ids[0] || "");
  }

  if (!downloadVersionInput.value) {
    downloadVersionInput.value = contentGameVersion;
  }
}

function mcVersionFromText(value) {
  const match = String(value || "").match(/\d+\.\d+(?:\.\d+)?/);
  return match ? match[0] : "";
}

function defaultContentGameVersion(fallback = "") {
  return (
    selectedGameVersion ||
    mcVersionFromText(selectedVersionId) ||
    mcVersionFromText(currentVersion) ||
    fallback
  );
}

function readContentGameVersion() {
  const value = downloadVersionInput.value.trim();

  if (value) {
    contentGameVersion = value;
  } else if (!contentGameVersion) {
    contentGameVersion = defaultContentGameVersion();
    downloadVersionInput.value = contentGameVersion;
  }

  return contentGameVersion;
}

function syncContentVersionFromSelection() {
  if (contentVersionManual || !downloadVersionInput) {
    return;
  }

  contentGameVersion = defaultContentGameVersion();
  downloadVersionInput.value = contentGameVersion;
}

function renderContentResults(items) {
  downloadResultList.replaceChildren();

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "download-browser-status";
    empty.textContent = "无结果";
    downloadResultList.appendChild(empty);
    return;
  }

  const fragment = document.createDocumentFragment();

  for (const item of items) {
    const resultKey = `${item.source}:${item.project_id}`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "download-result-item";
    button.dataset.source = item.source;
    button.dataset.projectId = item.project_id;
    button.dataset.resultKey = resultKey;
    button.dataset.title = item.title;
    button.dataset.slug = item.slug || "";

    const icon = document.createElement("span");
    icon.className = "download-result-icon";
    if (item.icon_url) {
      icon.style.backgroundImage = `url("${item.icon_url}")`;
    }

    const copy = document.createElement("span");
    copy.className = "download-result-copy";
    const title = document.createElement("strong");
    title.className = "download-result-title";
    title.textContent = contentDisplayTitle(item);
    const description = document.createElement("span");
    description.className = "download-result-description";
    description.textContent = item.description || "";
    copy.append(title, description);

    const meta = document.createElement("span");
    meta.className = "download-result-meta";
    const source = document.createElement("span");
    source.className = "download-result-source";
    source.textContent = item.source_label;
    const downloads = document.createElement("span");
    downloads.className = "download-result-downloads";
    downloads.title = "下载量";
    downloads.textContent = formatDownloadCount(item.downloads);
    meta.append(source, downloads);

    button.append(icon, copy, meta);
    button.addEventListener("click", () => {
      handleContentDownload(item);
    });
    fragment.appendChild(button);
  }

  downloadResultList.appendChild(fragment);
}

function updateContentPagination() {
  downloadPageLabels.forEach((label) => {
    label.textContent = `第 ${contentSearchPage} 页`;
  });
  downloadPagePrevButtons.forEach((button) => {
    button.disabled = contentSearchPage <= 1 || contentSearchPending;
  });
  downloadPageNextButtons.forEach((button) => {
    button.disabled = !contentSearchHasMore || contentSearchPending;
  });
}

async function loadContentSearch(page = 1) {
  if (
    !window.pywebview?.api?.search_content ||
    !["mods", "shaders", "resourcepacks"].includes(
      selectedDownloadCategory
    )
  ) {
    return;
  }

  contentSearchPending = true;
  contentSearchPage = Math.max(1, page);
  updateContentPagination();
  downloadResultList.replaceChildren();
  const status = document.createElement("div");
  status.className = "download-browser-status";
  status.textContent = "正在加载";
  downloadResultList.appendChild(status);

  try {
    const result = await window.pywebview.api.search_content(
      selectedDownloadCategory,
      downloadSearchInput.value.trim(),
      readContentGameVersion(),
      "",
      contentSearchPage
    );

    if (!result.ok) {
      throw new Error(result.message || "读取内容列表失败");
    }

    const items = result.items || [];
    contentSearchHasMore = Boolean(result.has_more);
    renderContentResults(items);
    updateContentTranslations(items);
  } catch (error) {
    downloadResultList.replaceChildren();
    const message = document.createElement("div");
    message.className = "download-browser-status";
    message.textContent = error?.message || "读取内容列表失败";
    downloadResultList.appendChild(message);
    contentSearchHasMore = false;
  } finally {
    contentSearchPending = false;
    updateContentPagination();
  }
}

function startDownloadPolling() {
  clearInterval(downloadPollTimer);
  downloadPollTimer = setInterval(pollDownloadStatus, 600);
  pollDownloadStatus();
}

async function handleContentDownload(item) {
  if (!window.pywebview?.api?.start_content_download) {
    return;
  }

  downloadConfirmButton.hidden = true;
  downloadFinished = false;
  showDownloadPanel(downloadProgressPanel);
  updateDownloadProgress({
    progress: 1,
    message: `准备下载 ${item.title}`,
  });
  syncDownloadRing({
    progress: 1,
    message: `准备下载 ${item.title}`,
    error: "",
    running: true,
  });

  try {
    const result =
      await window.pywebview.api.start_content_download(
        selectedDownloadCategory,
        item.source,
        item.project_id,
        item.title,
        item.slug || "",
        readContentGameVersion()
      );

    if (!result.ok) {
      throw new Error(result.message || "无法开始下载");
    }

    startDownloadPolling();
  } catch (error) {
    downloadProgressMessage.textContent =
      error?.message || "无法开始下载";
  }
}

function selectDownloadCategory(category) {
  selectedDownloadCategory = category;
  selectedDownloadVersionId = "";
  selectedDownloadLoaderId = "";
  downloadFinished = false;
  downloadConfirmButton.hidden = true;
  downloadConfirmButton.disabled = true;
  downloadConfirmButton.textContent = "确定";

  downloadCategoryButtons.forEach((button) => {
    button.classList.toggle(
      "is-active",
      button.dataset.downloadCategory === category
    );
  });

  const label = DOWNLOAD_CATEGORY_LABELS[category] || "下载";
  downloadTitle.textContent = label;

  if (category === "vanilla") {
    showDownloadPanel(downloadCatalogPanel);
    if (!downloadCatalog.length) {
      loadDownloadCatalog();
    }
    return;
  }

  if (
    ["mods", "shaders", "resourcepacks"].includes(category)
  ) {
    downloadSearchInput.value = "";
    contentSearchPage = 1;
    readContentGameVersion();
    showDownloadPanel(downloadBrowserPanel);
    loadContentSearch(1);
    return;
  }

  downloadPlaceholderTitle.textContent = label;
  downloadPlaceholderPanel.dataset.category = category;
  showDownloadPanel(downloadPlaceholderPanel);
}

function openDownloadCenter() {
  closeCornerPanel();
  closeAccountMenu();
  launcher.dataset.view = "download";
  selectDownloadCategory("vanilla");

  if (!downloadCatalog.length) {
    loadDownloadCatalog();
  }
}

async function openLoaderSelection(versionId) {
  if (!window.pywebview?.api?.get_version_loaders) {
    return;
  }

  selectedDownloadVersionId = versionId;
  selectedDownloadLoaderId = "";
  selectedDownloadVersion.textContent = versionId;
  loaderOptionList.replaceChildren();
  downloadTitle.textContent = "选择加载器";
  downloadConfirmButton.hidden = true;
  downloadConfirmButton.disabled = true;
  showDownloadPanel(downloadLoaderPanel);

  const loading = document.createElement("div");
  loading.className = "download-loading";
  loading.textContent = "正在加载";
  loaderOptionList.appendChild(loading);

  try {
    const result =
      await window.pywebview.api.get_version_loaders(versionId);

    if (!result.ok) {
      throw new Error(result.message || "读取加载器失败");
    }

    loaderOptionList.replaceChildren();

    for (const loader of result.loaders) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "loader-option";
      item.dataset.loaderId = loader.id;

      const name = document.createElement("strong");
      name.textContent = loader.version
        ? `${loader.name} ${loader.version}`
        : loader.name;
      const description = document.createElement("span");
      description.textContent = loader.description || "";
      item.append(name, description);

      item.addEventListener("click", () => {
        selectedDownloadLoaderId = loader.id;
        loaderOptionList
          .querySelectorAll(".loader-option")
          .forEach((option) => {
            option.classList.toggle(
              "is-active",
              option.dataset.loaderId === loader.id
            );
          });
        downloadConfirmButton.hidden = false;
        downloadConfirmButton.disabled = false;
      });
      loaderOptionList.appendChild(item);
    }
  } catch (error) {
    loaderOptionList.replaceChildren();
    const message = document.createElement("div");
    message.className = "download-loading";
    message.textContent = error?.message || "读取加载器失败";
    loaderOptionList.appendChild(message);
  }
}

function updateDownloadProgress(status) {
  const progress = Math.max(
    0,
    Math.min(100, Number(status.progress) || 0)
  );
  const message = status.message || "正在下载";

  if (progress !== lastDownloadProgress) {
    lastDownloadProgress = progress;
    downloadProgressFill.style.width = `${progress}%`;
    downloadProgressPercent.textContent = `${progress}%`;
  }

  if (message !== lastDownloadMessage) {
    lastDownloadMessage = message;
    downloadProgressMessage.textContent = message;
  }
}

function scheduleDownloadRingReset() {
  clearTimeout(downloadRingResetTimer);
  downloadRingResetTimer = setTimeout(() => {
    downloadRingVisible = false;
    updateLaunchRing(0);
  }, 5000);
}

function syncDownloadRing(status) {
  activeDownloadTask = status;
  downloadRingVisible = true;
  clearTimeout(downloadRingResetTimer);
  updateLaunchRing(status.progress || 0);
  launchRingButton.classList.toggle(
    "is-active",
    Boolean(status.running)
  );

  if (!status.running) {
    scheduleDownloadRingReset();
  }
}

function openDownloadTaskView() {
  if (!activeDownloadTask) {
    return;
  }

  closeCornerPanel();
  closeAccountMenu();
  launcher.dataset.view = "download";
  showDownloadPanel(downloadProgressPanel);
  updateDownloadProgress(activeDownloadTask);
  downloadConfirmButton.hidden = Boolean(activeDownloadTask.running);
  downloadConfirmButton.disabled = Boolean(activeDownloadTask.running);

  if (!activeDownloadTask.running && activeDownloadTask.progress >= 100) {
    downloadFinished = true;
    downloadConfirmButton.textContent = "完成";
  } else if (activeDownloadTask.error) {
    downloadFinished = false;
    downloadConfirmButton.textContent = "重试";
  }
}

async function pollDownloadStatus() {
  if (!window.pywebview?.api?.get_download_status) {
    return;
  }

  try {
    const status =
      await window.pywebview.api.get_download_status();
    updateDownloadProgress(status);
    syncDownloadRing(status);
    setLaunchStatus(status.error || status.message || "正在下载", Boolean(status.error));

    if (status.error) {
      clearInterval(downloadPollTimer);
      downloadPollTimer = null;
      downloadConfirmButton.hidden = false;
      downloadConfirmButton.disabled = false;
      downloadConfirmButton.textContent = "重试";
      downloadFinished = false;
      return;
    }

    if (!status.running && status.progress >= 100) {
      clearInterval(downloadPollTimer);
      downloadPollTimer = null;
      downloadFinished = true;
      downloadConfirmButton.hidden = false;
      downloadConfirmButton.disabled = false;
      downloadConfirmButton.textContent = "完成";
      await loadAppState();
    }
  } catch {
    // Keep polling while the native downloader is processing.
  }
}

async function startSelectedDownload() {
  if (downloadFinished) {
    launcher.dataset.view = "home";
    return;
  }

  if (
    !selectedDownloadVersionId ||
    !selectedDownloadLoaderId
  ) {
    return;
  }

  if (!window.pywebview?.api?.start_version_download) {
    downloadProgressMessage.textContent = "仅 exe 支持下载";
    return;
  }

  downloadConfirmButton.hidden = true;
  showDownloadPanel(downloadProgressPanel);
  updateDownloadProgress({
    progress: 1,
    message: "正在准备下载",
  });
  syncDownloadRing({
    progress: 1,
    message: "正在准备下载",
    error: "",
    running: true,
  });

  try {
    const result =
      await window.pywebview.api.start_version_download(
        selectedDownloadVersionId,
        selectedDownloadLoaderId
      );

    if (!result.ok) {
      throw new Error(result.message || "无法开始下载");
    }

    startDownloadPolling();
  } catch (error) {
    downloadProgressMessage.textContent =
      error?.message || "无法开始下载";
    downloadConfirmButton.hidden = false;
    downloadConfirmButton.disabled = false;
    downloadConfirmButton.textContent = "重试";
  }
}

function handleDownloadBack() {
  if (!downloadLoaderPanel.hidden) {
    selectedDownloadVersionId = "";
    selectedDownloadLoaderId = "";
    downloadTitle.textContent =
      DOWNLOAD_CATEGORY_LABELS[selectedDownloadCategory] || "原版";
    downloadConfirmButton.hidden = true;
    showDownloadPanel(downloadCatalogPanel);
    return;
  }

  launcher.dataset.view = "home";
}

function updateVerifyButton() {
  verifyPremiumButton.disabled = premiumLoginPending;
  verifyPremiumButton.textContent = premiumLoginPending
    ? "验证中..."
    : "正版验证";
}

async function handlePremiumLogin() {
  if (!window.pywebview?.api?.start_premium_login) {
    setLaunchStatus("仅 exe 支持验证", true);
    return;
  }

  premiumLoginPending = true;
  updateVerifyButton();
  setLaunchStatus("正在打开授权页");

  try {
    const result = await window.pywebview.api.start_premium_login();

    if (result.state === "error") {
      premiumLoginPending = false;
      updateVerifyButton();
      setLaunchStatus(
        result.error || result.message || "正版验证失败",
        true
      );
      return;
    }

    setLaunchStatus(result.message || "请在浏览器完成授权");
    startPremiumStatusPolling();
  } catch (error) {
    premiumLoginPending = false;
    updateVerifyButton();
    setLaunchStatus(error?.message || "正版验证失败", true);
  }
}

async function handleLogoutAccount() {
  if (!window.pywebview?.api?.logout_account) {
    setLaunchStatus("仅 exe 支持退出", true);
    return;
  }

  logoutAccountButton.disabled = true;
  logoutAccountButton.textContent = "退出中...";

  try {
    const result = await window.pywebview.api.logout_account();

    if (result.ok) {
      renderAccount({ signed_in: false });
      closeAccountMenu();
      setLaunchStatus(result.message || "已退出正版账号");
    } else {
      setLaunchStatus(result.message || "退出账号失败", true);
    }
  } catch (error) {
    setLaunchStatus(error?.message || "退出账号失败", true);
  } finally {
    logoutAccountButton.disabled = false;
    logoutAccountButton.textContent = "退出账号";
  }
}

function startPremiumStatusPolling() {
  clearInterval(premiumPollTimer);

  premiumPollTimer = setInterval(async () => {
    if (
      !premiumLoginPending ||
      !window.pywebview?.api?.get_premium_login_status
    ) {
      clearInterval(premiumPollTimer);
      return;
    }

    try {
      const status =
        await window.pywebview.api.get_premium_login_status();

      if (status.state === "success") {
        premiumLoginPending = false;
        updateVerifyButton();
        clearInterval(premiumPollTimer);
        await loadAccount();
        setLaunchStatus(status.message || "正版验证成功");
      } else if (status.state === "error") {
        premiumLoginPending = false;
        updateVerifyButton();
        clearInterval(premiumPollTimer);
        setLaunchStatus(
          status.error || status.message || "正版验证失败",
          true
        );
      } else {
        setLaunchStatus(status.message || "等待微软授权");
      }
    } catch {
      // Keep polling while the native bridge is processing the login.
    }
  }, 1500);
}

function createSidebarItem({
  className,
  labelClass,
  label,
  title = "",
  dataset = {},
  active = false,
  busy = false,
  onClick,
}) {
  const item = document.createElement("button");
  item.type = "button";
  item.className = className;
  item.title = title;

  if (active) {
    item.classList.add("is-active");
  }

  if (busy) {
    item.classList.add("is-busy");
  }

  Object.entries(dataset).forEach(([key, value]) => {
    item.dataset[key] = value;
  });

  const labelNode = document.createElement("span");
  labelNode.className = labelClass;
  labelNode.textContent = label;
  item.appendChild(labelNode);
  item.addEventListener("click", onClick);
  return item;
}

function syncSidebarState(
  container,
  itemClass,
  datasetKey,
  activeValue,
  busy
) {
  if (!container) {
    return;
  }

  container.toggleAttribute("aria-busy", busy);

  container.querySelectorAll(`.${itemClass}`).forEach((item) => {
    const isActive = item.dataset[datasetKey] === activeValue;
    item.classList.toggle("is-active", isActive);
    item.classList.toggle("is-busy", busy && isActive);
  });
}

function syncFolderSidebarState() {
  syncSidebarState(
    folderList,
    "folder-item",
    "sourceFolder",
    selectedSourceFolder,
    folderSelectPending
  );
}

function syncVersionSidebarState() {
  syncSidebarState(
    versionList,
    "version-sidebar-item",
    "versionId",
    selectedVersionId,
    versionSelectPending
  );
}

function renderFolderSidebar() {
  if (!folderList) {
    return;
  }

  folderList.replaceChildren();
  folderList.toggleAttribute("aria-busy", folderSelectPending);

  for (const folder of importedFolders) {
    if (!folder.source_folder) {
      continue;
    }

    const label =
      folder.folder_name ||
      folder.display_name ||
      folder.version_id ||
      folder.source_folder;
    const item = createSidebarItem({
      className: "folder-item",
      labelClass: "folder-name",
      label,
      title: folder.source_folder,
      dataset: { sourceFolder: folder.source_folder },
      active: folder.source_folder === selectedSourceFolder,
      busy:
        folderSelectPending &&
        folder.source_folder === selectedSourceFolder,
      onClick: () => handleFolderSelect(folder.source_folder),
    });
    folderList.appendChild(item);
  }
}

function renderVersionSidebar() {
  if (!versionList) {
    return;
  }

  versionList.replaceChildren();
  versionList.toggleAttribute("aria-busy", versionSelectPending);

  for (const version of importedVersions) {
    if (!version.version_id) {
      continue;
    }

    const item = createSidebarItem({
      className: "version-sidebar-item",
      labelClass: "version-sidebar-label",
      label: version.display_name || version.version_id,
      title: version.version_folder || version.version_id,
      dataset: { versionId: version.version_id },
      active: version.version_id === selectedVersionId,
      busy:
        versionSelectPending &&
        version.version_id === selectedVersionId,
      onClick: () => handleVersionSelect(version.version_id),
    });
    versionList.appendChild(item);
  }
}

async function refreshFolderState() {
  if (!window.pywebview?.api?.get_imported_folders) {
    return;
  }

  try {
    const result = await window.pywebview.api.get_imported_folders();

    importedFolders = Array.isArray(result.folders) ? result.folders : [];
    selectedSourceFolder = result.selected_folder || "";
    renderFolderSidebar();
  } catch {
    // Keep the current sidebar state when the native bridge is unavailable.
  }
}

async function refreshVersionState() {
  if (!window.pywebview?.api?.get_versions || !selectedSourceFolder) {
    importedVersions = [];
    selectedVersionId = "";
    selectedGameVersion = "";
    syncContentVersionFromSelection();
    renderVersionSidebar();
    return;
  }

  try {
    const result = await window.pywebview.api.get_versions(
      selectedSourceFolder
    );

    importedVersions = Array.isArray(result.versions)
      ? result.versions
      : [];
    selectedVersionId = result.selected_version_id || "";
    selectedGameVersion = result.game_version || "";
    syncContentVersionFromSelection();
    renderVersionSidebar();
  } catch {
    // Keep the current version list when the native bridge is unavailable.
  }
}

async function loadAppState() {
  if (!window.pywebview?.api?.get_imported_folders) {
    return;
  }

  try {
    await refreshFolderState();
    await Promise.all([
      refreshVersionState(),
      window.pywebview.api.load_version().then((saved) => {
        if (saved && String(saved).trim()) {
          currentVersion = String(saved).trim();
          renderVersion(currentVersion);
        }
      }),
      loadAccount(),
      refreshJavaStatus(),
    ]);
  } catch {
    // Ignore transient startup failures; the UI keeps its default state.
  }
}

async function handleVersionSelect(versionId) {
  if (
    !window.pywebview?.api?.select_version ||
    !selectedSourceFolder ||
    !versionId ||
    versionSelectPending ||
    folderSelectPending
  ) {
    return;
  }

  const previousVersionId = selectedVersionId;
  versionSelectPending = true;
  selectedVersionId = versionId;
  syncVersionSidebarState();

  if (isEditing) {
    isEditing = false;
    renameRow.classList.remove("is-editing");
    renameInput.blur();
  }

  setLaunchStatus("检测版本");

  try {
    const result = await window.pywebview.api.select_version(
      selectedSourceFolder,
      versionId
    );

    if (result.ok) {
      versionSelectPending = false;
      currentVersion =
        result.display_name || result.version_id || currentVersion;
      renderVersion(currentVersion);
      refreshJavaStatus();
      syncVersionSidebarState();
      await refreshVersionState();
      setLaunchStatus(result.message || "已切换版本");
    } else {
      versionSelectPending = false;
      selectedVersionId = previousVersionId;
      syncVersionSidebarState();
      setLaunchStatus(result.message || "未找到游戏版本", true);
    }
  } catch (error) {
    versionSelectPending = false;
    selectedVersionId = previousVersionId;
    syncVersionSidebarState();
    setLaunchStatus(error?.message || "切换版本失败", true);
  }
}

async function handleFolderSelect(sourceFolder) {
  if (
    !window.pywebview?.api?.select_folder ||
    !sourceFolder ||
    folderSelectPending ||
    versionSelectPending
  ) {
    return;
  }

  const previousSourceFolder = selectedSourceFolder;
  folderSelectPending = true;
  selectedSourceFolder = sourceFolder;
  syncFolderSidebarState();

  if (isEditing) {
    isEditing = false;
    renameRow.classList.remove("is-editing");
    renameInput.blur();
  }

  setLaunchStatus("检测文件");

  try {
    const result = await window.pywebview.api.select_folder(sourceFolder);

    if (result.ok) {
      folderSelectPending = false;
      selectedSourceFolder = result.source_folder || sourceFolder;
      currentVersion =
        result.display_name || result.version_id || currentVersion;
      renderVersion(currentVersion);
      refreshJavaStatus();
      syncFolderSidebarState();
      await Promise.all([
        refreshFolderState(),
        refreshVersionState(),
      ]);
      setLaunchStatus(result.message || "已切换文件夹");
    } else {
      folderSelectPending = false;
      selectedSourceFolder = previousSourceFolder;
      syncFolderSidebarState();
      setLaunchStatus(result.message || "未找到游戏文件", true);
    }
  } catch (error) {
    folderSelectPending = false;
    selectedSourceFolder = previousSourceFolder;
    syncFolderSidebarState();
    setLaunchStatus(error?.message || "切换失败", true);
  }
}

function getTextRect(element) {
  const range = document.createRange();

  if (element.firstChild) {
    range.selectNodeContents(element.firstChild);
  } else {
    range.selectNodeContents(element);
  }

  return range.getBoundingClientRect();
}

function animateVersionOpen() {
  closeCornerPanel();
  const sourceRect = getTextRect(versionChip);

  launcher.dataset.view = "version";

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return;
  }

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      const targetRect = getTextRect(versionHero);
      const dx =
        sourceRect.left +
        sourceRect.width / 2 -
        (targetRect.left + targetRect.width / 2);
      const dy =
        sourceRect.top +
        sourceRect.height / 2 -
        (targetRect.top + targetRect.height / 2);
      const scaleX = sourceRect.width / targetRect.width;
      const scaleY = sourceRect.height / targetRect.height;

      versionHero.getAnimations().forEach((animation) => animation.cancel());

      versionHero.animate(
        [
          {
            transform: `translate(${dx}px, ${dy}px) scale(${scaleX}, ${scaleY})`,
            opacity: 0.25,
          },
          {
            transform: "translate(0px, 0px) scale(1, 1)",
            opacity: 1,
          },
        ],
        {
          duration: 700,
          easing: "cubic-bezier(0.22, 0.61, 0.36, 1)",
          fill: "both",
        }
      );
    });
  });
}

versionChip.addEventListener("click", () => {
  animateVersionOpen();
});

versionHero.addEventListener("click", () => {
  versionHero.getAnimations().forEach((animation) => animation.cancel());
  launcher.dataset.view = "home";
});

function startRename() {
  isEditing = true;
  renameInput.value = currentVersion;
  renameRow.classList.add("is-editing");
  requestAnimationFrame(() => renameInput.focus());
}

async function commitRename() {
  if (!isEditing) {
    return;
  }

  isEditing = false;

  const nextVersion = renameInput.value.trim();

  if (nextVersion) {
    currentVersion = nextVersion;
  }

  renderVersion(currentVersion);
  renameRow.classList.remove("is-editing");
  renameInput.blur();
  await saveVersion(currentVersion);
  await Promise.all([
    refreshFolderState(),
    refreshVersionState(),
  ]);
}

renameButton.addEventListener("click", startRename);

renameInput.addEventListener("input", () => {
  renderVersion(renameInput.value.trim() || currentVersion);
});

renameInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    commitRename();
  }
});

renameInput.addEventListener("blur", commitRename);

cornerDownloadButton.addEventListener("click", openDownloadCenter);
launchRingButton.addEventListener("click", openDownloadTaskView);
downloadBackButton.addEventListener("click", handleDownloadBack);
downloadConfirmButton.addEventListener(
  "click",
  startSelectedDownload
);

downloadCategoryButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (downloadPollTimer) {
      return;
    }
    selectDownloadCategory(button.dataset.downloadCategory);
  });
});

downloadSearchButton.addEventListener("click", () => {
  loadContentSearch(1);
});

downloadSearchInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    loadContentSearch(1);
  }
});

downloadVersionInput.addEventListener("change", () => {
  contentGameVersion = downloadVersionInput.value.trim();
  contentVersionManual = true;
  loadContentSearch(1);
});

downloadVersionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    contentGameVersion = downloadVersionInput.value.trim();
    contentVersionManual = true;
    loadContentSearch(1);
  }
});

downloadPagePrevButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (contentSearchPage > 1) {
      loadContentSearch(contentSearchPage - 1);
    }
  });
});

downloadPageNextButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (contentSearchHasMore) {
      loadContentSearch(contentSearchPage + 1);
    }
  });
});

playerAvatar.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  openAccountMenu();
});

playerAvatar.addEventListener("click", () => {
  toggleAccountMenu();
});

verifyPremiumButton.addEventListener("click", () => {
  closeAccountMenu();
  handlePremiumLogin();
});

logoutAccountButton.addEventListener("click", () => {
  handleLogoutAccount();
});

cornerMenu.addEventListener("mouseenter", openCornerPanel);
cornerMenu.addEventListener("mouseleave", () => {
  cornerPanelCloseTimer = setTimeout(closeCornerPanel, 180);
});
cornerPanel.addEventListener("mouseenter", () => {
  clearTimeout(cornerPanelCloseTimer);
});
cornerTile.addEventListener("click", openCornerPanel);
cornerSettingsButton.addEventListener("click", openSettings);

settingsHero.addEventListener("click", () => {
  launcher.dataset.view = "home";
});

settingsNavItems.forEach((item) => {
  item.addEventListener("click", () => {
    activateSettingsTab(item.dataset.settingsTab);
  });
});

settingsBrowseButton.addEventListener("click", handleBrowseJava);
settingsWallpaperButton.addEventListener("click", handleChangeWallpaper);
saveSettingsButton.addEventListener("click", saveSettings);
settingsJavaStatus.addEventListener("click", installRequiredJava);
settingsJavaStatus.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    installRequiredJava();
  }
});

settingsDarkMode.addEventListener("change", () => {
  document.documentElement.dataset.theme = settingsDarkMode.checked
    ? "dark"
    : "light";
  if (selectedWallpaperUri) {
    launcher.style.backgroundImage = `url("${selectedWallpaperUri}")`;
  } else {
    launcher.style.backgroundImage = "";
  }
});

document.addEventListener("click", (event) => {
  if (
    isCornerPanelOpen &&
    !cornerPanel.contains(event.target) &&
    event.target !== cornerTile
  ) {
    closeCornerPanel();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && isCornerPanelOpen) {
    closeCornerPanel();
  }
});

document.addEventListener("click", (event) => {
  if (
    !accountMenu.contains(event.target) &&
    event.target !== playerAvatar
  ) {
    closeAccountMenu();
  }
});

document.addEventListener("contextmenu", (event) => {
  if (
    accountMenu.classList.contains("is-open") &&
    !accountMenu.contains(event.target) &&
    event.target !== playerAvatar
  ) {
    closeAccountMenu();
  }
});

window.addEventListener("resize", () => {
  if (accountMenu.classList.contains("is-open")) {
    positionAccountMenu();
  }
});

renderVersion(currentVersion);

async function bootstrapNative() {
  if (nativeBootstrapped || !window.pywebview?.api?.get_imported_folders) {
    return;
  }

  nativeBootstrapped = true;
  await Promise.all([loadAppState(), loadSettings()]);
  startLaunchPolling();
}

function bootstrapApp() {
  if (window.pywebview?.api?.get_imported_folders) {
    bootstrapNative();
    return;
  }

  window.addEventListener("pywebviewready", bootstrapNative);
  loadSavedVersion();
  loadSettings();
}

bootstrapApp();

function setLaunchStatus(message, isError = false) {
  if (
    message === lastLaunchStatusMessage &&
    isError === lastLaunchStatusError
  ) {
    return;
  }

  lastLaunchStatusMessage = message;
  lastLaunchStatusError = isError;

  if (message) {
    launchStatus.textContent = message;
    launchStatus.classList.toggle("is-error", isError);
  } else {
    launchStatus.textContent = "";
    launchStatus.classList.remove("is-error");
  }
}

function updateLaunchRing(progress) {
  const clamped = Math.max(0, Math.min(100, Number(progress) || 0));

  if (clamped === lastRingProgress) {
    return;
  }

  lastRingProgress = clamped;
  const circumference = 2 * Math.PI * 24;

  launchRingFill.style.strokeDashoffset = String(
    circumference * (1 - clamped / 100)
  );
}

async function handleImport() {
  if (!window.pywebview?.api?.import_folder) {
    setLaunchStatus("仅 exe 支持导入", true);
    return;
  }

  setLaunchStatus("正在导入");

  try {
    const result = await window.pywebview.api.import_folder();

    if (result.ok) {
      selectedSourceFolder = result.source_folder || "";
      currentVersion =
        result.display_name || result.version_id || currentVersion;
      renderVersion(currentVersion);
      await saveVersion(currentVersion);
      await refreshFolderState();
      await Promise.all([
        refreshVersionState(),
        loadAccount(),
      ]);
      setLaunchStatus(result.message || "已导入文件夹");
    } else {
      setLaunchStatus(result.message || "导入失败", true);
    }
  } catch (error) {
    setLaunchStatus(error?.message || "导入失败", true);
  }
}

async function handleLaunch() {
  if (!window.pywebview?.api?.launch_game) {
    setLaunchStatus("仅 exe 支持启动", true);
    return;
  }

  setLaunchStatus("准备启动");

  try {
    const result = await window.pywebview.api.launch_game();

    if (!result.ok) {
      setLaunchStatus(result.message || "启动失败", true);
    } else {
      stopRequested = false;
      isGameRunning = true;
      playButton.classList.add("is-running");
      playButton.setAttribute("aria-label", "关闭游戏");
    }
  } catch (error) {
    setLaunchStatus(error?.message || "启动失败", true);
  }
}

async function handlePlayButton() {
  if (isGameRunning) {
    if (!window.pywebview?.api?.stop_game) {
      setLaunchStatus("仅 exe 支持关闭", true);
      return;
    }

    setLaunchStatus("正在关闭");

    try {
      const result = await window.pywebview.api.stop_game();

      if (!result.ok) {
        setLaunchStatus(result.message || "关闭失败", true);
      } else {
        stopRequested = true;
        isGameRunning = false;
        playButton.classList.remove("is-running");
        playButton.setAttribute("aria-label", "开始游戏");
      }
    } catch (error) {
      setLaunchStatus(error?.message || "关闭失败", true);
    }

    return;
  }

  await handleLaunch();
}

async function updateLaunchLog(status) {
  const shouldShow =
    status.state === "launching" ||
    status.state === "running" ||
    status.state === "stopping";

  if (shouldShow) {
    launchLogPanel.hidden = false;
  }

  if (!window.pywebview?.api?.get_launch_log) {
    return;
  }

  try {
    const log = await window.pywebview.api.get_launch_log();
    if (log.revision === lastLaunchLogRevision) {
      return;
    }

    lastLaunchLogRevision = log.revision;
    launchLogOutput.textContent = (log.lines || []).join("\n");
    launchLogOutput.scrollTop = launchLogOutput.scrollHeight;
  } catch {
    // Ignore transient log polling failures.
  }
}

async function pollLaunchStatus() {
  if (!window.pywebview?.api?.get_launch_status) {
    return;
  }

  try {
    const status = await window.pywebview.api.get_launch_status();
    const progress = Number(status.progress || 0);
    const hasError = Boolean(status.error);
    let nextGameRunning;

    if (hasError) {
      stopRequested = false;
      nextGameRunning = false;
    } else if (stopRequested) {
      if (!status.running && (progress === 0 || progress >= 100)) {
        stopRequested = false;
      }
      nextGameRunning = false;
    } else {
      const idle = !status.running && progress === 0;
      const exited = !status.running && progress >= 100;
      nextGameRunning = !idle && !exited;
    }

    if (nextGameRunning !== isGameRunning) {
      isGameRunning = nextGameRunning;
      playButton.classList.toggle("is-running", isGameRunning);
      playButton.setAttribute(
        "aria-label",
        isGameRunning ? "关闭游戏" : "开始游戏"
      );
    }
    if (!downloadRingVisible) {
      updateLaunchRing(status.progress || 0);

      if (status.error) {
        setLaunchStatus(status.error, true);
      } else if (status.message) {
        setLaunchStatus(status.message);
      }
    }

    await updateLaunchLog(status);
  } catch {
    // Ignore transient polling failures.
  }
}

function startLaunchPolling() {
  if (!window.pywebview?.api?.get_launch_status || launchPollTimer) {
    return;
  }

  launchPollTimer = setInterval(pollLaunchStatus, 600);
  pollLaunchStatus();
}

importButton.addEventListener("click", handleImport);
playButton.addEventListener("click", handlePlayButton);
