const launcher = document.querySelector(".launcher");
const versionChip = document.querySelector(".version-name");
const versionHero = document.querySelector(".version-hero");
const renameButton = document.querySelector(".rename-button");
const renameRow = document.querySelector(".rename-row");
const renameInput = document.querySelector(".rename-input");
const importButton = document.querySelector(".import-button");
const playButton = document.querySelector(".play-button");
const launchRingFill = document.querySelector(".launch-ring-fill");
const launchStatus = document.querySelector(".launch-status");
const folderList = document.querySelector(".folder-list");
const versionList = document.querySelector(".version-list");
const playerName = document.querySelector(".player-name");
const playerAvatar = document.querySelector(".player-avatar");
const accountMenu = document.querySelector(".account-menu");
const verifyPremiumButton = document.querySelector(".verify-premium-button");

let currentVersion = "1.21.4";
let isEditing = false;
let isGameRunning = false;
let stopRequested = false;
let premiumLoginPending = false;
let premiumPollTimer = null;
let launchPollTimer = null;
let importedFolders = [];
let selectedSourceFolder = "";
let importedVersions = [];
let selectedVersionId = "";
const STORAGE_KEY = "minecraft-launcher-version";

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
  } else {
    playerName.textContent = "Steve";
    playerAvatar.src = "assets/player-avatar.png";
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

function closeAccountMenu() {
  accountMenu.classList.remove("is-open");
}

function updateVerifyButton() {
  verifyPremiumButton.disabled = premiumLoginPending;
  verifyPremiumButton.textContent = premiumLoginPending
    ? "验证中..."
    : "正版验证";
}

async function handlePremiumLogin() {
  if (!window.pywebview?.api?.start_premium_login) {
    setLaunchStatus("请在打包后的 exe 中验证正版", true);
    return;
  }

  premiumLoginPending = true;
  updateVerifyButton();
  setLaunchStatus("正在打开微软授权页面");

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

    setLaunchStatus(result.message || "请在浏览器中完成微软授权");
    startPremiumStatusPolling();
  } catch (error) {
    premiumLoginPending = false;
    updateVerifyButton();
    setLaunchStatus(error?.message || "正版验证失败", true);
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

function renderFolderSidebar() {
  if (!folderList) {
    return;
  }

  folderList.replaceChildren();

  for (const folder of importedFolders) {
    if (!folder.source_folder) {
      continue;
    }

    const item = document.createElement("button");
    item.type = "button";
    item.className = "folder-item";
    item.dataset.sourceFolder = folder.source_folder;

    const name = document.createElement("span");
    name.className = "folder-name";
    name.textContent =
      folder.folder_name ||
      folder.display_name ||
      folder.version_id ||
      folder.source_folder;
    item.appendChild(name);

    if (folder.source_folder === selectedSourceFolder) {
      item.classList.add("is-active");
    }

    item.addEventListener("click", () => {
      handleFolderSelect(folder.source_folder);
    });
    folderList.appendChild(item);
  }
}

function renderVersionSidebar() {
  if (!versionList) {
    return;
  }

  versionList.replaceChildren();

  for (const version of importedVersions) {
    if (!version.version_id) {
      continue;
    }

    const item = document.createElement("button");
    item.type = "button";
    item.className = "version-sidebar-item";
    item.dataset.versionId = version.version_id;

    const label = document.createElement("span");
    label.className = "version-sidebar-label";
    label.textContent =
      version.display_name || version.version_id;
    item.appendChild(label);

    if (version.version_id === selectedVersionId) {
      item.classList.add("is-active");
    }

    item.addEventListener("click", () => {
      handleVersionSelect(version.version_id);
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
    ]);
  } catch {
    // Ignore transient startup failures; the UI keeps its default state.
  }
}

async function handleVersionSelect(versionId) {
  if (
    !window.pywebview?.api?.select_version ||
    !selectedSourceFolder ||
    !versionId
  ) {
    return;
  }

  if (isEditing) {
    isEditing = false;
    renameRow.classList.remove("is-editing");
    renameInput.blur();
  }

  setLaunchStatus("正在检测游戏版本");

  try {
    const result = await window.pywebview.api.select_version(
      selectedSourceFolder,
      versionId
    );

    if (result.ok) {
      currentVersion =
        result.display_name || result.version_id || currentVersion;
      renderVersion(currentVersion);
      await refreshVersionState();
      setLaunchStatus(result.message || "已切换版本");
    } else {
      setLaunchStatus(result.message || "未找到游戏版本", true);
    }
  } catch (error) {
    setLaunchStatus(error?.message || "切换版本失败", true);
  }
}

async function handleFolderSelect(sourceFolder) {
  if (!window.pywebview?.api?.select_folder || !sourceFolder) {
    return;
  }

  if (isEditing) {
    isEditing = false;
    renameRow.classList.remove("is-editing");
    renameInput.blur();
  }

  setLaunchStatus("正在检测游戏文件");

  try {
    const result = await window.pywebview.api.select_folder(sourceFolder);

    if (result.ok) {
      selectedSourceFolder = result.source_folder || sourceFolder;
      currentVersion =
        result.display_name || result.version_id || currentVersion;
      renderVersion(currentVersion);
      await refreshFolderState();
      await refreshVersionState();
      setLaunchStatus(result.message || "已切换文件夹");
    } else {
      setLaunchStatus(result.message || "未找到游戏文件", true);
    }
  } catch (error) {
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

playerAvatar.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  openAccountMenu();
});

verifyPremiumButton.addEventListener("click", () => {
  closeAccountMenu();
  handlePremiumLogin();
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

if (window.pywebview?.api?.get_imported_folders) {
  loadAppState();
  startLaunchPolling();
} else {
  window.addEventListener("pywebviewready", () => {
    if (window.pywebview?.api?.get_imported_folders) {
      loadAppState();
      startLaunchPolling();
    }
  });
  loadSavedVersion();
}

function setLaunchStatus(message, isError = false) {
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
  const circumference = 2 * Math.PI * 24;

  launchRingFill.style.strokeDashoffset = String(
    circumference * (1 - clamped / 100)
  );
}

async function handleImport() {
  if (!window.pywebview?.api?.import_folder) {
    setLaunchStatus("请在打包后的 exe 中导入文件夹", true);
    return;
  }

  setLaunchStatus("正在导入文件夹");

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
    setLaunchStatus("请在打包后的 exe 中启动游戏", true);
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
      setLaunchStatus("请在打包后的 exe 中关闭游戏", true);
      return;
    }

    setLaunchStatus("正在关闭游戏");

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

async function pollLaunchStatus() {
  if (!window.pywebview?.api?.get_launch_status) {
    return;
  }

  try {
    const status = await window.pywebview.api.get_launch_status();
    const progress = Number(status.progress || 0);
    const hasError = Boolean(status.error);

    if (hasError) {
      stopRequested = false;
      isGameRunning = false;
    } else if (stopRequested) {
      if (!status.running && (progress === 0 || progress >= 100)) {
        stopRequested = false;
      }
      isGameRunning = false;
    } else {
      const idle = !status.running && progress === 0;
      const exited = !status.running && progress >= 100;
      isGameRunning = !idle && !exited;
    }

    playButton.classList.toggle("is-running", isGameRunning);
    playButton.setAttribute(
      "aria-label",
      isGameRunning ? "关闭游戏" : "开始游戏"
    );
    updateLaunchRing(status.progress || 0);

    if (status.error) {
      setLaunchStatus(status.error, true);
    } else if (status.message) {
      setLaunchStatus(status.message);
    }
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
