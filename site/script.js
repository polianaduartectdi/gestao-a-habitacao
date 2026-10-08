(function () {
  var html = document.documentElement;

  try {
    if (localStorage.getItem("tema") === "escuro") {
      html.setAttribute("data-theme", "dark");
    }
  } catch (e) {}

  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;

    function atualizar() {
      var escuro = html.getAttribute("data-theme") === "dark";
      btn.textContent = escuro ? "Modo claro" : "Modo escuro";
    }

    btn.addEventListener("click", function () {
      var escuro = html.getAttribute("data-theme") === "dark";
      if (escuro) {
        html.removeAttribute("data-theme");
      } else {
        html.setAttribute("data-theme", "dark");
      }
      try {
        localStorage.setItem("tema", escuro ? "claro" : "escuro");
      } catch (e) {}
      atualizar();
    });

    atualizar();
  });
})();