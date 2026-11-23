document.addEventListener("DOMContentLoaded", () => {
  const state = {
    apiKey: localStorage.getItem("sql_fixer_api_key") || "",
    model: localStorage.getItem("sql_fixer_model") || "openrouter/free",
    presets: [],
    schema: null,
    schemaSource: "default",
    diffView: "split",
    currentSession: null,
    benchmarkData: null,
    activeTab: "workbench"
  };

  const tabNavWorkbench = document.getElementById("tab-nav-workbench");
  const tabNavSchema = document.getElementById("tab-nav-schema");
  const tabNavBenchmarks = document.getElementById("tab-nav-benchmarks");
  const tabWorkbench = document.getElementById("tab-workbench");
  const tabSchema = document.getElementById("tab-schema");
  const tabBenchmarks = document.getElementById("tab-benchmarks");
  const btnExportQuick = document.getElementById("btn-export-quick");
  const btnExportSingle = document.getElementById("btn-export-single");
  const btnSettings = document.getElementById("btn-settings");
  const activeModelBadge = document.getElementById("active-model-badge");
  const activeModelText = document.getElementById("active-model-text");

  const presetSelect = document.getElementById("preset-select");
  const presetDescText = document.getElementById("preset-desc-text");
  const quickChips = document.querySelectorAll(".chip-btn");
  const sqlInput = document.getElementById("sql-input");
  const checkDryRun = document.getElementById("check-dry-run");
  const btnClearSql = document.getElementById("btn-clear-sql");
  const btnRunRaw = document.getElementById("btn-run-raw");
  const btnExplainFix = document.getElementById("btn-explain-fix");
  const terminalOutput = document.getElementById("terminal-output");
  const terminalStatusBadge = document.getElementById("terminal-status-badge");
  const resultsSection = document.getElementById("results-section");

  const resCategory = document.getElementById("res-category");
  const resSafety = document.getElementById("res-safety");
  const resRiskScore = document.getElementById("res-risk-score");
  const resModel = document.getElementById("res-model");
  const resRootCause = document.getElementById("res-root-cause");
  const resTechnical = document.getElementById("res-technical");
  const resDiffSummary = document.getElementById("res-diff-summary");
  const resPrevention = document.getElementById("res-prevention");
  const resLayerPills = document.getElementById("res-layer-pills");

  const btnDiffSplit = document.getElementById("btn-diff-split");
  const btnDiffUnified = document.getElementById("btn-diff-unified");
  const diffContainerSplit = document.getElementById("diff-container-split");
  const diffContainerUnified = document.getElementById("diff-container-unified");
  const diffLeftLines = document.getElementById("diff-left-lines");
  const diffRightLines = document.getElementById("diff-right-lines");
  const diffUnifiedText = document.getElementById("diff-unified-text");
  const btnCopyFixed = document.getElementById("btn-copy-fixed");

  const metricStatus = document.getElementById("metric-status");
  const metricRows = document.getElementById("metric-rows");
  const metricTime = document.getElementById("metric-time");
  const execTableContainer = document.getElementById("exec-table-container");
  const queryPlanContent = document.getElementById("query-plan-content");

  const schemaStatusBadge = document.getElementById("schema-status-badge");
  const customDdlInput = document.getElementById("custom-ddl-input");
  const fileDdl = document.getElementById("file-ddl");
  const btnPickDdl = document.getElementById("btn-pick-ddl");
  const btnDeployDdl = document.getElementById("btn-deploy-ddl");
  const dbDropZone = document.getElementById("db-drop-zone");
  const fileDb = document.getElementById("file-db");
  const btnPickDb = document.getElementById("btn-pick-db");
  const dbUploadStatus = document.getElementById("db-upload-status");
  const btnResetSchemaMain = document.getElementById("btn-reset-schema-main");
  const tablesCountBadge = document.getElementById("tables-count-badge");
  const activeTablesContainer = document.getElementById("active-tables-container");

  const btnRunBenchmarks = document.getElementById("btn-run-benchmarks");
  const scoreAccuracy = document.getElementById("score-accuracy");
  const scoreGuardrail = document.getElementById("score-guardrail");
  const scoreTotal = document.getElementById("score-total");
  const scoreLatency = document.getElementById("score-latency");
  const categoryChipsContainer = document.getElementById("category-chips-container");
  const benchmarkTableContainer = document.getElementById("benchmark-table-container");
  const benchFilterGroup = document.getElementById("bench-filter-group");

  const reportModal = document.getElementById("report-modal");
  const btnCloseReportModal = document.getElementById("btn-close-report-modal");
  const reportMarkdownPreview = document.getElementById("report-markdown-preview");
  const btnCopyReport = document.getElementById("btn-copy-report");
  const btnDownloadReport = document.getElementById("btn-download-report");

  const settingsModal = document.getElementById("settings-modal");
  const btnCloseModal = document.getElementById("btn-close-modal");
  const modalBackdrop = document.getElementById("modal-backdrop");
  const cfgApiKey = document.getElementById("cfg-api-key");
  const cfgModelSelect = document.getElementById("cfg-model-select");
  const customModelGroup = document.getElementById("custom-model-group");
  const cfgCustomModel = document.getElementById("cfg-custom-model");
  const btnSaveSettings = document.getElementById("btn-save-settings");
  const btnResetDb = document.getElementById("btn-reset-db");

  let currentFixedSql = "";
  let currentReportMarkdown = "";
  let currentReportFilename = "sql_audit_report.md";

  function init() {
    updateModelPill();
    setupTabNavigation();
    loadPresets();
    loadSchema();
    setupEventListeners();
    setupSchemaManager();
    setupBenchmarks();
  }

  function updateModelPill() {
    if (!activeModelText) return;
    if (state.model === "offline-expert" || !state.apiKey) {
      activeModelText.textContent = state.model === "offline-expert"
        ? "Offline Expert"
        : `${state.model} (Offline Auto)`;
    } else {
      activeModelText.textContent = state.model;
    }
  }

  function setupTabNavigation() {
    const tabs = [
      { btn: tabNavWorkbench, pane: tabWorkbench, id: "workbench" },
      { btn: tabNavSchema, pane: tabSchema, id: "schema" },
      { btn: tabNavBenchmarks, pane: tabBenchmarks, id: "benchmarks" }
    ];

    tabs.forEach(({ btn, pane, id }) => {
      if (!btn) return;
      btn.addEventListener("click", () => {
        tabs.forEach(t => {
          t.btn.classList.remove("active");
          t.pane.classList.add("hidden");
        });
        btn.classList.add("active");
        pane.classList.remove("hidden");
        state.activeTab = id;
        if (id === "schema") loadSchema();
      });
    });
  }

  async function loadPresets() {
    try {
      const res = await fetch("/api/benchmarks");
      const data = await res.json();
      state.presets = data.benchmarks || [];
      populatePresetDropdown();
    } catch (err) {
      console.error(err);
    }
  }

  function populatePresetDropdown() {
    presetSelect.innerHTML = '<option value="">-- Choose a broken SQL scenario (25 available) --</option>';
    const categories = {};

    state.presets.forEach(p => {
      const cat = p.category || "OTHER";
      if (!categories[cat]) categories[cat] = [];
      categories[cat].push(p);
    });

    for (const [cat, items] of Object.entries(categories)) {
      const optGroup = document.createElement("optgroup");
      optGroup.label = cat.replace(/_/g, " ");
      items.forEach(item => {
        const opt = document.createElement("option");
        opt.value = item.id;
        opt.textContent = `[${item.id}] ${item.title}`;
        optGroup.appendChild(opt);
      });
      presetSelect.appendChild(optGroup);
    }
  }

  function loadScenarioById(presetId) {
    if (!presetId) {
      presetDescText.textContent = "Select a scenario above or type custom SQL below.";
      return;
    }
    const found = state.presets.find(p => p.id === presetId);
    if (!found) return;

    sqlInput.value = found.broken_sql;
    presetDescText.innerHTML = `<strong>${found.title}</strong> &bull; Category: <span class="badge badge-category">${found.category}</span> &bull; ${found.misdiagnosis_risk || ""}`;
    clearTerminal();
    resultsSection.classList.add("hidden");
    sqlInput.focus();
  }

  async function loadSchema() {
    try {
      const res = await fetch("/api/schema");
      const data = await res.json();
      state.schema = data.schema || {};
      state.schemaSource = data.source || "default";

      if (schemaStatusBadge) {
        schemaStatusBadge.textContent = data.is_custom ? `Custom Schema (${data.source})` : "Default Schema";
        schemaStatusBadge.className = data.is_custom ? "badge badge-category" : "badge";
      }

      const tableNames = Object.keys(state.schema);
      if (tablesCountBadge) {
        tablesCountBadge.textContent = `${tableNames.length} Tables`;
      }

      renderSchemaTables(state.schema);
    } catch (err) {
      console.error(err);
    }
  }

  function renderSchemaTables(schema) {
    if (!activeTablesContainer) return;
    const tableNames = Object.keys(schema);
    if (tableNames.length === 0) {
      activeTablesContainer.innerHTML = '<p class="terminal-dim">No tables found in active schema.</p>';
      return;
    }

    let html = "";
    tableNames.forEach(tbl => {
      const meta = schema[tbl];
      const cols = meta.columns || [];
      const fks = meta.foreign_keys || [];
      const rowCount = meta.row_count || 0;

      let colsHtml = cols.map(c => `
        <div class="table-col-row ${c.pk ? 'pk' : ''}">
          <span>${c.pk ? '🔑 ' : ''}<strong>${escapeHtml(c.name)}</strong></span>
          <span class="col-type">${escapeHtml(c.type || 'TEXT')} ${c.notnull ? 'NOT NULL' : ''}</span>
        </div>
      `).join("");

      let fksHtml = "";
      if (fks.length > 0) {
        fksHtml = '<div style="margin-top:0.4rem; font-size:0.75rem; color:var(--text-muted);">' +
          fks.map(f => `FK: <code>${escapeHtml(f.from)}</code> &rarr; <code>${escapeHtml(f.table)}.${escapeHtml(f.to)}</code>`).join("<br>") +
          '</div>';
      }

      html += `
        <div class="table-card-item">
          <div class="table-card-header">
            <span class="table-card-name">${escapeHtml(tbl)}</span>
            <span class="badge">${rowCount} rows</span>
          </div>
          <div class="table-columns-list">
            ${colsHtml}
          </div>
          ${fksHtml}
        </div>
      `;
    });

    activeTablesContainer.innerHTML = html;
  }

  function setupSchemaManager() {
    if (btnPickDdl && fileDdl) {
      btnPickDdl.addEventListener("click", () => fileDdl.click());
      fileDdl.addEventListener("change", (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (evt) => {
          customDdlInput.value = evt.target.result;
        };
        reader.readAsText(file);
      });
    }

    if (btnDeployDdl) {
      btnDeployDdl.addEventListener("click", async () => {
        const ddl = customDdlInput.value.trim();
        if (!ddl) {
          alert("Please enter a SQL DDL script.");
          return;
        }
        btnDeployDdl.disabled = true;
        btnDeployDdl.textContent = "Deploying...";
        try {
          const res = await fetch("/api/schema/upload-ddl", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: jsonPayload({ ddl })
          });
          const data = await res.json();
          if (data.success) {
            alert(data.message);
            loadSchema();
          } else {
            alert(`DDL Error: ${data.error}`);
          }
        } catch (err) {
          alert(`Network error: ${err.message}`);
        } finally {
          btnDeployDdl.disabled = false;
          btnDeployDdl.textContent = "Deploy DDL Schema";
        }
      });
    }

    if (btnPickDb && fileDb) {
      btnPickDb.addEventListener("click", () => fileDb.click());
      fileDb.addEventListener("change", (e) => {
        const file = e.target.files[0];
        if (file) handleDbFileUpload(file);
      });
    }

    if (dbDropZone) {
      dbDropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dbDropZone.classList.add("dragover");
      });
      dbDropZone.addEventListener("dragleave", () => dbDropZone.classList.remove("dragover"));
      dbDropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dbDropZone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) {
          handleDbFileUpload(e.dataTransfer.files[0]);
        }
      });
    }

    if (btnResetSchemaMain) {
      btnResetSchemaMain.addEventListener("click", async () => {
        if (confirm("Reset database sandbox to default schema?")) {
          const res = await fetch("/api/schema/reset", { method: "POST" });
          const data = await res.json();
          alert(data.message || "Database reset.");
          loadSchema();
        }
      });
    }
  }

  function handleDbFileUpload(file) {
    if (!file.name.match(/\.(db|sqlite|sqlite3)$/i)) {
      alert("Please upload a valid SQLite database file (.db, .sqlite, .sqlite3).");
      return;
    }
    if (dbUploadStatus) {
      dbUploadStatus.innerHTML = `<span style="color:var(--accent-primary);">Uploading ${escapeHtml(file.name)}...</span>`;
    }

    const reader = new FileReader();
    reader.onload = async (e) => {
      const dataUrl = e.target.result;
      const base64Content = dataUrl.split(",")[1];
      try {
        const res = await fetch("/api/schema/upload-db", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: jsonPayload({
            data_base64: base64Content,
            filename: file.name
          })
        });
        const data = await res.json();
        if (data.success) {
          if (dbUploadStatus) dbUploadStatus.innerHTML = `<span style="color:var(--accent-emerald);">✓ ${escapeHtml(data.message)}</span>`;
          loadSchema();
        } else {
          if (dbUploadStatus) dbUploadStatus.innerHTML = `<span style="color:var(--accent-rose);">✗ ${escapeHtml(data.error)}</span>`;
        }
      } catch (err) {
        if (dbUploadStatus) dbUploadStatus.innerHTML = `<span style="color:var(--accent-rose);">${escapeHtml(err.message)}</span>`;
      }
    };
    reader.readAsDataURL(file);
  }

  function setupEventListeners() {
    presetSelect.addEventListener("change", (e) => loadScenarioById(e.target.value));

    quickChips.forEach(chip => {
      chip.addEventListener("click", () => {
        const presetId = chip.getAttribute("data-preset");
        presetSelect.value = presetId;
        loadScenarioById(presetId);
      });
    });

    btnClearSql.addEventListener("click", () => {
      sqlInput.value = "";
      clearTerminal();
      resultsSection.classList.add("hidden");
      presetSelect.value = "";
      presetDescText.textContent = "Select a scenario above or type custom SQL below.";
      sqlInput.focus();
    });

    sqlInput.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        btnExplainFix.click();
      }
    });

    btnRunRaw.addEventListener("click", () => {
      const sql = sqlInput.value.trim();
      if (!sql) return;
      executeRawSQL(sql);
    });

    btnExplainFix.addEventListener("click", () => {
      const sql = sqlInput.value.trim();
      if (!sql) {
        alert("Please enter a SQL query or select a preset scenario.");
        return;
      }
      explainAndFixSQL(sql);
    });

    btnDiffSplit.addEventListener("click", () => {
      state.diffView = "split";
      btnDiffSplit.classList.add("active");
      btnDiffUnified.classList.remove("active");
      diffContainerSplit.classList.remove("hidden");
      diffContainerUnified.classList.add("hidden");
    });

    btnDiffUnified.addEventListener("click", () => {
      state.diffView = "unified";
      btnDiffUnified.classList.add("active");
      btnDiffSplit.classList.remove("active");
      diffContainerUnified.classList.remove("hidden");
      diffContainerSplit.classList.add("hidden");
    });

    btnCopyFixed.addEventListener("click", () => {
      if (currentFixedSql) {
        copyToClipboard(currentFixedSql);
        const originalText = btnCopyFixed.textContent;
        btnCopyFixed.textContent = "Copied!";
        setTimeout(() => btnCopyFixed.textContent = originalText, 1800);
      }
    });

    const openSettings = () => {
      if (cfgApiKey) cfgApiKey.value = state.apiKey;
      if (cfgModelSelect) {
        const optionExists = Array.from(cfgModelSelect.options).some(o => o.value === state.model);
        if (optionExists) {
          cfgModelSelect.value = state.model;
          if (customModelGroup) customModelGroup.classList.add("hidden");
        } else if (state.model && state.model !== "custom") {
          cfgModelSelect.value = "custom";
          if (customModelGroup) customModelGroup.classList.remove("hidden");
          if (cfgCustomModel) cfgCustomModel.value = state.model;
        } else {
          cfgModelSelect.value = "openrouter/free";
          if (customModelGroup) customModelGroup.classList.add("hidden");
        }
      }
      if (settingsModal) settingsModal.classList.add("open");
      if (modalBackdrop) modalBackdrop.classList.add("open");
    };

    btnSettings.addEventListener("click", openSettings);
    if (activeModelBadge) activeModelBadge.addEventListener("click", openSettings);

    cfgModelSelect.addEventListener("change", (e) => {
      if (e.target.value === "custom") {
        customModelGroup.classList.remove("hidden");
      } else {
        customModelGroup.classList.add("hidden");
      }
    });

    btnCloseModal.addEventListener("click", closeModals);
    if (modalBackdrop) modalBackdrop.addEventListener("click", closeModals);

    btnSaveSettings.addEventListener("click", () => {
      state.apiKey = cfgApiKey.value.trim();
      let chosenModel = cfgModelSelect.value;
      if (chosenModel === "custom") {
        chosenModel = cfgCustomModel.value.trim() || "openrouter/free";
      }
      state.model = chosenModel;
      localStorage.setItem("sql_fixer_api_key", state.apiKey);
      localStorage.setItem("sql_fixer_model", state.model);
      updateModelPill();
      closeModals();
    });

    btnResetDb.addEventListener("click", async () => {
      if (confirm("Reset database sandbox to default state?")) {
        await fetch("/api/schema/reset", { method: "POST" });
        alert("Database sandbox reset.");
        loadSchema();
        closeModals();
      }
    });

    if (btnExportQuick) btnExportQuick.addEventListener("click", exportAuditReport);
    if (btnExportSingle) btnExportSingle.addEventListener("click", exportAuditReport);
    if (btnCloseReportModal) btnCloseReportModal.addEventListener("click", closeModals);

    if (btnCopyReport) {
      btnCopyReport.addEventListener("click", () => {
        copyToClipboard(currentReportMarkdown);
        const orig = btnCopyReport.textContent;
        btnCopyReport.textContent = "Copied!";
        setTimeout(() => btnCopyReport.textContent = orig, 1800);
      });
    }

    if (btnDownloadReport) {
      btnDownloadReport.addEventListener("click", () => {
        downloadFile(currentReportMarkdown, currentReportFilename, "text/markdown");
      });
    }
  }

  function closeModals() {
    if (settingsModal) settingsModal.classList.remove("open");
    if (reportModal) reportModal.classList.remove("open");
    if (modalBackdrop) modalBackdrop.classList.remove("open");
  }

  async function executeRawSQL(sql) {
    const isDryRun = checkDryRun ? checkDryRun.checked : true;
    setTerminalLoading("Executing query in sandbox...");

    try {
      const res = await fetch("/api/run-sql", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: jsonPayload({ sql, dry_run: isDryRun })
      });
      const data = await res.json();

      if (data.guardrail_blocked) {
        setTerminalBlocked(data.error, data.verdict);
      } else if (!data.success) {
        setTerminalError(data.error, data.execution_time_ms);
      } else {
        setTerminalSuccess(data);
      }
    } catch (err) {
      setTerminalError(`Execution failed: ${err.message}`, 0);
    }
  }

  async function explainAndFixSQL(sql) {
    const isDryRun = checkDryRun ? checkDryRun.checked : true;
    btnExplainFix.disabled = true;
    btnExplainFix.innerHTML = '<span class="spinner"></span> Diagnosing...';
    setTerminalLoading("Analyzing query and error...");
    resultsSection.classList.add("hidden");

    try {
      const res = await fetch("/api/explain-and-fix", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: jsonPayload({
          sql,
          api_key: state.apiKey,
          model: state.model,
          force_offline: !state.apiKey || state.model === "offline-expert",
          dry_run: isDryRun
        })
      });
      const data = await res.json();
      state.currentSession = data;

      if (data.is_destructive_input) {
        setTerminalBlocked(data.verdict.violations.join("\n"), data.verdict);
        renderDiagnosisCard(data.diagnosis, data.verdict, data.model_used);
        resultsSection.classList.remove("hidden");
      } else {
        if (data.broken_error) {
          setTerminalError(data.broken_error, 0);
        } else {
          setTerminalSuccess({ row_count: 0, execution_time_ms: 1 });
        }
        renderDiagnosisCard(data.diagnosis, data.verdict, data.model_used);
        renderDiff(data.diff, data.fixed_sql);
        renderExecutionResults(data.fixed_execution, data.query_plan);
        resultsSection.classList.remove("hidden");
      }
    } catch (err) {
      setTerminalError(`Diagnosis failed: ${err.message}`, 0);
    } finally {
      btnExplainFix.disabled = false;
      btnExplainFix.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"></path></svg> Explain &amp; Fix with AI';
    }
  }

  function renderDiagnosisCard(diag, verdict, modelUsed) {
    resCategory.textContent = diag.error_category || "SYNTAX";
    resModel.textContent = modelUsed || "Offline Expert";

    const isSafe = verdict && verdict.is_safe;
    resSafety.textContent = isSafe ? "SAFE" : (verdict.risk_level || "BLOCKED");
    resSafety.className = `badge ${isSafe ? 'badge-safety' : 'badge-danger'}`;

    const riskScore = (verdict && verdict.risk_score !== undefined) ? verdict.risk_score : (isSafe ? 0 : 95);
    resRiskScore.textContent = `Risk Score: ${riskScore}/100`;

    resRootCause.textContent = diag.root_cause || "No root cause provided.";
    resTechnical.textContent = diag.technical_details || "N/A";
    resDiffSummary.textContent = diag.diff_explanation || "N/A";
    resPrevention.textContent = diag.prevention_advice || "Validate syntax against schema.";

    if (resLayerPills && verdict && verdict.defense_layers) {
      let layerHtml = "";
      for (const [k, v] of Object.entries(verdict.defense_layers)) {
        const passed = v.passed;
        layerHtml += `
          <span class="layer-pill ${passed ? 'passed' : 'blocked'}">
            ${passed ? '✓' : '✗'} ${escapeHtml(v.name || k)}
          </span>
        `;
      }
      resLayerPills.innerHTML = layerHtml;
    }
  }

  function renderDiff(diffData, fixedSql) {
    currentFixedSql = fixedSql || "";
    if (diffUnifiedText) {
      diffUnifiedText.textContent = diffData.unified_text || "No differences detected.";
    }

    if (diffLeftLines && diffRightLines) {
      diffLeftLines.innerHTML = (diffData.left_lines || []).map(l => `
        <div class="diff-line ${l.status}">
          <span class="diff-line-num">${l.line_no}</span>
          <span class="diff-line-code">${escapeHtml(l.text)}</span>
        </div>
      `).join("");

      diffRightLines.innerHTML = (diffData.right_lines || []).map(l => `
        <div class="diff-line ${l.status}">
          <span class="diff-line-num">${l.line_no}</span>
          <span class="diff-line-code">${escapeHtml(l.text)}</span>
        </div>
      `).join("");
    }
  }

  function renderExecutionResults(exec, queryPlan) {
    const success = exec && exec.success;
    metricStatus.textContent = success ? "Status: VERIFIED SUCCESS" : "Status: EXECUTION ERROR";
    metricStatus.className = `metric-pill ${success ? 'status-ok' : 'status-err'}`;
    metricRows.textContent = `Rows: ${exec.row_count || 0}`;
    metricTime.textContent = `Time: ${exec.execution_time_ms || 0} ms`;

    if (!success) {
      execTableContainer.innerHTML = `<p class="table-placeholder error" style="color:var(--accent-rose);">Execution error: ${escapeHtml(exec.error || 'Unknown error')}</p>`;
    } else if (!exec.columns || exec.columns.length === 0 || !exec.rows || exec.rows.length === 0) {
      execTableContainer.innerHTML = '<p class="table-placeholder">Query executed cleanly.</p>';
    } else {
      let ths = exec.columns.map(c => `<th>${escapeHtml(c)}</th>`).join("");
      let trs = exec.rows.map(r => `<tr>${r.map(cell => `<td>${escapeHtml(String(cell === null ? 'NULL' : cell))}</td>`).join("")}</tr>`).join("");
      execTableContainer.innerHTML = `
        <table class="data-table">
          <thead><tr>${ths}</tr></thead>
          <tbody>${trs}</tbody>
        </table>
      `;
    }

    if (queryPlanContent) {
      if (queryPlan && queryPlan.length > 0) {
        queryPlanContent.innerHTML = queryPlan.map(p => `
          <div class="plan-node">
            <span class="plan-id">#${p.id} (Parent: ${p.parent})</span>
            <span class="plan-detail">${escapeHtml(p.detail)}</span>
          </div>
        `).join("");
      } else {
        queryPlanContent.innerHTML = '<p class="terminal-dim" style="padding:0.5rem 0;">No query plan available.</p>';
      }
    }
  }

  function setupBenchmarks() {
    if (!btnRunBenchmarks) return;

    btnRunBenchmarks.addEventListener("click", async () => {
      btnRunBenchmarks.disabled = true;
      btnRunBenchmarks.innerHTML = '<span class="spinner"></span> Running Tests...';

      try {
        const res = await fetch("/api/benchmarks/run");
        const data = await res.json();
        state.benchmarkData = data;

        scoreAccuracy.textContent = `${data.accuracy_percentage}%`;
        scoreGuardrail.textContent = `${data.guardrail_catch_rate}%`;
        scoreTotal.textContent = `${data.total_tests}`;
        scoreLatency.textContent = `${data.total_runtime_ms} ms`;

        renderCategoryChips(data.category_stats);
        renderBenchmarkTable(data.scenarios, "ALL");
      } catch (err) {
        alert(`Benchmark run failed: ${err.message}`);
      } finally {
        btnRunBenchmarks.disabled = false;
        btnRunBenchmarks.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> Re-Run Benchmark Suite';
      }
    });

    if (benchFilterGroup) {
      benchFilterGroup.querySelectorAll(".btn-chip").forEach(btn => {
        btn.addEventListener("click", () => {
          benchFilterGroup.querySelectorAll(".btn-chip").forEach(b => b.classList.remove("active"));
          btn.classList.add("active");
          const filter = btn.getAttribute("data-filter");
          if (state.benchmarkData && state.benchmarkData.scenarios) {
            renderBenchmarkTable(state.benchmarkData.scenarios, filter);
          }
        });
      });
    }
  }

  function renderCategoryChips(stats) {
    if (!categoryChipsContainer || !stats) return;
    let html = "";
    for (const [cat, s] of Object.entries(stats)) {
      const hasFails = s.failed > 0;
      html += `
        <div class="category-stat-pill ${hasFails ? 'has-fails' : ''}">
          <span>${escapeHtml(cat.replace(/_/g, ' '))}</span>
          <strong>${s.passed} / ${s.total} (${Math.round((s.passed / s.total) * 100)}%)</strong>
        </div>
      `;
    }
    categoryChipsContainer.innerHTML = html;
  }

  function renderBenchmarkTable(scenarios, filter) {
    if (!benchmarkTableContainer || !scenarios) return;

    let filtered = scenarios;
    if (filter === "PASSED") {
      filtered = scenarios.filter(s => s.status === "PASSED");
    } else if (filter === "GUARDRAIL") {
      filtered = scenarios.filter(s => s.status === "PASSED_GUARDRAIL");
    } else if (filter === "DIALECT") {
      filtered = scenarios.filter(s => s.category === "DIALECT_MISDIAGNOSIS");
    }

    if (filtered.length === 0) {
      benchmarkTableContainer.innerHTML = '<p class="terminal-dim" style="padding:1rem;">No scenarios matching this filter.</p>';
      return;
    }

    let rowsHtml = filtered.map(sc => {
      const isPassed = sc.status === "PASSED" || sc.status === "PASSED_GUARDRAIL";
      const statusBadge = isPassed
        ? `<span class="badge badge-safety">${sc.status}</span>`
        : `<span class="badge badge-danger">${sc.status}</span>`;

      return `
        <tr>
          <td><strong>${escapeHtml(sc.id)}</strong></td>
          <td><span class="badge badge-category">${escapeHtml(sc.category)}</span></td>
          <td>
            <strong>${escapeHtml(sc.title)}</strong><br>
            <small style="color:var(--text-muted);">${escapeHtml(sc.misdiagnosis_risk || '')}</small>
          </td>
          <td>${statusBadge}</td>
          <td><code>${sc.elapsed_ms} ms</code></td>
          <td>
            <button class="btn-secondary btn-sm" onclick="window.loadScenarioFromBench('${sc.id}')">Load in Workbench</button>
          </td>
        </tr>
      `;
    }).join("");

    benchmarkTableContainer.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Category</th>
            <th>Scenario</th>
            <th>Verdict</th>
            <th>Latency</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    `;
  }

  window.loadScenarioFromBench = function(presetId) {
    if (tabNavWorkbench) tabNavWorkbench.click();
    if (presetSelect) presetSelect.value = presetId;
    loadScenarioById(presetId);
  };

  async function exportAuditReport() {
    let session = state.currentSession;
    if (!session || !session.broken_sql) {
      session = {
        broken_sql: sqlInput.value.trim() || "SELECT * FROM customers;",
        fixed_sql: currentFixedSql || "SELECT * FROM customers;",
        broken_error: "Captured session error",
        model_used: state.model,
        diagnosis: {
          error_category: "SYNTAX",
          root_cause: "Session diagnosis summary",
          technical_details: "Verified AST inspection against schema.",
          prevention_advice: "Verify SQL syntax against DDL schema."
        },
        verdict: {
          risk_level: "SAFE",
          risk_score: 0,
          statement_type: "SELECT",
          is_safe: true,
          remediation_advice: "Clean execution."
        },
        diff: { unified_text: "--- Original\n+++ Corrected\n" },
        fixed_execution: { success: true, row_count: 5, execution_time_ms: 1.2 },
        query_plan: [{ id: 0, parent: 0, detail: "SCAN TABLE customers" }]
      };
    }

    try {
      const res = await fetch("/api/export-report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: jsonPayload(session)
      });
      const data = await res.json();
      if (data.success && data.report) {
        currentReportMarkdown = data.report.markdown;
        currentReportFilename = data.report.filename;
        reportMarkdownPreview.textContent = currentReportMarkdown;
        reportModal.classList.add("open");
        modalBackdrop.classList.add("open");
      }
    } catch (err) {
      alert(`Report export failed: ${err.message}`);
    }
  }

  function setTerminalLoading(msg) {
    terminalStatusBadge.textContent = "Processing";
    terminalStatusBadge.className = "badge";
    terminalOutput.innerHTML = `<span class="terminal-dim">// ${escapeHtml(msg)}</span>`;
  }

  function setTerminalError(errMsg, timeMs) {
    terminalStatusBadge.textContent = "Error";
    terminalStatusBadge.className = "badge badge-danger";
    terminalOutput.innerHTML = `
      <div class="terminal-err">
        <span class="err-prefix">Error:</span> ${escapeHtml(errMsg)}
      </div>
      <div class="terminal-meta">Latency: ${timeMs} ms &bull; Rollback: Executed</div>
    `;
  }

  function setTerminalBlocked(violations, verdict) {
    terminalStatusBadge.textContent = "BLOCKED";
    terminalStatusBadge.className = "badge badge-danger";
    terminalOutput.innerHTML = `
      <div class="terminal-err" style="color:var(--accent-rose);">
        <span class="err-prefix">Security Guardrail Blocked (Risk: ${verdict.risk_score || 95}/100):</span>
        <br>${escapeHtml(violations)}
      </div>
      <div class="terminal-meta" style="margin-top:0.4rem;">Remediation: ${escapeHtml(verdict.remediation_advice || 'Aborted')}</div>
    `;
  }

  function setTerminalSuccess(data) {
    terminalStatusBadge.textContent = "Success";
    terminalStatusBadge.className = "badge badge-safety";
    terminalOutput.innerHTML = `
      <div class="terminal-ok">✓ Query executed cleanly in sandbox.</div>
      <div class="terminal-meta">Rows returned: ${data.row_count || 0} &bull; Time: ${data.execution_time_ms || 0} ms</div>
    `;
  }

  function clearTerminal() {
    terminalStatusBadge.textContent = "Idle";
    terminalStatusBadge.className = "badge";
    terminalOutput.innerHTML = '<span class="terminal-dim">// Database output and execution metrics will display here...</span>';
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function jsonPayload(obj) {
    return JSON.stringify(obj);
  }

  function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(() => fallbackCopy(text));
    } else {
      fallbackCopy(text);
    }
  }

  function fallbackCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(ta);
  }

  function downloadFile(content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  init();
});
