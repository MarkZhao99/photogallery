function updateCountryIntroState(toggleButton, detailElement, expanded) {
  toggleButton.setAttribute("aria-expanded", expanded ? "true" : "false");
  toggleButton.textContent = expanded ? "收起导览" : "展开导览";
  detailElement.hidden = !expanded;
}

document.addEventListener("click", (event) => {
  const toggleButton = event.target.closest("[data-country-intro-toggle]");
  if (!toggleButton) {
    return;
  }

  const introRoot = toggleButton.closest(".country-intro");
  const detailElement = introRoot?.querySelector("[data-country-intro-detail]");
  if (!introRoot || !detailElement) {
    return;
  }

  const expanded = toggleButton.getAttribute("aria-expanded") === "true";
  updateCountryIntroState(toggleButton, detailElement, !expanded);
});
