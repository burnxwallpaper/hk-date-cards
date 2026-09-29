/* HK 活動卡片 UI — Traditional Chinese (HK) */
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
    tabs: document.getElementById("view-tabs"),
  };

  let all = [];
  /** @type {"events"|"evergreen"} */
  let activeTab = "events";

  function isEvergreen(ev) {
    return ev && ev.evergreen === true;
  }

  function tabPool() {
    if (activeTab === "evergreen") {
      return all.filter(isEvergreen);
    }
    return all.filter((ev) => !isEvergreen(ev));
  }

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
    const pool = tabPool();

    const out = pool.filter((ev) => {
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
    render(out, pool.length);
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

  function cleanText(s) {
    return String(s || "")
      .replace(/\u00a0/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  /** Shortened time for cards. Empty → omit row (never 待定/未知). */
  function shortScheduleLabel(ev) {
    const raw = cleanText(ev.date_text || "");
    const md = (iso) => {
      const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
      if (!m) return iso || "";
      return `${parseInt(m[2], 10)}/${parseInt(m[3], 10)}`;
    };

    if (!raw) {
      const sd = (ev.start_date || "").trim();
      const ed = (ev.end_date || "").trim();
      if (sd && ed && sd !== ed) return `${md(sd)}–${md(ed)}`;
      if (sd) return md(sd) || sd;
      return "";
    }

    // 17.10.2026 (六) 3pm – 4:30pm → 10/17 六 3–4:30pm
    let m = /^(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*(?:\(([^)]+)\))?\s*(.*)$/.exec(raw);
    if (m) {
      const d = parseInt(m[1], 10);
      const mo = parseInt(m[2], 10);
      const wd = cleanText(m[4] || "");
      let rest = cleanText(m[5] || "").replace(/[–—]/g, "–").replace(/\s*–\s*/g, "–");
      const bits = [`${mo}/${d}`];
      if (wd) bits.push(wd);
      if (rest) bits.push(rest);
      return bits.join(" ").slice(0, 60);
    }

    // 2026年9月25日至2027年1月3日 …
    m = /^(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日(?:\s*[至到\-–—~～]\s*(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*日)?\s*(.*)$/.exec(raw);
    if (m) {
      const y1 = parseInt(m[1], 10);
      const mo1 = parseInt(m[2], 10);
      const d1 = parseInt(m[3], 10);
      let head = `${mo1}/${d1}`;
      if (m[6]) {
        const y2 = m[4] ? parseInt(m[4], 10) : y1;
        const mo2 = parseInt(m[5], 10);
        const d2 = parseInt(m[6], 10);
        head = y2 !== y1 ? `${y1}/${mo1}/${d1}–${y2}/${mo2}/${d2}` : `${mo1}/${d1}–${mo2}/${d2}`;
      }
      let rest = cleanText(m[7] || "");
      rest = rest.replace(/星期二至日/g, "二至日").replace(/上午\s*/g, "").replace(/晚上\s*/g, "");
      rest = rest.replace(/至/g, "–");
      if (rest.length > 36) rest = rest.slice(0, 33).replace(/[，,;；、\s]+$/, "") + "…";
      return cleanText(`${head} ${rest}`).slice(0, 60);
    }

    m = /^(\d{4})-(\d{2})-(\d{2})\s*至\s*(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
    if (m) {
      return `${parseInt(m[2], 10)}/${parseInt(m[3], 10)}–${parseInt(m[5], 10)}/${parseInt(m[6], 10)}`;
    }
    m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
    if (m) return `${parseInt(m[2], 10)}/${parseInt(m[3], 10)}`;

    return raw.length > 56 ? raw.slice(0, 53).replace(/[，,;；、\s]+$/, "") + "…" : raw;
  }

  function render(list, poolSize) {
    const total = poolSize == null ? tabPool().length : poolSize;
    els.count.textContent = `${list.length}／${total}`;
    if (!list.length) {
      const emptyMsg =
        activeTab === "evergreen"
          ? "冇符合條件嘅常設免費場地。試放寬篩選。"
          : "冇符合條件嘅活動。試將場合改「全部」或放寬預算。";
      els.grid.innerHTML = `<div class="empty">${emptyMsg}</div>`;
      return;
    }
    els.grid.innerHTML = list
      .map((ev) => {
        const tags = (ev.display_tags || []).slice(0, 2);
        const tagHtml = tags.map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");
        const timeLabel = shortScheduleLabel(ev);
        const timeRow = timeLabel
          ? `<div class="kv"><span class="label">時間</span>${escapeHtml(timeLabel)}</div>`
          : "";
        return `<article class="card">
          <div class="tags">${tagHtml}</div>
          <h2>${escapeHtml(ev.title)}</h2>
          ${timeRow}
          <div class="kv"><span class="label">預算</span>${budgetHtml(ev)}</div>
          <div class="kv"><span class="label">地點</span>${escapeHtml(ev.location || "地點待查")}</div>
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

  function setDefaultsForTab() {
    els.type.value = "";
    els.mood.value = "";
    els.budget.value = "$100內";
    els.excludeFamily.checked = true;
    els.location.value = "";
    els.q.value = "";
    // 常設免費 / 活動: never lock weekend as default occasion
    els.occasion.value = "";
    applyFilters();
  }

  function setActiveTab(tab) {
    activeTab = tab === "evergreen" ? "evergreen" : "events";
    if (els.tabs) {
      els.tabs.querySelectorAll("[data-tab]").forEach((btn) => {
        const on = btn.getAttribute("data-tab") === activeTab;
        btn.classList.toggle("is-active", on);
        btn.setAttribute("aria-selected", on ? "true" : "false");
      });
    }
    if (activeTab === "evergreen") {
      els.occasion.value = "";
    }
    applyFilters();
  }

  if (els.tabs) {
    els.tabs.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-tab]");
      if (!btn) return;
      setActiveTab(btn.getAttribute("data-tab"));
    });
  }

  ["change", "input"].forEach((evt) => {
    [els.type, els.occasion, els.mood, els.budget, els.excludeFamily, els.location, els.q].forEach((el) => {
      el.addEventListener(evt, applyFilters);
    });
  });
  els.reset.addEventListener("click", setDefaultsForTab);

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
      els.meta.textContent = updated ? `更新：${updated}` : `${all.length} 項`;
      setDefaultsForTab();
    })
    .catch((err) => {
      els.meta.textContent = "載入失敗";
      els.grid.innerHTML = `<div class="empty">${escapeHtml(err.message)}。請先運行 python refresh.py，再用本地伺服器開啟 web/。</div>`;
    });
})();
