/**
 * Frontend Application Logic for SQL Error Explainer & Fixer
 * Coordinates REST API calls, editor interactions, diff rendering,
 * and security / benchmark simulations.
 */

document.addEventListener("DOMContentLoaded", () => {
  // State
  const state = {
    apiKey: localStorage.getItem("sql_fixer_api_key") || "",
    model: localStorage.getItem("sql_fixer_model") || "openrouter/free",
    presets: [],
    schema: null,
    diffView: "split"
  };

  // DOM Elements
  const presetSelect = document.getElementById("preset-select");
  const presetDescText = document.getElementById("preset-desc-text");
  const quickChips = document.querySelectorAll(".chip-btn");
  const sqlInput = document.getElementById("sql-input");
  const btnClearSql = document.getElementById("btn-clear-sql");
  const btnRunRaw = document.getElementById("btn-run-raw");
  const btnExplainFix = document.getElementById("btn-explain-fix");
  const terminalOutput = document.getElementById("terminal-output");
  const terminalStatusBadge = document.getElementById("terminal-status-badge");
  const resultsSection = document.getElementById("results-section");

  // Diagnosis Card
  const resCategory = document.getElementById("res-category");
  const resSafety = document.getElementById("res-safety");
  const resModel = document.getElementById("res-model");
  const resConfidenceBar = document.getElementById("res-confidence-bar");
  const resConfidenceText = document.getElementById("res-confidence-text");
  const resRootCause = document.getElementById("res-root-cause");
  const resTechnical = document.getElementById("res-technical");
  const resDiffSummary = document.getElementById("res-diff-summary");
  const resPrevention = document.getElementById("res-prevention");

  // Diff Panes & Toggles
  const btnDiffSplit = document.getElementById("btn-diff-split");
  const btnDiffUnified = document.getElementById("btn-diff-unified");
  const diffContainerSplit = document.getElementById("diff-container-split");
  const diffContainerUnified = document.getElementById("diff-container-unified");
  const diffLeftLines = document.getElementById("diff-left-lines");
  const diffRightLines = document.getElementById("diff-right-lines");
  const diffUnifiedText = document.getElementById("diff-unified-text") || document.getElementById("unified-diff-text");
  const btnCopyFixed = document.getElementById("btn-copy-fixed");

  // Execution Table
  const metricStatus = document.getElementById("metric-status");
  const metricRows = document.getElementById("metric-rows");
  const metricTime = document.getElementById("metric-time");
  const execTableContainer = document.getElementById("exec-table-container");
  const queryPlanContent = document.getElementById("query-plan-content");

  // Schema Drawer
  const btnSchema = document.getElementById("btn-schema");
  const schemaDrawer = document.getElementById("schema-drawer");
  const drawerBackdrop = document.getElementById("drawer-backdrop");
  const btnCloseDrawer = document.getElementById("btn-close-drawer");
  const schemaDrawerContent = document.getElementById("schema-drawer-content");

  // Settings Modal
  const btnSettings = document.getElementById("btn-settings");
  const settingsModal = document.getElementById("settings-modal");
  const btnCloseModal = document.getElementById("btn-close-modal");
  const cfgApiKey = document.getElementById("cfg-api-key");
  const cfgModelSelect = document.getElementById("cfg-model-select");
  const customModelGroup = document.getElementById("custom-model-group");
  const cfgCustomModel = document.getElementById("cfg-custom-model");
  const btnSaveSettings = document.getElementById("btn-save-settings");
  const btnResetDb = document.getElementById("btn-reset-db");
  const activeModelBadge = document.getElementById("active-model-badge");
  const activeModelText = document.getElementById("active-model-text");

  let currentFixedSql = "";
  let currentDiffData = null;

  // 1. Initial Load & Setup
  function init() {
    updateModelPill();
    loadPresets();
    loadSchema();
    setupEventListeners();
  }

  function updateModelPill() {
    if (activeModelText) {
      if (state.model === "offline-expert" || !state.apiKey) {
        activeModelText.textContent = state.model === "offline-expert" 
          ? "Offline Expert" 
          : `${state.model} (Offline Auto)`;
      } else {
        activeModelText.textContent = state.model;
      }
    }
  }

  function setupEventListeners() {
    // Preset Selection via Dropdown
    presetSelect.addEventListener("change", (e) => {
      loadScenarioById(e.target.value);
    });

    // Quick Preset Chips
    quickChips.forEach(chip => {
      chip.addEventListener("click", () => {
        const presetId = chip.getAttribute("data-preset");
        presetSelect.value = presetId;
        loadScenarioById(presetId);
      });
    });

    // Clear Button
    btnClearSql.addEventListener("click", () => {
      sqlInput.value = "";
      clearTerminal();
      resultsSection.classList.add("hidden");
      presetSelect.value = "";
      presetDescText.textContent = "Select a preset scenario above or type custom SQL below.";
      sqlInput.focus();
    });

    // Keyboard Shortcut (Cmd+Enter or Ctrl+Enter)
    sqlInput.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        btnExplainFix.click();
      }
    });

    // Raw Execute Button
    btnRunRaw.addEventListener("click", () => {
      const sql = sqlInput.value.trim();
      if (!sql) return;
      executeRawSQL(sql);
    });

    // Explain & Fix Button
    btnExplainFix.addEventListener("click", () => {
      const sql = sqlInput.value.trim();
      if (!sql) {
        alert("Please enter a SQL query or select a preset scenario.");
        return;
      }
      explainAndFixSQL(sql);
    });

    // Diff View Toggle
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

    // Copy Fixed SQL with Fallback
    btnCopyFixed.addEventListener("click", () => {
      if (currentFixedSql) {
        copyToClipboard(currentFixedSql);
        const originalText = btnCopyFixed.textContent;
        btnCopyFixed.textContent = "Copied!";
        btnCopyFixed.classList.add("badge-safety");
        setTimeout(() => {
          btnCopyFixed.textContent = originalText;
          btnCopyFixed.classList.remove("badge-safety");
        }, 1800);
      }
    });

    // Schema Drawer Toggles
    btnSchema.addEventListener("click", () => {
      schemaDrawer.classList.add("open");
      drawerBackdrop.classList.add("open");
    });
    btnCloseDrawer.addEventListener("click", closeDrawer);
    drawerBackdrop.addEventListener("click", closeDrawer);

    // Settings Modal
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
    };

    btnSettings.addEventListener("click", openSettings);
    if (activeModelBadge) {
      activeModelBadge.addEventListener("click", openSettings);
    }

    cfgModelSelect.addEventListener("change", (e) => {
      if (e.target.value === "custom") {
        customModelGroup.classList.remove("hidden");
      } else {
        customModelGroup.classList.add("hidden");
      }
    });

    btnCloseModal.addEventListener("click", () => settingsModal.classList.remove("open"));

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
      settingsModal.classList.remove("open");
    });

    btnResetDb.addEventListener("click", async () => {
      if (confirm("Reset the database sandbox to pristine seed state?")) {
        await fetch("/api/reset-db", { method: "POST" });
        alert("Database sandbox reset to pristine state!");
        loadSchema();
        settingsModal.classList.remove("open");
      }
    });
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
    try {
      document.execCommand("copy");
    } catch (e) {
      console.warn("Fallback copy failed", e);
    }
    document.body.removeChild(ta);
  }

  function loadScenarioById(selectedId) {
    const found = state.presets.find(p => p.id === selectedId);
    if (found) {
      sqlInput.value = found.broken_sql;
      presetDescText.textContent = `[${found.category}] ${found.description}`;
      clearTerminal();
      resultsSection.classList.add("hidden");
    } else {
      presetDescText.textContent = "Select a preset scenario above or type custom SQL below.";
    }
  }

  function closeDrawer() {
    schemaDrawer.classList.remove("open");
    drawerBackdrop.classList.remove("open");
  }

  function clearTerminal() {
    terminalOutput.innerHTML = '<span class="terminal-dim">// Database error output and stack trace will display here...</span>';
    terminalStatusBadge.textContent = "Idle";
    terminalStatusBadge.className = "badge";
  }

  // 2. Fetch Presets
  async function loadPresets() {
    try {
      const res = await fetch("/api/benchmarks");
      const data = await res.json();
      state.presets = data.benchmarks || [];

      presetSelect.innerHTML = '<option value="">-- Choose a broken SQL scenario --</option>';
      state.presets.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = `[${p.category}] ${p.title}`;
        presetSelect.appendChild(opt);
      });
    } catch (err) {
      console.error("Failed to load benchmarks:", err);
    }
  }

  // 3. Fetch Schema
  async function loadSchema() {
    try {
      const res = await fetch("/api/schema");
      const data = await res.json();
      state.schema = data.schema || {};

      let html = "";
      for (const [tbl, meta] of Object.entries(state.schema)) {
        html += `
          <div class="card" style="margin-bottom: 12px; padding: 12px 14px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <span style="color: #38bdf8; font-weight:600; font-size:0.88rem;">Table: ${escapeHtml(tbl)}</span>
              <span class="badge" style="background:#1e293b; color:#94a3b8; font-size:0.7rem;">${meta.row_count} rows</span>
            </div>
            <div style="font-family: var(--font-mono); font-size: 0.78rem; line-height: 1.6; margin-bottom: 8px;">
              ${meta.columns.map(c => `<div>• <strong>${escapeHtml(c.name)}</strong> <span style="color:var(--text-muted)">${escapeHtml(c.type)}${c.pk ? ' (PK)' : ''}</span></div>`).join("")}
            </div>
            ${meta.foreign_keys.length > 0 ? `
              <div style="font-size: 0.76rem; color: #a5b4fc; margin-bottom: 6px; padding: 4px 8px; background: rgba(99,102,241,0.08); border-radius:4px;">
                ${meta.foreign_keys.map(f => `FK: ${escapeHtml(f.from)} &rarr; ${escapeHtml(f.table)}.${escapeHtml(f.to)}`).join("<br>")}
              </div>
            ` : ""}
            <details style="font-size: 0.78rem; margin-top: 6px;">
              <summary style="cursor:pointer; color: var(--accent-primary)">Preview Rows</summary>
              <pre style="background:var(--bg-input); padding:8px; border-radius:6px; margin-top:6px; overflow-x:auto; font-size:0.74rem;">${escapeHtml(JSON.stringify(meta.sample_rows, null, 2))}</pre>
            </details>
          </div>
        `;
      }
      schemaDrawerContent.innerHTML = html;
    } catch (err) {
      schemaDrawerContent.innerHTML = `<p style="color:var(--accent-rose)">Error loading schema: ${escapeHtml(err.message)}</p>`;
    }
  }

  // 4. Execute Raw Query in DB Sandbox
  async function executeRawSQL(sql) {
    terminalStatusBadge.textContent = "Executing...";
    terminalStatusBadge.className = "badge badge-model";
    terminalOutput.innerHTML = '<span class="terminal-dim">Running query against database sandbox...</span>';

    try {
      const res = await fetch("/api/run-sql", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql })
      });
      const data = await res.json();

      if (data.guardrail_blocked) {
        terminalStatusBadge.textContent = "BLOCKED";
        terminalStatusBadge.className = "badge badge-safety critical";
        terminalOutput.innerHTML = `[!] BLOCKED BY AST GUARDRAIL (${data.verdict.risk_level})\n${data.verdict.violations.map(v => "• " + v).join("\n")}`;
        return;
      }

      if (data.success) {
        terminalStatusBadge.textContent = "SUCCESS (0 ERRORS)";
        terminalStatusBadge.className = "badge badge-safety";
        terminalOutput.innerHTML = `<span class="terminal-success">[✓] Query executed successfully with 0 errors!\n• Rows returned: ${data.row_count}\n• Execution time: ${data.execution_time_ms} ms</span>`;
      } else {
        terminalStatusBadge.textContent = "ERROR CAPTURED";
        terminalStatusBadge.className = "badge badge-safety critical";
        terminalOutput.innerHTML = `[!] Database Engine Error:\n${data.error}\n\nType: ${data.error_type || "SqliteOperationalError"}`;
      }
    } catch (err) {
      terminalStatusBadge.textContent = "NETWORK ERROR";
      terminalOutput.innerHTML = `Failed to contact API server: ${err.message}`;
    }
  }

  // 6. Core: Explain & Fix SQL
  async function explainAndFixSQL(sql) {
    btnExplainFix.disabled = true;
    btnExplainFix.textContent = "Analyzing with AI...";
    terminalStatusBadge.textContent = "Diagnosing...";
    terminalStatusBadge.className = "badge badge-model";

    const isOffline = state.model === "offline-expert" || !state.apiKey;

    try {
      const res = await fetch("/api/explain-and-fix", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sql,
          api_key: state.apiKey,
          model: state.model,
          force_offline: isOffline
        })
      });
      const data = await res.json();

      if (resultsSection) resultsSection.classList.remove("hidden");

      // Handle Destructive Input Block
      if (data.is_destructive_input) {
        if (terminalStatusBadge) {
          terminalStatusBadge.textContent = "BLOCKED BY GUARDRAIL";
          terminalStatusBadge.className = "badge badge-safety critical";
        }
        if (terminalOutput) {
          terminalOutput.innerHTML = `[!] DESTRUCTIVE STATEMENT INTERCEPTED:\n${(data.verdict && data.verdict.violations ? data.verdict.violations : []).map(v => "• " + v).join("\n")}`;
        }

        if (resCategory) {
          resCategory.textContent = "HAZARD_BLOCKED";
          resCategory.className = "badge badge-safety critical";
        }
        if (resSafety) {
          resSafety.textContent = "CRITICAL (BLOCKED)";
          resSafety.className = "badge badge-safety critical";
        }
        if (resModel) resModel.textContent = "AST Guardrail";
        if (resConfidenceBar) resConfidenceBar.style.width = "100%";
        if (resConfidenceText) resConfidenceText.textContent = "100%";

        const dDiag = data.diagnosis || {};
        if (resRootCause) resRootCause.textContent = dDiag.root_cause || "Destructive SQL operation detected.";
        if (resTechnical) resTechnical.textContent = dDiag.technical_details || "Blocked by AST token analyzer.";
        if (resDiffSummary) resDiffSummary.textContent = dDiag.diff_explanation || "Execution halted to protect database integrity.";
        if (resPrevention) resPrevention.textContent = dDiag.prevention_advice || "Review SQL operations before execution.";

        if (diffLeftLines) diffLeftLines.innerHTML = `<div class="diff-line removed">${escapeHtml(sql)}</div>`;
        if (diffRightLines) diffRightLines.innerHTML = `<div class="diff-line" style="color: var(--accent-rose)">[Execution Blocked: Destructive Statement]</div>`;
        if (diffUnifiedText) diffUnifiedText.textContent = "--- Original Broken SQL\n+++ Corrected SQL\n[EXECUTION BLOCKED BY AST GUARDRAILS]";

        if (metricStatus) {
          metricStatus.textContent = "Status: BLOCKED";
          metricStatus.style.color = "var(--accent-rose)";
        }
        if (metricRows) metricRows.textContent = "Rows: 0";
        if (metricTime) metricTime.textContent = "Time: 0 ms";
        if (execTableContainer) execTableContainer.innerHTML = `<p style="padding:16px; color:var(--accent-rose)">Execution was halted prior to database dispatch to protect table integrity.</p>`;
        if (queryPlanContent) queryPlanContent.textContent = "N/A (Query was blocked by AST guardrail).";
        return;
      }

      // Populate Diagnosis
      const diag = data.diagnosis || {};
      if (resCategory) {
        resCategory.textContent = diag.error_category || "SQL_ERROR";
        resCategory.className = "badge badge-category";
      }

      const isSafe = data.verdict ? data.verdict.is_safe : true;
      if (resSafety) {
        resSafety.textContent = isSafe ? "SAFE (READ-ONLY)" : "MODERATE / HAZARD";
        resSafety.className = isSafe ? "badge badge-safety" : "badge badge-safety critical";
      }

      if (resModel) resModel.textContent = data.model_used || state.model;
      const confPercent = Math.round((diag.confidence || 0.95) * 100);
      if (resConfidenceBar) resConfidenceBar.style.width = `${confPercent}%`;
      if (resConfidenceText) resConfidenceText.textContent = `${confPercent}%`;

      if (resRootCause) resRootCause.textContent = diag.root_cause || "No explanation provided.";
      if (resTechnical) resTechnical.textContent = diag.technical_details || "No technical details.";
      if (resDiffSummary) resDiffSummary.textContent = diag.diff_explanation || "No remediation details.";
      if (resPrevention) resPrevention.textContent = diag.prevention_advice || "Follow standard SQL best practices.";

      // Terminal Output
      if (terminalStatusBadge && terminalOutput) {
        if (data.broken_error) {
          terminalStatusBadge.textContent = "ERROR DIAGNOSED";
          terminalStatusBadge.className = "badge badge-safety critical";
          terminalOutput.innerHTML = `[!] Initial Error Caught:\n${data.broken_error}\n\n[✓] AI Remediation generated successfully.`;
        } else {
          terminalStatusBadge.textContent = "DIAGNOSED";
          terminalStatusBadge.className = "badge badge-safety";
          terminalOutput.innerHTML = `<span class="terminal-success">[✓] Query analyzed and verified.</span>`;
        }
      }

      // Render Diff
      currentFixedSql = data.fixed_sql || "";
      currentDiffData = data.diff;
      renderDiff(data.diff);

      // Render Execution Table
      const exec = data.fixed_execution || {};
      if (exec.success) {
        if (metricStatus) {
          metricStatus.textContent = "Status: SUCCESS";
          metricStatus.style.color = "var(--accent-emerald)";
        }
        if (metricRows) metricRows.textContent = `Rows: ${exec.row_count}`;
        if (metricTime) metricTime.textContent = `Time: ${exec.execution_time_ms} ms`;
        renderTable(exec.columns, exec.rows);
      } else {
        if (metricStatus) {
          metricStatus.textContent = "Status: FAILED";
          metricStatus.style.color = "var(--accent-rose)";
        }
        if (metricRows) metricRows.textContent = "Rows: 0";
        if (metricTime) metricTime.textContent = `Time: ${exec.execution_time_ms || 0} ms`;
        if (execTableContainer) execTableContainer.innerHTML = `<p style="padding:16px; color:var(--accent-rose)">Execution Error: ${escapeHtml(exec.error || "Unknown error")}</p>`;
      }

      // Render Execution Plan
      if (queryPlanContent) {
        if (data.query_plan && data.query_plan.length > 0) {
          queryPlanContent.innerHTML = data.query_plan.map(p => `<div>[Step ${p.id}] Parent: ${p.parent} &rarr; ${escapeHtml(p.detail)}</div>`).join("");
        } else {
          queryPlanContent.textContent = "Direct scan or trivial execution.";
        }
      }

      // Scroll smoothly to results
      if (resultsSection) resultsSection.scrollIntoView({ behavior: "smooth" });

    } catch (err) {
      alert(`Error during diagnosis: ${err.message}`);
    } finally {
      if (btnExplainFix) {
        btnExplainFix.disabled = false;
        btnExplainFix.innerHTML = `
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"></path></svg>
          Explain &amp; Fix with AI
        `;
      }
    }
  }

  // 7. Render Diff (Split & Unified)
  function renderDiff(diffData) {
    if (!diffData || !diffData.left_lines) {
      if (diffLeftLines) diffLeftLines.innerHTML = `<div class="diff-line unchanged">${escapeHtml(sqlInput ? sqlInput.value : "")}</div>`;
      if (diffRightLines) diffRightLines.innerHTML = `<div class="diff-line unchanged">${escapeHtml(currentFixedSql)}</div>`;
      if (diffUnifiedText) diffUnifiedText.textContent = diffData ? (diffData.unified_text || "(No differences detected)") : "";
      return;
    }

    if (diffLeftLines) {
      diffLeftLines.innerHTML = diffData.left_lines.map(line => `
        <div class="diff-line ${line.status}">${line.line_no}: ${escapeHtml(line.text)}</div>
      `).join("");
    }

    if (diffRightLines) {
      diffRightLines.innerHTML = diffData.right_lines.map(line => `
        <div class="diff-line ${line.status}">${line.line_no}: ${escapeHtml(line.text)}</div>
      `).join("");
    }

    if (diffUnifiedText) {
      diffUnifiedText.textContent = diffData.unified_text || "(No differences detected)";
    }
  }

  // 8. Render Results Table
  function renderTable(columns, rows) {
    if (!columns || columns.length === 0) {
      execTableContainer.innerHTML = '<p class="table-placeholder">Query executed with 0 return columns (e.g. DML mutation).</p>';
      return;
    }
    if (!rows || rows.length === 0) {
      execTableContainer.innerHTML = '<p class="table-placeholder">Query returned 0 matching rows.</p>';
      return;
    }

    let html = '<table class="result-table"><thead><tr>';
    columns.forEach(col => {
      html += `<th>${escapeHtml(col)}</th>`;
    });
    html += '</tr></thead><tbody>';

    rows.forEach(row => {
      html += '<tr>';
      row.forEach(val => {
        html += `<td>${escapeHtml(val !== null ? String(val) : "NULL")}</td>`;
      });
      html += '</tr>';
    });
    html += '</tbody></table>';

    execTableContainer.innerHTML = html;
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

  // Start
  init();
});
