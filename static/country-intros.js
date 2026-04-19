function updateCountryIntroState(toggleButton, detailElement, expanded) {
  const collapsedLabel = toggleButton.dataset.collapsedLabel || "展开导览";
  const expandedLabel = toggleButton.dataset.expandedLabel || "收起导览";

  toggleButton.setAttribute("aria-expanded", expanded ? "true" : "false");
  toggleButton.textContent = expanded ? expandedLabel : collapsedLabel;

  if (detailElement) {
    detailElement.hidden = !expanded;
  }
}

function activateDeferredImages(images) {
  images.forEach((image) => {
    if (image.dataset.activated === "true") {
      return;
    }

    const src = image.dataset.src || "";
    if (src) {
      image.setAttribute("src", src);
    }

    if (image.dataset.srcset) {
      image.setAttribute("srcset", image.dataset.srcset);
    }

    if (image.dataset.sizes) {
      image.setAttribute("sizes", image.dataset.sizes);
    }

    image.dataset.activated = "true";
  });
}

function collectDeferredImages(section) {
  return Array.from(section.querySelectorAll('img[data-deferred-photo="true"]'));
}

function hydrateCountryOverflow(section) {
  if (!section || section.getAttribute("data-country-hydrated") === "true") {
    return;
  }

  const deferredImages = collectDeferredImages(section);
  if (!deferredImages.length) {
    section.setAttribute("data-country-hydrated", "true");
    return;
  }

  activateDeferredImages(deferredImages);
  section.setAttribute("data-country-hydrated", "true");
}

function updateCountrySectionState(section, expanded) {
  if (!section) {
    return;
  }

  section.setAttribute("data-country-expanded", expanded ? "true" : "false");

  const overflowShell = section.querySelector("[data-country-overflow-shell]");
  if (overflowShell) {
    overflowShell.hidden = !expanded;
  }
}

function whenImageSettles(image) {
  if (image.complete) {
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    image.addEventListener("load", resolve, { once: true });
    image.addEventListener("error", resolve, { once: true });
  });
}

function waitForPreviewImages() {
  const previewImages = Array.from(
    document.querySelectorAll("[data-country-preview-grid] img:not([data-deferred-photo])")
  );

  return Promise.all(previewImages.map(whenImageSettles));
}

function nextHydrationTarget(queue) {
  return (
    queue.find(
      (section) =>
        section.getAttribute("data-country-hydrated") !== "true" &&
        section.getAttribute("data-country-priority") === "interactive"
    ) ||
    queue.find((section) => section.getAttribute("data-country-hydrated") !== "true")
  );
}

function scheduleOverflowHydration(countrySections) {
  const queue = countrySections.filter((section) => collectDeferredImages(section).length > 0);
  if (!queue.length) {
    return;
  }

  const runNext = () => {
    const section = nextHydrationTarget(queue);
    if (!section) {
      return;
    }

    if (section.getAttribute("data-country-priority") !== "interactive") {
      section.setAttribute("data-country-priority", "background");
    }

    hydrateCountryOverflow(section);
    window.setTimeout(runNext, 140);
  };

  const start = () => {
    window.setTimeout(runNext, 120);
  };

  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(start, { timeout: 900 });
    return;
  }

  window.setTimeout(start, 180);
}

function initializeCountrySections() {
  const countrySections = Array.from(document.querySelectorAll("[data-country-section]"));
  countrySections.forEach((section) => {
    if (!section.hasAttribute("data-country-expanded")) {
      section.setAttribute("data-country-expanded", "false");
    }

    if (!section.hasAttribute("data-country-priority")) {
      section.setAttribute("data-country-priority", "idle");
    }

    const overflowShell = section.querySelector("[data-country-overflow-shell]");
    if (overflowShell && section.getAttribute("data-country-expanded") !== "true") {
      overflowShell.hidden = true;
    }
  });

  waitForPreviewImages().then(() => {
    scheduleOverflowHydration(countrySections);
  });
}

document.addEventListener("click", (event) => {
  const toggleButton = event.target.closest("[data-country-expand-toggle], [data-country-intro-toggle]");
  if (!toggleButton) {
    return;
  }

  const introRoot = toggleButton.closest(".country-intro");
  const detailElement = introRoot?.querySelector("[data-country-intro-detail]");
  const section = toggleButton.closest("[data-country-section]");
  const expanded = toggleButton.getAttribute("aria-expanded") === "true";
  const nextExpanded = !expanded;

  updateCountryIntroState(toggleButton, detailElement, nextExpanded);
  updateCountrySectionState(section, nextExpanded);

  if (section) {
    section.setAttribute("data-country-priority", nextExpanded ? "interactive" : "idle");
    if (nextExpanded) {
      hydrateCountryOverflow(section);
    }
  }
});

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeCountrySections, { once: true });
} else {
  initializeCountrySections();
}
