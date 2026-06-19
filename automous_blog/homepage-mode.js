;(function () {
  var root = document.documentElement;
  var body = document.body;
  if (!root || !body) {
    return;
  }

  if (typeof localStorage !== "undefined") {
    try {
      localStorage.setItem("starlight-theme", "dark");
    } catch (_unusedErr) {
      // no-op
    }
  }

  root.classList.add("homepage-mode");
  body.classList.add("homepage-mode");
  root.dataset.theme = "dark";

  var main = document.querySelector("main[data-pagefind-body]");
  if (main) {
    var firstPanel = main.querySelector(".content-panel");
    var secondPanel = firstPanel ? firstPanel.nextElementSibling : null;

    if (firstPanel) {
      firstPanel.style.display = "none";
    }

    if (secondPanel && secondPanel.classList.contains("content-panel")) {
      secondPanel.style.marginTop = "0";
      secondPanel.style.paddingTop = "0";
    }
  }

  var hideSelectors = [
    "header.header",
    "nav.sidebar",
    ".right-sidebar-container",
    "starlight-theme-select",
    "site-search",
    "a[href='#_top'].astro-7q3lir66",
    "a[href='#_top']",
    ".pagination-links",
    ".meta",
    ".footer",
    "footer.sl-flex",
    "starlight-toc",
    "mobile-starlight-toc",
    "starlight-menu-button",
    ".mobile-preferences",
    ".social-icons",
    ".search-container",
    ".pagefind-ui",
    ".pagefind-ui__results-area",
    ".search-result-title",
  ];
  for (var i = 0; i < hideSelectors.length; i++) {
    var nodes = document.querySelectorAll(hideSelectors[i]);
    for (var j = 0; j < nodes.length; j++) {
      nodes[j].style.display = "none";
      nodes[j].setAttribute("aria-hidden", "true");
    }
  }
})();
