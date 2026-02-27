/* =================================================================
   LicitaAI — app.js
   Countdown, checklist, copy, tabs, search debounce, filters
   ================================================================= */
(function () {
  "use strict";

  /* ---------- Countdown Timer ---------- */
  var cd = document.getElementById("countdown");
  if (cd) {
    var deadline = new Date(cd.dataset.deadline);
    var $d = document.getElementById("cd-days");
    var $h = document.getElementById("cd-hours");
    var $m = document.getElementById("cd-mins");
    var $s = document.getElementById("cd-secs");

    function tick() {
      var diff = Math.max(0, Math.floor((deadline - new Date()) / 1000));
      var d = Math.floor(diff / 86400); diff %= 86400;
      var h = Math.floor(diff / 3600);  diff %= 3600;
      var m = Math.floor(diff / 60);    diff %= 60;
      if ($d) $d.textContent = String(d).padStart(2, "0");
      if ($h) $h.textContent = String(h).padStart(2, "0");
      if ($m) $m.textContent = String(m).padStart(2, "0");
      if ($s) $s.textContent = String(diff).padStart(2, "0");
    }
    tick();
    setInterval(tick, 1000);
  }

  /* ---------- Checklist localStorage ---------- */
  var wrapper = document.querySelector("[data-opp-id]");
  var oppId = wrapper ? wrapper.dataset.oppId : null;
  var STORE_KEY = oppId ? "la_chk_" + oppId : null;

  function loadState() {
    if (!STORE_KEY) return {};
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; }
    catch (e) { return {}; }
  }
  function saveState(s) { if (STORE_KEY) localStorage.setItem(STORE_KEY, JSON.stringify(s)); }

  document.querySelectorAll(".chk-item input[type='checkbox']").forEach(function (cb) {
    var id = cb.dataset.reqId;
    var state = loadState();
    if (state[id]) { cb.checked = true; cb.closest(".chk-item").classList.add("checked"); }
    cb.addEventListener("change", function () {
      var s = loadState();
      s[id] = cb.checked;
      saveState(s);
      cb.closest(".chk-item").classList.toggle("checked", cb.checked);
    });
  });

  /* ---------- Copy button ---------- */
  var copyBtn = document.getElementById("btn-copy");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      var title = document.getElementById("opp-title");
      var text = (title ? title.textContent.trim() : "") + "\n" + location.href;
      navigator.clipboard.writeText(text).then(function () {
        var orig = copyBtn.innerHTML;
        copyBtn.innerHTML = '<i class="bi bi-check2 me-1"></i>Copiado!';
        setTimeout(function () { copyBtn.innerHTML = orig; }, 1800);
      });
    });
  }

  /* ---------- Copy AI summary ---------- */
  var copySummary = document.getElementById("btn-copy-summary");
  if (copySummary) {
    copySummary.addEventListener("click", function () {
      var el = document.getElementById("ai-summary-content");
      if (!el) return;
      navigator.clipboard.writeText(el.innerText.trim()).then(function () {
        var orig = copySummary.innerHTML;
        copySummary.innerHTML = '<i class="bi bi-check2 me-1"></i>Copiado!';
        setTimeout(function () { copySummary.innerHTML = orig; }, 1800);
      });
    });
  }

  /* ---------- Tab hash routing + ARIA ---------- */
  var tabs = document.querySelectorAll(".la-tabs a[data-bs-toggle='tab']");
  tabs.forEach(function (link) {
    link.setAttribute("role", "tab");
    link.addEventListener("shown.bs.tab", function () {
      history.replaceState(null, "", link.getAttribute("href"));
    });
  });
  if (location.hash) {
    var target = document.querySelector('.la-tabs a[href="' + location.hash + '"]');
    if (target) { var t = new bootstrap.Tab(target); t.show(); }
  }

  /* ---------- Search debounce (list page) ---------- */
  var searchInput = document.getElementById("filter-q");
  if (searchInput) {
    var timer;
    searchInput.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        searchInput.form.submit();
      }, 600);
    });
  }

  /* ---------- Filter chip removal ---------- */
  document.querySelectorAll(".filter-chip a[data-remove]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      var param = btn.dataset.remove;
      var url = new URL(location.href);
      url.searchParams.delete(param);
      url.searchParams.delete("page");
      location.href = url.toString();
    });
  });

  /* ---------- Collapse toggle arrow ---------- */
  document.querySelectorAll("[data-bs-toggle='collapse']").forEach(function (el) {
    var target = document.querySelector(el.dataset.bsTarget);
    if (target) {
      target.addEventListener("shown.bs.collapse", function () { el.setAttribute("aria-expanded", "true"); });
      target.addEventListener("hidden.bs.collapse", function () { el.setAttribute("aria-expanded", "false"); });
    }
  });

})();
