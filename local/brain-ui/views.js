// Native workspace navigation: keep drafts, selection and live connections intact.
(() => {
  "use strict";
  const nav = document.getElementById("brainNav");
  if (!nav) return;
  const tabs = [...nav.querySelectorAll('[role="tab"]')];
  const panels = tabs.map(tab => document.getElementById(tab.getAttribute("aria-controls")));

  function show(panel, focusTab = false) {
    if (!panels.includes(panel)) return;
    panels.forEach((item, i) => {
      const active = item === panel;
      item.hidden = !active;
      tabs[i].setAttribute("aria-selected", String(active));
      tabs[i].tabIndex = active ? 0 : -1;
      if (active && focusTab) tabs[i].focus();
    });
    window.dispatchEvent(new CustomEvent("brain:view", { detail: panel.id }));
  }

  function openHash(hash) {
    let target;
    try { target = document.getElementById(decodeURIComponent(hash.slice(1))); }
    catch (_) { return false; } // a malformed external URL does not break navigation
    const panel = target && target.closest('[role="tabpanel"]');
    if (!panel) return false;
    show(panel);
    for (let parent = target; parent && parent !== panel; parent = parent.parentElement) {
      if (parent.tagName === "DETAILS") parent.open = true;
    }
    if (target !== panel) target.scrollIntoView({ block: "nearest" });
    return true;
  }

  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => {
      show(panels[i]);
      history.pushState(null, "", "#" + panels[i].id);
    });
    tab.addEventListener("keydown", event => {
      let next;
      if (event.key === "ArrowRight") next = (i + 1) % tabs.length;
      else if (event.key === "ArrowLeft") next = (i + tabs.length - 1) % tabs.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = tabs.length - 1;
      else return;
      event.preventDefault();
      show(panels[next], true);
      history.replaceState(null, "", "#" + panels[next].id);
    });
  });
  document.addEventListener("click", event => {
    const link = event.target.closest('a[href^="#"]');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const hash = link.getAttribute("href");
    if (!openHash(hash)) return;
    event.preventDefault();
    history.pushState(null, "", hash);
  });
  window.addEventListener("hashchange", () => openHash(location.hash) || show(panels[0]));
  window.addEventListener("popstate", () => openHash(location.hash) || show(panels[0]));
  if (!openHash(location.hash)) show(panels[0]);
})();
