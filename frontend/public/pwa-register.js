// The dashboard requires an authenticated network connection; PWA is install-only.
if ("serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" })
      .then(registration => {
        // Detect new active code while an existing installation is open.
        let initialized = !navigator.serviceWorker.controller;
        navigator.serviceWorker.addEventListener("controllerchange", () => {
          if (initialized) return;
          initialized = true;
          const banner = document.createElement("div");
          banner.setAttribute("role", "status");
          banner.className = "pwa-update-banner";
          banner.textContent = "A new Smart Meter Texas version is available. ";
          const button = document.createElement("button");
          button.textContent = "Reload";
          button.addEventListener("click", () => window.location.reload());
          banner.appendChild(button);
          document.body.appendChild(banner);
        });
        document.addEventListener("visibilitychange", () => {
          if (!document.hidden) registration.update().catch(() => {});
        });
      })
      .catch(() => {}); // PWA must never block normal dashboard usage.
  });
}
