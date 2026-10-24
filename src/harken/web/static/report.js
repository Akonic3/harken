document.querySelectorAll("[data-print]").forEach((el) =>
  el.addEventListener("click", () => window.print())
);
