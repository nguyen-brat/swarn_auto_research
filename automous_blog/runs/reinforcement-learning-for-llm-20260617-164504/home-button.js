(() => {
  const script = document.currentScript;
  const homeHref = script?.dataset.homeHref || "";
  if (!homeHref) return;

  const install = () => {
    if (document.querySelector(".swarn-home-link")) return;

    const headerInner = document.querySelector("header.header > div.header");
    if (!(headerInner instanceof HTMLElement)) return;

    const link = document.createElement("a");
    link.className = "swarn-home-link";
    link.href = homeHref;
    link.textContent = "Home";
    link.setAttribute("aria-label", "Back to research blog home");

    const desktopTarget = headerInner.querySelector(".right-group");
    if (desktopTarget instanceof HTMLElement) {
      desktopTarget.prepend(link);
      return;
    }
    headerInner.append(link);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
    return;
  }
  install();
})();
