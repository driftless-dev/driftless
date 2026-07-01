// driftless site interactions — vanilla JS, no deps.
(function () {
  "use strict";

  /* ---- mobile nav toggle ---- */
  var nav = document.getElementById("nav");
  var toggle = document.getElementById("navToggle");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      nav.classList.toggle("open");
    });
    nav.querySelectorAll(".nav-links a, .landing-links a").forEach(function (a) {
      a.addEventListener("click", function () {
        nav.classList.remove("open");
      });
    });
  }

  /* ---- code tabs (landing) ---- */
  document.querySelectorAll(".tabs-bar").forEach(function (bar) {
    var tabs = bar.querySelectorAll(".tab");
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        var id = tab.getAttribute("data-tab");
        tabs.forEach(function (t) { t.classList.remove("active"); });
        tab.classList.add("active");
        var root = bar.closest(".code-tabs");
        root.querySelectorAll(".tab-panel").forEach(function (p) {
          p.classList.toggle("active", p.id === id);
        });
      });
    });
  });

  /* ---- copy-to-clipboard buttons ---- */
  document.querySelectorAll(".copy-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var host = btn.closest(".has-copy");
      if (!host) return;
      var code = host.querySelector("code, .term-body");
      var text = code ? code.innerText : host.innerText;
      var done = function () {
        var prev = btn.textContent;
        btn.textContent = "copied";
        btn.classList.add("copied");
        setTimeout(function () {
          btn.textContent = prev;
          btn.classList.remove("copied");
        }, 1400);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(done);
      } else {
        var ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); } catch (e) {}
        document.body.removeChild(ta);
        done();
      }
    });
  });

  /* ---- docs sidebar active-link on scroll ---- */
  var sidebar = document.getElementById("sidebar");
  if (sidebar) {
    var links = Array.prototype.slice.call(sidebar.querySelectorAll("a[href^='#']"));
    var sections = links
      .map(function (l) { return document.querySelector(l.getAttribute("href")); })
      .filter(Boolean);

    var setActive = function (id) {
      links.forEach(function (l) {
        l.classList.toggle("active", l.getAttribute("href") === "#" + id);
      });
    };

    if ("IntersectionObserver" in window && sections.length) {
      var visible = new Set();
      var obs = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) visible.add(e.target.id);
          else visible.delete(e.target.id);
        });
        // pick the topmost visible section
        var topmost = sections.filter(function (s) { return visible.has(s.id); })[0];
        if (topmost) setActive(topmost.id);
      }, { rootMargin: "-80px 0px -70% 0px", threshold: 0 });
      sections.forEach(function (s) { obs.observe(s); });
    }

    // clicking a link sets it active immediately
    links.forEach(function (l) {
      l.addEventListener("click", function () {
        setActive(l.getAttribute("href").slice(1));
      });
    });
  }
})();
