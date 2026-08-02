// driftless site interactions — vanilla JS, no deps.
(function () {
  "use strict";

  /* ---- mobile nav toggle ---- */
  var nav = document.getElementById("nav");
  var toggle = document.getElementById("navToggle");
  if (toggle && nav) {
    var setMenuOpen = function (open) {
      nav.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    };
    toggle.addEventListener("click", function () {
      setMenuOpen(!nav.classList.contains("open"));
    });
    nav.querySelectorAll(".nav-links a, .landing-links a").forEach(function (a) {
      a.addEventListener("click", function () {
        setMenuOpen(false);
      });
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && nav.classList.contains("open")) {
        setMenuOpen(false);
        toggle.focus();
      }
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
  document.querySelectorAll(".copy-btn").forEach(function (btn, index) {
    if (!btn.getAttribute("aria-label")) {
      var host = btn.closest(".has-copy");
      var code = host ? host.querySelector("code, .term-body") : null;
      var language = code && code.className.match(/language-([a-z0-9_-]+)/i);
      var description = language ? language[1] + " code" : "code block " + (index + 1);
      btn.setAttribute("aria-label", "Copy " + description + " to clipboard");
    }
    btn.addEventListener("click", function () {
      var host = btn.closest(".has-copy");
      if (!host) return;
      var code = host.querySelector("code, .term-body");
      var text = code ? code.innerText : host.innerText;
      var done = function () {
        var prev = btn.textContent;
        var prevLabel = btn.getAttribute("aria-label");
        btn.textContent = "copied";
        btn.setAttribute("aria-label", "Copied to clipboard");
        btn.classList.add("copied");
        setTimeout(function () {
          btn.textContent = prev;
          btn.setAttribute("aria-label", prevLabel);
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
