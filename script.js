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

let currentVersion = "1.21.4";
let isEditing = false;
let isGameRunning = false;
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

renderVersion(currentVersion);

if (window.pywebview?.api?.load_version) {
  loadSavedVersion();
} else {
  window.addEventListener("pywebviewready", loadSavedVersion);
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
      currentVersion = result.version_id;
      renderVersion(currentVersion);
      await saveVersion(currentVersion);
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

    isGameRunning = Boolean(status.running);
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

importButton.addEventListener("click", handleImport);
playButton.addEventListener("click", handlePlayButton);

setInterval(pollLaunchStatus, 600);
