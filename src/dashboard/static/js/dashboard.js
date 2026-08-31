(function () {
  "use strict";

  var THEME_KEY = "dep-dashboard-theme";
  var mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

  function savedTheme() {
    try {
      var saved = localStorage.getItem(THEME_KEY);
      return saved === "light" || saved === "dark" ? saved : null;
    } catch (error) {
      return null;
    }
  }

  function plotColors() {
    var styles = getComputedStyle(document.documentElement);
    return {
      text: styles.getPropertyValue("--muted").trim(),
      surface: styles.getPropertyValue("--surface").trim(),
      grid: styles.getPropertyValue("--chart-grid").trim()
    };
  }

  function updatePlots() {
    if (!window.Plotly) return;
    var colors = plotColors();
    document.querySelectorAll(".js-plotly-plot").forEach(function (chart) {
      window.Plotly.relayout(chart, {
        "font.color": colors.text,
        "font.family": "Roboto, Noto Sans, sans-serif",
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "xaxis.color": colors.text,
        "xaxis.gridcolor": colors.grid,
        "yaxis.color": colors.text,
        "yaxis.gridcolor": colors.grid,
        "legend.font.color": colors.text
      });
    });
  }

  function updateThemeControls(theme) {
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      var isDark = theme === "dark";
      button.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
      var label = button.querySelector("[data-theme-label]");
      var icon = button.querySelector("[data-theme-icon]");
      if (label) label.textContent = isDark ? "Light mode" : "Dark mode";
      if (icon) icon.textContent = isDark ? "☀" : "☾";
    });
  }

  function applyTheme(theme, persist) {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    if (persist) {
      try { localStorage.setItem(THEME_KEY, theme); } catch (error) {}
    }
    updateThemeControls(theme);
    window.requestAnimationFrame(updatePlots);
  }

  function initTheme() {
    var initial = document.documentElement.dataset.theme || (mediaQuery.matches ? "dark" : "light");
    applyTheme(initial, false);
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      button.addEventListener("click", function () {
        applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);
      });
    });
    mediaQuery.addEventListener("change", function (event) {
      if (!savedTheme()) applyTheme(event.matches ? "dark" : "light", false);
    });
  }

  function initDrawer() {
    var sidebar = document.querySelector("[data-sidebar]");
    var openButton = document.querySelector("[data-drawer-open]");
    var closeButton = document.querySelector("[data-drawer-close]");
    var overlay = document.querySelector("[data-drawer-overlay]");
    if (!sidebar || !openButton || !closeButton || !overlay) return;

    var lastFocused;
    function focusableItems() {
      return Array.from(sidebar.querySelectorAll("a[href], button:not([disabled]), input, select"));
    }
    function openDrawer() {
      lastFocused = document.activeElement;
      sidebar.classList.add("is-open");
      document.body.classList.add("drawer-open");
      overlay.hidden = false;
      openButton.setAttribute("aria-expanded", "true");
      closeButton.focus();
    }
    function closeDrawer() {
      sidebar.classList.remove("is-open");
      document.body.classList.remove("drawer-open");
      overlay.hidden = true;
      openButton.setAttribute("aria-expanded", "false");
      if (lastFocused) lastFocused.focus();
    }

    openButton.addEventListener("click", openDrawer);
    closeButton.addEventListener("click", closeDrawer);
    overlay.addEventListener("click", closeDrawer);
    document.addEventListener("keydown", function (event) {
      if (!sidebar.classList.contains("is-open")) return;
      if (event.key === "Escape") {
        event.preventDefault();
        closeDrawer();
      }
      if (event.key === "Tab") {
        var items = focusableItems();
        if (!items.length) return;
        var first = items[0];
        var last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    });
    window.matchMedia("(min-width: 821px)").addEventListener("change", function (event) {
      if (event.matches && sidebar.classList.contains("is-open")) closeDrawer();
    });
  }

  function initInterventionFilters() {
    var table = document.querySelector("[data-intervention-table]");
    if (!table) return;
    var search = document.querySelector("[data-table-search]");
    var milestone = document.querySelector("[data-table-milestone]");
    var status = document.querySelector("[data-table-status]");
    var schedule = document.querySelector("[data-table-schedule]");
    var rows = Array.from(table.querySelectorAll("[data-intervention-row]"));
    var count = document.querySelector("[data-visible-count]");
    var empty = document.querySelector("[data-filter-empty]");

    function normalize(value) { return String(value || "").trim().toLocaleLowerCase(); }
    function filterRows() {
      var query = normalize(search.value);
      var selectedMilestone = normalize(milestone.value);
      var selectedStatus = normalize(status.value);
      var selectedSchedule = normalize(schedule.value);
      var visible = 0;
      rows.forEach(function (row) {
        var matches = (!query || normalize(row.dataset.search).includes(query)) &&
          (!selectedMilestone || normalize(row.dataset.milestone) === selectedMilestone) &&
          (!selectedStatus || normalize(row.dataset.status) === selectedStatus) &&
          (!selectedSchedule || normalize(row.dataset.schedule) === selectedSchedule);
        row.hidden = !matches;
        if (matches) visible += 1;
      });
      count.textContent = String(visible);
      empty.hidden = visible !== 0;
      table.hidden = visible === 0;
    }

    search.addEventListener("input", filterRows);
    milestone.addEventListener("change", filterRows);
    status.addEventListener("change", filterRows);
    schedule.addEventListener("change", filterRows);
  }

  function init() {
    initTheme();
    initDrawer();
    initInterventionFilters();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
}());
