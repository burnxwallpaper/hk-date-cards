/* HK date-cards UI — Traditional Chinese (HK) */
(function () {
  const BUDGET_RANK = {
    "免費": 0,
    "$100內": 1,
    "$100–300": 2,
    "$300–600": 3,
    "$600+": 4,
  };

  const els = {
    grid: document.getElementById("grid"),
    count: document.getElementById("count"),
    meta: document.getElementById("meta"),
    type: document.getElementById("f-type"),
    occasion: document.getElementById("f-occasion"),
    mood: document.getElementById("f-mood"),
    budget: document.getElementById("f-budget"),
    excludeFamily: document.getElementById("f-exclude-family"),
    location: document.getElementById("f-location"),
    q: document.getElementById("f-q"),
    reset: document.getElementById("btn-reset"),
  };

  let all = [];

  function budgetOk(ev, cap) {
    if (!cap) return true;
    const tag = ev.budget_tag;
    // Unknown budget: keep visible unless "只看免費"
    if (!tag) {
      return cap !== "免費";
    }
    if (cap === "免費") return tag === "免費";
    const need = BUDGET_RANK[cap];
    const got = BUDGET_RANK[tag];
    if (need === undefined || got === undefined) return true;
    // Cap means "at or under this band"
    return got <= need;
  }

  function applyFilters() {
    const typ = els.type.value;
    const occ = els.occasion.value;
    const mood = els.mood.value;
    const cap = els.budget.value;
    const excl = els.excludeFamily.checked;
    const loc = els.location.value.trim();
    const q = els.q.value.trim();

    const out = all.filter((ev) => {
      const tags = ev.tags || [];
      if (typ && !tags.includes(typ)) return false;
      if (occ && !tags.includes(occ)) return false;
      if (mood && !tags.includes(mood)) return false;
      if (excl && tags.includes("親子向")) return false;
      if (!budgetOk(ev, cap)) return false;
      if (loc && !(ev.location || "").includes(loc)) return false;
      if (q && !(ev.title || "").includes(q) && !(ev.title_full || "").includes(q)) return false;
      return true;
    });
    render(out);
  }

  function budgetHtml(ev) {
    if (!ev.budget || ev.budget === "未知" || !ev.budget_tag) {
      return '<span class="budget-unknown">預算未知</span>';
    }
    if (ev.budget === "免費" || ev.budget_tag === "免費") {
      return '<span class="budget-free">免費</span>';
    }
    return `<span>${escapeHtml(ev.budget)}</span>`;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function render(list) {
    els.count.textContent = `${list.length}／${all.length}`;
    if (!list.length) {
      els.grid.innerHTML = '<div class="empty">冇符合條件嘅活動。試將場合改「全部」或放寬預算。</div>';
      return;
    }
    els.grid.innerHTML = list
      .map((ev) => {
        const tags = (ev.display_tags || []).slice(0, 2);
        const tagHtml = tags.map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");
        const date = ev.date_text || ev.start_date || "";
        return `<article class="card">
          <div class="tags">${tagHtml}</div>
          <h2>${escapeHtml(ev.title)}</h2>
          <div class="kv"><span class="label">預算</span>${budgetHtml(ev)}</div>
          <div class="kv"><span class="label">地點</span>${escapeHtml(ev.location || "地點待查")}</div>
          ${date ? `<div class="date">${escapeHtml(date)}</div>` : ""}
          <div class="src">${escapeHtml(ev.source || "")}${
            ev.source_url
              ? ` · <a href="${escapeHtml(ev.source_url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(ev.title_full || ev.title)}">來源</a>`
              : ""
          }${
            ev.title_full && ev.title_full !== ev.title
              ? ` · <span class="full-title" title="${escapeHtml(ev.title_full)}">全名</span>`
              : ""
          }</div>
        </article>`;
      })
      .join("");
  }

  function setDefaults() {
    els.type.value = "";
    els.occasion.value = "";
    els.mood.value = "";
    els.budget.value = "$100內";
    els.excludeFamily.checked = true;
    els.location.value = "";
    els.q.value = "";
    applyFilters();
  }

  ["change", "input"].forEach((evt) => {
    [els.type, els.occasion, els.mood, els.budget, els.excludeFamily, els.location, els.q].forEach((el) => {
      el.addEventListener(evt, applyFilters);
    });
  });
  els.reset.addEventListener("click", setDefaults);

  // GitHub Pages serves from repo root → ./data/; opening web/ locally → ../data/
  const path = (window.location.pathname || "").replace(/\\/g, "/");
  const inWeb = path.includes("/web/") || /\/web\/?$/.test(path);
  const dataUrl = new URL(inWeb ? "../data/events.json" : "./data/events.json", window.location.href).href;

  fetch(dataUrl)
    .then((r) => {
      if (!r.ok) throw new Error("events.json 讀取失敗");
      return r.json();
    })
    .then((data) => {
      all = data.events || [];
      const updated = data.updated_at || "";
      els.meta.textContent = updated ? `更新：${updated}` : `${all.length} 項活動`;
      applyFilters();
    })
    .catch((err) => {
      els.meta.textContent = "載入失敗";
      els.grid.innerHTML = `<div class="empty">${escapeHtml(err.message)}。請先運行 python refresh.py，再用本地伺服器開啟 web/。</div>`;
    });
})();
