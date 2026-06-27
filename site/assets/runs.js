/* driftless run viewer — renders .driftless/migrations/*.json */
(function () {
  "use strict";

  var COLORS = ["#6ea8fe", "#43e0c4", "#f5b454", "#ff6b81", "#8b7bff", "#46d39a", "#e7eaf3"];
  var METRIC_LABEL = "F1";

  var fileInput = document.getElementById("fileInput");
  var runSelect = document.getElementById("runSelect");
  var loadSample = document.getElementById("loadSample");
  var emptyState = document.getElementById("emptyState");
  var runPanel = document.getElementById("runPanel");
  var dropZone = document.getElementById("dropZone");

  function pct(v) {
    if (v == null || isNaN(v)) return "n/a";
    return (v * 100).toFixed(1) + "%";
  }

  function num(v, d) {
    if (v == null || isNaN(v)) return "n/a";
    return Number(v).toFixed(d == null ? 3 : d);
  }

  function isRefine(data) {
    return data.current_model === data.target_model;
  }

  function statusClass(s) {
    if (s === "pass" || s === "model_change_only") return "pass";
    if (s === "partial") return "partial";
    if (s === "blocked") return "blocked";
    return "neutral";
  }

  function primaryOf(metrics) {
    if (!metrics) return null;
    if (metrics.f1 != null) return metrics.f1;
    if (metrics.score != null) return metrics.score;
    return metrics.accuracy;
  }

  function renderRun(data) {
    emptyState.hidden = true;
    runPanel.hidden = false;

    var refine = isRefine(data);
    document.getElementById("runTitle").textContent = data.workflow || "unknown";
    document.getElementById("runSubtitle").textContent = refine
      ? "Refine · model pinned to " + data.current_model + " · " + data.iterations + " iteration(s)"
      : "Migrate · " + data.current_model + " → " + data.target_model + " · " + data.iterations + " iteration(s)";

    var badge = document.getElementById("statusBadge");
    badge.textContent = data.status || "unknown";
    badge.className = "status-pill " + statusClass(data.status);

    renderKpis(data, refine);
    renderScorecard(data, refine);
    renderHoldout(data);
    renderMetricChart(data);
    renderClusterChart(data);
    renderAttemptLog(data);
    renderRemaining(data);
    renderThresholds(data);
  }

  function renderKpis(data, refine) {
    var baseP = primaryOf(data.baseline);
    var finalP = primaryOf(data.final);
    var holdP = data.holdout ? primaryOf(data.holdout) : null;
    var delta = baseP != null && finalP != null ? finalP - baseP : null;
    var attempts = (data.experiment_log || []).length;
    var accepted = (data.experiment_log || []).filter(function (a) { return a.accepted; }).length;

    var items = [
      { label: refine ? "Baseline F1" : "Current F1", value: num(baseP) },
      { label: refine ? "Refined F1" : "Migrated F1", value: num(finalP) },
      { label: "Δ tuning", value: delta != null ? (delta >= 0 ? "+" : "") + num(delta) : "n/a" },
      { label: "Holdout F1", value: holdP != null ? num(holdP) : "n/a" },
      { label: "Attempts", value: String(attempts) + " (" + accepted + " accepted)" },
    ];

    document.getElementById("kpiRow").innerHTML = items.map(function (k) {
      return '<div class="kpi"><div class="kpi-label">' + k.label + '</div><div class="kpi-value">' + k.value + '</div></div>';
    }).join("");
  }

  function renderScorecard(data, refine) {
    var rows = [
      { label: "F1", key: "f1", pct: false },
      { label: "Precision", key: "precision", pct: false },
      { label: "Recall", key: "recall", pct: false },
      { label: "Accuracy", key: "accuracy", pct: false },
      { label: "Schema error rate", key: "schema_error_rate", pct: true },
      { label: "Refusal rate", key: "refusal_rate", pct: true },
    ];

    var cols, headers;
    if (refine) {
      headers = ["Metric", "Current prompt", "Refined prompt"];
      cols = [data.baseline, data.final];
    } else {
      headers = ["Metric", "Current", "Target (orig)", "Target (migrated)"];
      cols = [data.baseline, data.naive_target, data.final];
    }

    var html = "<thead><tr>" + headers.map(function (h) { return "<th>" + h + "</th>"; }).join("") + "</tr></thead><tbody>";
    rows.forEach(function (r) {
      var vals = cols.map(function (m) { return m ? (r.pct ? pct(m[r.key]) : num(m[r.key])) : "n/a"; });
      if (vals.every(function (v) { return v === "n/a"; })) return;
      html += "<tr><td>" + r.label + "</td>" + vals.map(function (v) { return "<td>" + v + "</td>"; }).join("") + "</tr>";
    });
    html += "</tbody>";
    document.getElementById("scorecard").innerHTML = html;
  }

  function renderHoldout(data) {
    var sec = document.getElementById("holdoutSection");
    var checks = data.holdout_checks || [];
    if (!checks.length) {
      sec.hidden = true;
      return;
    }
    sec.hidden = false;
    document.getElementById("holdoutChecks").innerHTML = checks.map(function (c) {
      return '<li class="' + (c.passed ? "pass" : "fail") + '">' +
        (c.passed ? "✓" : "✗") + " " + c.name + ": " + (c.detail || "") + "</li>";
    }).join("");
  }

  function bestTrajectory(data) {
    var base = primaryOf(data.baseline);
    var log = data.experiment_log || [];
    var byIter = {};
    log.forEach(function (a) {
      if (!byIter[a.iteration]) byIter[a.iteration] = [];
      byIter[a.iteration].push(a);
    });
    var iters = Object.keys(byIter).map(Number).sort(function (a, b) { return a - b; });
    var best = base;
    var points = [{ x: -0.5, y: base, label: "baseline" }];
    var candidates = [];

    log.forEach(function (a) {
      candidates.push({ x: a.iteration, y: a.primary, accepted: a.accepted, error: a.error });
    });

    iters.forEach(function (i) {
      var accepted = byIter[i].filter(function (a) { return a.accepted; });
      if (accepted.length) {
        best = Math.max.apply(null, accepted.map(function (a) { return a.primary; }));
      }
      points.push({ x: i, y: best, label: "iter " + i });
    });

    return { points: points, candidates: candidates, holdout: data.holdout ? primaryOf(data.holdout) : null };
  }

  function renderMetricChart(data) {
    var traj = bestTrajectory(data);
    var series = [
      { name: "Best accepted", points: traj.points, color: "#43e0c4", strokeWidth: 2.5, dots: true },
    ];
    var extras = [];
    if (traj.holdout != null) {
      extras.push({ y: traj.holdout, label: "Holdout F1 " + num(traj.holdout), color: "#f5b454" });
    }
    document.getElementById("metricChart").innerHTML = lineChart({
      series: series,
      scatter: traj.candidates,
      hlines: extras,
      yMin: 0,
      yMax: 1,
      yFormat: function (v) { return num(v, 2); },
      xLabels: function (x) { return x < 0 ? "start" : String(Math.round(x)); },
    });
    document.getElementById("metricLegend").innerHTML = legendHtml([
      { color: "#43e0c4", name: "Best accepted (tuning " + METRIC_LABEL + ")" },
      { color: "rgba(110,168,254,.45)", name: "Rejected candidates" },
      { color: "#f5b454", name: "Holdout (final)" },
    ]);
  }

  function renderClusterChart(data) {
    var traj = data.cluster_trajectory || {};
    var keys = Object.keys(traj);
    if (!keys.length) {
      document.getElementById("clusterChart").innerHTML = '<p class="dim">No cluster history recorded.</p>';
      document.getElementById("clusterLegend").innerHTML = "";
      return;
    }
    var maxLen = Math.max.apply(null, keys.map(function (k) { return traj[k].length; }));
    var series = keys.map(function (k, i) {
      var pts = traj[k].map(function (count, idx) { return { x: idx, y: count }; });
      return { name: k.replace("misclassification:", ""), points: pts, color: COLORS[i % COLORS.length], strokeWidth: 2, dots: true };
    });
    var maxY = Math.max(1, Math.max.apply(null, keys.flatMap(function (k) { return traj[k]; })));
    document.getElementById("clusterChart").innerHTML = lineChart({
      series: series,
      yMin: 0,
      yMax: maxY + 1,
      yFormat: function (v) { return String(Math.round(v)); },
      xLabels: function (x) { return "iter " + x; },
    });
    document.getElementById("clusterLegend").innerHTML = legendHtml(
      series.map(function (s) { return { color: s.color, name: s.name }; })
    );
  }

  function renderAttemptLog(data) {
    var log = data.experiment_log || [];
    var originals = data.original_editable_files || {};
    if (!log.length) {
      document.getElementById("attemptLog").innerHTML = '<p class="dim">No attempts logged.</p>';
      return;
    }
    var byIter = {};
    log.forEach(function (a) {
      if (!byIter[a.iteration]) byIter[a.iteration] = [];
      byIter[a.iteration].push(a);
    });
    var html = "";
    Object.keys(byIter).map(Number).sort(function (a, b) { return a - b; }).forEach(function (iter) {
      var candidates = byIter[iter];
      html += '<div class="iter-block"><div class="iter-head"><span>Iteration ' + iter + '</span><span class="dim">' +
        candidates.length + " candidate(s)</span></div>";
      candidates.forEach(function (a, idx) {
        var badge, badgeClass;
        if (a.error) { badge = "error"; badgeClass = "error"; }
        else if (a.accepted) { badge = "accepted"; badgeClass = "accepted"; }
        else { badge = "rejected"; badgeClass = "rejected"; }
        html += '<div class="attempt">' +
          '<div class="attempt-meta">' +
          '<span class="attempt-badge ' + badgeClass + '">' + badge + '</span>' +
          '<span class="dim">candidate ' + (idx + 1) + '</span>' +
          '<span><strong>' + METRIC_LABEL + '</strong> ' + num(a.primary) + '</span>' +
          '<span>schema ' + (a.schema_error_rate != null ? pct(a.schema_error_rate) : "n/a") + '</span>' +
          '<span>diff ±' + (a.diff_size != null ? a.diff_size : "n/a") + '</span>' +
          '<span>' + (a.passed_tuning ? "passed tuning" : "below bar") + '</span>' +
          '</div>';
        if (a.error) {
          html += '<p class="attempt-rationale"><strong>Error:</strong> ' + escapeHtml(a.error) + '</p>';
        } else if (a.rationale) {
          html += '<p class="attempt-rationale">' + escapeHtml(a.rationale) + '</p>';
        }
        html += renderCandidateFiles(a, originals);
        html += '</div>';
      });
      html += '</div>';
    });
    document.getElementById("attemptLog").innerHTML = html;
  }

  function renderCandidateFiles(attempt, originals) {
    var contents = attempt.file_contents || {};
    var paths = attempt.files && attempt.files.length
      ? attempt.files
      : Object.keys(contents);
    if (!paths.length) {
      return '<p class="dim attempt-no-files">File contents not captured — re-run <code>migrate</code> or <code>refine</code> with a current driftless build.</p>';
    }
    var html = '<div class="candidate-files">';
    paths.forEach(function (path) {
      var proposed = contents[path];
      if (proposed == null) {
        html += '<p class="dim">' + escapeHtml(path) + ' — content not stored</p>';
        return;
      }
      var original = originals[path] != null ? originals[path] : "";
      var stats = diffStats(original, proposed);
      html += '<details class="file-diff"' + (attempt.accepted ? " open" : "") + '>' +
        '<summary><code>' + escapeHtml(path) + '</code> <span class="dim">(+' + stats.added + ' −' + stats.removed + ')</span></summary>' +
        '<pre class="diff-block">' + renderDiffHtml(original, proposed) + '</pre>' +
        '</details>';
    });
    html += '</div>';
    return html;
  }

  function diffStats(oldText, newText) {
    var lines = buildDiffLines(oldText || "", newText || "");
    var added = 0, removed = 0;
    lines.forEach(function (l) {
      if (l.t === "+") added++;
      if (l.t === "-") removed++;
    });
    return { added: added, removed: removed };
  }

  function buildDiffLines(oldText, newText) {
    var a = oldText.split("\n");
    var b = newText.split("\n");
    var n = a.length, m = b.length;
    // Myers-like DP is overkill; LCS table for typical prompt sizes is fine.
    var dp = Array(n + 1);
    for (var i = 0; i <= n; i++) {
      dp[i] = Array(m + 1).fill(0);
    }
    for (i = 1; i <= n; i++) {
      for (var j = 1; j <= m; j++) {
        dp[i][j] = a[i - 1] === b[j - 1]
          ? dp[i - 1][j - 1] + 1
          : Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
    var out = [];
    i = n; j = m;
    while (i > 0 || j > 0) {
      if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
        out.push({ t: " ", line: a[i - 1] });
        i--; j--;
      } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
        out.push({ t: "+", line: b[j - 1] });
        j--;
      } else {
        out.push({ t: "-", line: a[i - 1] });
        i--;
      }
    }
    out.reverse();
    return out;
  }

  function renderDiffHtml(oldText, newText) {
    return buildDiffLines(oldText, newText).map(function (row) {
      var cls = row.t === "+" ? "diff-add" : row.t === "-" ? "diff-del" : "diff-ctx";
      var prefix = row.t === " " ? " " : row.t;
      return '<span class="' + cls + '">' + prefix + escapeHtml(row.line) + "\n</span>";
    }).join("");
  }

  function renderRemaining(data) {
    var sec = document.getElementById("clustersSection");
    var clusters = data.remaining_clusters || [];
    if (!clusters.length) { sec.hidden = true; return; }
    sec.hidden = false;
    document.getElementById("remainingClusters").innerHTML = clusters.map(function (c) {
      return "<li><code>" + escapeHtml(c.key) + "</code> — " + c.count + " remaining (" + c.kind + ")</li>";
    }).join("");
  }

  function renderThresholds(data) {
    var sec = document.getElementById("thresholdsSection");
    var th = data.suggested_thresholds;
    if (!th || !Object.keys(th).length) { sec.hidden = true; return; }
    sec.hidden = false;
    var lines = ["thresholds:"];
    Object.keys(th).forEach(function (k) { lines.push("  " + k + ": " + th[k]); });
    document.getElementById("thresholdsBlock").textContent = lines.join("\n");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function legendHtml(items) {
    return items.map(function (it) {
      return '<span class="legend-item"><span class="legend-swatch" style="background:' + it.color + '"></span>' + escapeHtml(it.name) + '</span>';
    }).join("");
  }

  /** Simple responsive SVG line/scatter chart. */
  function lineChart(opts) {
    var W = 560, H = 200, pad = { t: 16, r: 16, b: 36, l: 44 };
    var iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
    var yMin = opts.yMin != null ? opts.yMin : 0;
    var yMax = opts.yMax != null ? opts.yMax : 1;
    var allX = [];
    (opts.series || []).forEach(function (s) {
      s.points.forEach(function (p) { allX.push(p.x); });
    });
    (opts.scatter || []).forEach(function (p) { allX.push(p.x); });
    var xMin = Math.min.apply(null, allX.concat([0]));
    var xMax = Math.max.apply(null, allX.concat([0]));

    function sx(x) {
      if (xMax === xMin) return pad.l + iw / 2;
      return pad.l + ((x - xMin) / (xMax - xMin)) * iw;
    }
    function sy(y) {
      var t = (y - yMin) / (yMax - yMin || 1);
      return pad.t + ih - t * ih;
    }

    var parts = ['<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="chart">'];

    // grid
    for (var g = 0; g <= 4; g++) {
      var gy = pad.t + (ih * g) / 4;
      var gv = yMax - ((yMax - yMin) * g) / 4;
      parts.push('<line x1="' + pad.l + '" y1="' + gy + '" x2="' + (W - pad.r) + '" y2="' + gy + '" stroke="#232838" stroke-width="1"/>');
      parts.push('<text x="' + (pad.l - 8) + '" y="' + (gy + 4) + '" fill="#6e7587" font-size="10" text-anchor="end" font-family="JetBrains Mono, monospace">' +
        opts.yFormat(gv) + "</text>");
    }

    (opts.hlines || []).forEach(function (hl) {
      parts.push('<line x1="' + pad.l + '" y1="' + sy(hl.y) + '" x2="' + (W - pad.r) + '" y2="' + sy(hl.y) + '" stroke="' + hl.color + '" stroke-width="1" stroke-dasharray="5,4" opacity=".85"/>');
    });

    (opts.series || []).forEach(function (s) {
      if (s.points.length < 2) return;
      var d = s.points.map(function (p, i) {
        return (i ? "L" : "M") + sx(p.x) + " " + sy(p.y);
      }).join(" ");
      parts.push('<path d="' + d + '" fill="none" stroke="' + s.color + '" stroke-width="' + (s.strokeWidth || 2) + '" stroke-linejoin="round" stroke-linecap="round"/>');
      if (s.dots) {
        s.points.forEach(function (p) {
          parts.push('<circle cx="' + sx(p.x) + '" cy="' + sy(p.y) + '" r="4" fill="' + s.color + '"/>');
        });
      }
    });

    (opts.scatter || []).forEach(function (p) {
      var col = p.error ? "#ff6b81" : (p.accepted ? "#43e0c4" : "rgba(110,168,254,.55)");
      parts.push('<circle cx="' + sx(p.x) + '" cy="' + sy(p.y) + '" r="3.5" fill="' + col + '" opacity=".9"/>');
    });

    // x labels at integer ticks
    var ticks = [];
    for (var tx = Math.ceil(xMin); tx <= Math.floor(xMax); tx++) ticks.push(tx);
    if (xMin < 0) ticks.unshift(xMin);
    ticks.forEach(function (tx) {
      parts.push('<text x="' + sx(tx) + '" y="' + (H - 10) + '" fill="#6e7587" font-size="10" text-anchor="middle" font-family="Inter, sans-serif">' +
        opts.xLabels(tx) + "</text>");
    });

    parts.push("</svg>");
    return parts.join("");
  }

  function loadJson(obj) {
    try {
      renderRun(obj);
    } catch (e) {
      alert("Could not render run: " + e.message);
    }
  }

  function readFile(file) {
    var reader = new FileReader();
    reader.onload = function () {
      try {
        loadJson(JSON.parse(reader.result));
      } catch (e) {
        alert("Invalid JSON file");
      }
    };
    reader.readAsText(file);
  }

  fileInput.addEventListener("change", function () {
    if (fileInput.files[0]) readFile(fileInput.files[0]);
  });

  loadSample.addEventListener("click", function () {
    fetch("assets/sample-run.json")
      .then(function (r) { return r.json(); })
      .then(loadJson)
      .catch(function () { alert("Could not load sample (open via driftless view or a local server)"); });
  });

  runSelect.addEventListener("change", function () {
    var wf = runSelect.value;
    if (!wf) return;
    fetch("/api/runs/" + encodeURIComponent(wf))
      .then(function (r) { return r.json(); })
      .then(loadJson)
      .catch(function () { alert("Could not load run"); });
  });

  // Drag and drop
  ["dragenter", "dragover"].forEach(function (ev) {
    document.addEventListener(ev, function (e) {
      e.preventDefault();
      dropZone.hidden = false;
    });
  });
  document.addEventListener("dragleave", function (e) {
    if (e.target === document || e.target === document.body) dropZone.hidden = true;
  });
  dropZone.addEventListener("drop", function (e) {
    e.preventDefault();
    dropZone.hidden = true;
    if (e.dataTransfer.files[0]) readFile(e.dataTransfer.files[0]);
  });

  // API mode (driftless view)
  fetch("/api/runs")
    .then(function (r) {
      if (!r.ok) throw new Error("no api");
      return r.json();
    })
    .then(function (list) {
      if (!list.length) return;
      runSelect.hidden = false;
      runSelect.innerHTML = '<option value="">Select run…</option>' +
        list.map(function (item) {
          return '<option value="' + escapeHtml(item.workflow) + '">' + escapeHtml(item.workflow) + " (" + escapeHtml(item.status) + ")</option>";
        }).join("");
      var params = new URLSearchParams(window.location.search);
      var wf = params.get("workflow");
      if (wf && list.some(function (i) { return i.workflow === wf; })) {
        runSelect.value = wf;
        runSelect.dispatchEvent(new Event("change"));
      } else if (list.length === 1) {
        runSelect.value = list[0].workflow;
        runSelect.dispatchEvent(new Event("change"));
      }
    })
    .catch(function () { /* static file mode */ });

  // Auto-load sample when opened as static file with hash
  if (window.location.hash === "#sample") {
    loadSample.click();
  }
})();
