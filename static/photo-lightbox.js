(function () {
  const lightboxDialog = document.getElementById("lightbox-dialog");
  const lightboxImage = document.getElementById("lightbox-image");
  const closeLightboxButton = document.getElementById("close-lightbox-button");
  const lightboxWallpaperButton = document.getElementById("lightbox-wallpaper-button");
  const lightboxDownloadButton = document.getElementById("lightbox-download-button");
  const lightboxCurrentImage = document.getElementById("lightbox-current-image");
  const lightboxWallpaperStatus = document.getElementById("lightbox-wallpaper-status");
  const lightboxHelperText = document.getElementById("lightbox-helper-text");
  const lightboxGuideLink = document.querySelector(".lightbox-guide-link");
  const helperOrigins = ["http://127.0.0.1:38941", "http://localhost:38941"];
  const isPublicPage = document.body.classList.contains("public-page");
  const mobileWidthQuery = window.matchMedia("(max-width: 720px)");
  const touchQuery = window.matchMedia("(pointer: coarse)");
  let helperState = {
    available: false,
    origin: null,
    checkedAt: 0,
  };

  if (!lightboxDialog || !lightboxImage || !closeLightboxButton) {
    return;
  }

  function buildDownloadName(imageUrl, imageAlt) {
    const fallbackName = (imageAlt || "wallpaper").trim().replace(/[\\/:*?"<>|]+/g, "-");

    try {
      const url = new URL(imageUrl, window.location.href);
      const pathname = url.pathname.split("/").filter(Boolean);
      const lastSegment = pathname[pathname.length - 1] || "";
      return decodeURIComponent(lastSegment) || fallbackName;
    } catch (error) {
      return fallbackName;
    }
  }

  function isMobileLightbox() {
    return mobileWidthQuery.matches || touchQuery.matches;
  }

  function setWallpaperStatus(message, kind) {
    if (!lightboxWallpaperStatus) {
      return;
    }

    lightboxWallpaperStatus.textContent = message || "";
    lightboxWallpaperStatus.dataset.state = kind || "";
  }

  function setCurrentImageLabel(imageUrl, imageAlt) {
    if (!lightboxCurrentImage) {
      return;
    }

    if (!imageUrl) {
      lightboxCurrentImage.textContent = "";
      return;
    }

    lightboxCurrentImage.textContent = `当前图片：${buildDownloadName(imageUrl, imageAlt)}`;
  }

  function updateWallpaperButtonState() {
    if (!lightboxWallpaperButton) {
      return;
    }

    if (!isPublicPage) {
      lightboxWallpaperButton.hidden = true;
      return;
    }

    const isMobileViewer = isMobileLightbox();
    lightboxWallpaperButton.hidden = isMobileLightbox();
    if (lightboxWallpaperStatus) {
      lightboxWallpaperStatus.hidden = isMobileViewer;
    }
    if (lightboxHelperText) {
      lightboxHelperText.hidden = isMobileViewer;
    }
    if (lightboxGuideLink) {
      lightboxGuideLink.hidden = isMobileViewer;
    }

    if (isMobileViewer) {
      return;
    }

    if (helperState.available) {
      lightboxWallpaperButton.disabled = false;
      lightboxWallpaperButton.textContent = "一键设为当前电脑壁纸";
      return;
    }

    lightboxWallpaperButton.disabled = false;
    lightboxWallpaperButton.textContent = "安装并启动桌面助手后可一键设壁纸";
  }

  async function readJsonResponse(response) {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      return response.json();
    }

    const text = await response.text();
    return { ok: false, error: text || `请求失败（${response.status}）` };
  }

  async function callHelper(path, options) {
    let lastError = null;

    for (const origin of helperOrigins) {
      try {
        const response = await fetch(`${origin}${path}`, options);
        const data = await readJsonResponse(response);
        helperState.available = true;
        helperState.origin = origin;
        helperState.checkedAt = Date.now();
        return { response, data, origin };
      } catch (error) {
        lastError = error;
      }
    }

    helperState.available = false;
    helperState.origin = null;
    helperState.checkedAt = Date.now();
    throw lastError || new Error("无法连接桌面助手。");
  }

  async function detectHelper(force = false) {
    if (!isPublicPage || !lightboxWallpaperButton || isMobileLightbox()) {
      return;
    }

    const checkedRecently = Date.now() - helperState.checkedAt < 5000;
    if (!force && checkedRecently) {
      updateWallpaperButtonState();
      return;
    }

    setWallpaperStatus("正在检测桌面助手...", "checking");
    updateWallpaperButtonState();

    try {
      const { response, data, origin } = await callHelper("/health", { method: "GET" });
      if (response.ok && data.ok) {
        helperState.available = true;
        helperState.origin = origin;
        setWallpaperStatus("桌面助手已连接，可以直接设为当前电脑壁纸。", "success");
      } else {
        helperState.available = false;
        setWallpaperStatus("未检测到可用桌面助手，请先下载安装并启动。", "idle");
      }
    } catch (error) {
      helperState.available = false;
      setWallpaperStatus("未检测到可用桌面助手，请先下载安装并启动。", "idle");
    }

    updateWallpaperButtonState();
  }

  function openLightbox(imageUrl, downloadUrl, imageAlt) {
    if (!imageUrl) {
      return;
    }

    lightboxImage.src = imageUrl;
    lightboxImage.alt = imageAlt || "";
    const effectiveDownloadUrl = downloadUrl || imageUrl;

    if (lightboxDownloadButton) {
      lightboxDownloadButton.href = effectiveDownloadUrl;
      lightboxDownloadButton.download = buildDownloadName(effectiveDownloadUrl, imageAlt);
    }

    setCurrentImageLabel(effectiveDownloadUrl, imageAlt);

    updateWallpaperButtonState();
    if (isPublicPage && !isMobileLightbox()) {
      setWallpaperStatus("", "");
      void detectHelper();
    } else {
      setWallpaperStatus("", "");
    }

    lightboxDialog.showModal();
  }

  function closeLightbox() {
    if (!lightboxDialog.open) {
      return;
    }

    lightboxDialog.close();
    lightboxImage.removeAttribute("src");
    lightboxImage.alt = "";

    if (lightboxDownloadButton) {
      lightboxDownloadButton.href = "#";
      lightboxDownloadButton.download = "";
    }

    setCurrentImageLabel("", "");
    setWallpaperStatus("", "");
  }

  document.addEventListener("click", (event) => {
    const guideLink = event.target.closest(".lightbox-guide-link");
    if (guideLink) {
      closeLightbox();
      return;
    }

    const trigger = event.target.closest("[data-action='open-lightbox']");
    if (!trigger) {
      return;
    }

    openLightbox(trigger.dataset.imageUrl, trigger.dataset.downloadUrl, trigger.dataset.imageAlt);
  });

  closeLightboxButton.addEventListener("click", closeLightbox);
  lightboxWallpaperButton?.addEventListener("click", async () => {
    if (isMobileLightbox()) {
      return;
    }

    const imageUrl = lightboxDownloadButton?.getAttribute("href") || lightboxImage.getAttribute("src");
    if (!imageUrl) {
      setWallpaperStatus("当前没有可设置的图片。", "error");
      return;
    }

    if (!helperState.available) {
      setWallpaperStatus("未检测到桌面助手，请先下载安装并启动。", "error");
      closeLightbox();
      document.getElementById("wallpaper-helper-guide")?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }

    lightboxWallpaperButton.disabled = true;
    lightboxWallpaperButton.textContent = "正在设置壁纸...";
    setWallpaperStatus("正在把当前图片发送给本地桌面助手...", "checking");

    try {
      const absoluteImageUrl = new URL(imageUrl, window.location.href).href;
      const imageAlt = lightboxImage.getAttribute("alt") || "";
      const imageName = buildDownloadName(absoluteImageUrl, imageAlt);
      const { response, data } = await callHelper("/set-wallpaper", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          image_url: absoluteImageUrl,
          image_name: imageName,
        }),
      });

      if (!response.ok || !data.ok) {
        throw new Error(data.error || "设置壁纸失败。");
      }

      const currentPaths = Array.isArray(data.current_paths) ? data.current_paths : [];
      const savedPath = typeof data.saved_path === "string" ? data.saved_path : "";
      const applied = savedPath && currentPaths.includes(savedPath);

      if (!applied) {
        throw new Error(`助手已收到 ${imageName}，但系统当前壁纸还不是这张图。`);
      }

      setWallpaperStatus(`已设为壁纸：${imageName}`, "success");
    } catch (error) {
      setWallpaperStatus(error.message || "设置壁纸失败。", "error");
    } finally {
      updateWallpaperButtonState();
    }
  });
  lightboxDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeLightbox();
  });
  lightboxDialog.addEventListener("click", (event) => {
    if (event.target === lightboxDialog) {
      closeLightbox();
    }
  });
})();
