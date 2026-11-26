const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  if (tg.requestFullscreen) {
    try { tg.requestFullscreen(); } catch (_) {}
  }
}

let state = {
  items: [],
  botUsername: "",
  filterType: "all",
  editingSlug: null,
  expandedBatches: {},
  activeQrUrl: "",
  activePreviewSlug: null,
};

const els = {
  vaultTitle: document.getElementById("vaultTitle"),
  vaultStats: document.getElementById("vaultStats"),
  pinHomeBtn: document.getElementById("pinHomeBtn"),
  searchInput: document.getElementById("searchInput"),
  sortSelect: document.getElementById("sortSelect"),
  filterPills: document.getElementById("filterPills"),
  itemsList: document.getElementById("itemsList"),
  refreshBtn: document.getElementById("refreshBtn"),
  editModal: document.getElementById("editModal"),
  editTitleInput: document.getElementById("editTitleInput"),
  editTextGroup: document.getElementById("editTextGroup"),
  editTextContent: document.getElementById("editTextContent"),
  toggleRulesBtn: document.getElementById("toggleRulesBtn"),
  rulesContent: document.getElementById("rulesContent"),
  rulesChevron: document.getElementById("rulesChevron"),
  rulePinInput: document.getElementById("rulePinInput"),
  ruleExpirySelect: document.getElementById("ruleExpirySelect"),
  ruleMaxDownloads: document.getElementById("ruleMaxDownloads"),
  cancelEditBtn: document.getElementById("cancelEditBtn"),
  saveEditBtn: document.getElementById("saveEditBtn"),
  qrModal: document.getElementById("qrModal"),
  qrTitle: document.getElementById("qrTitle"),
  qrCanvas: document.getElementById("qrCanvas"),
  closeQrBtn: document.getElementById("closeQrBtn"),
  copyQrLinkBtn: document.getElementById("copyQrLinkBtn"),
  previewModal: document.getElementById("previewModal"),
  previewTitle: document.getElementById("previewTitle"),
  previewContainer: document.getElementById("previewContainer"),
  closePreviewBtn: document.getElementById("closePreviewBtn"),
  sendFromPreviewBtn: document.getElementById("sendFromPreviewBtn"),
  toast: document.getElementById("toast"),
};

// Show Home Screen Shortcut button if supported by client
if (tg?.addToHomeScreen) {
  els.pinHomeBtn.classList.remove("hidden");
  els.pinHomeBtn.onclick = () => {
    try {
      tg.addToHomeScreen();
    } catch (_) {
      showToast("Home screen shortcut not supported on this device");
    }
  };
}

function showToast(msg) {
  els.toast.textContent = msg;
  els.toast.classList.remove("hidden");
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => els.toast.classList.add("hidden"), 2600);
}

function haptic(type = "light") {
  try {
    tg?.HapticFeedback?.impactOccurred(type);
  } catch (_) {}
}

// --- DeviceStorage / LocalStorage Instant Cache ---
function readCache() {
  try {
    const raw = localStorage.getItem("vault_items_cache");
    if (raw) {
      const parsed = JSON.parse(raw);
      state.items = parsed.items || [];
      state.botUsername = parsed.botUsername || "";
      if (state.items.length) renderItems();
    }
  } catch (_) {}
  if (tg?.DeviceStorage?.getItem) {
    tg.DeviceStorage.getItem("vault_items_cache", (err, val) => {
      if (!err && val) {
        try {
          const parsed = JSON.parse(val);
          state.items = parsed.items || [];
          state.botUsername = parsed.botUsername || "";
          renderItems();
        } catch (_) {}
      }
    });
  }
}

function writeCache(items, botUsername) {
  const payload = JSON.stringify({ items, botUsername });
  try {
    localStorage.setItem("vault_items_cache", payload);
  } catch (_) {}
  if (tg?.DeviceStorage?.setItem) {
    try { tg.DeviceStorage.setItem("vault_items_cache", payload); } catch (_) {}
  }
}

function formatBytes(bytes) {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val.toFixed(1)} ${units[i]}`;
}

async function apiFetch(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    "X-Telegram-Init-Data": tg?.initData || "",
    ...(options.headers || {}),
  };
  const res = await fetch(path, { ...options, headers });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

async function loadItems() {
  const q = encodeURIComponent(els.searchInput.value.trim());
  const type = encodeURIComponent(state.filterType);
  const sort = encodeURIComponent(els.sortSelect.value);

  try {
    const data = await apiFetch(`/api/items?q=${q}&type=${type}&sort=${sort}`);
    state.items = data.items || [];
    state.botUsername = data.bot_username || "";
    if (!q && type === "all") {
      writeCache(state.items, state.botUsername);
    }
    const ownerName = data.user?.first_name ? `${data.user.first_name}'s Vault` : "My Vault";
    els.vaultTitle.textContent = ownerName;
    els.vaultStats.textContent = `${state.items.length} item(s) stored by you`;
    renderItems();
  } catch (err) {
    if (!state.items.length) {
      els.itemsList.innerHTML = `<div class="empty-state">⚠️ ${err.message}<br/>Open this Mini App directly from your Telegram bot chat.</div>`;
    }
  }
}

function renderItems() {
  if (!state.items.length) {
    els.itemsList.innerHTML = `<div class="empty-state">No stored items found.<br/>Send any file, <b>/text</b>, or <b>/wizard</b> to the bot to populate your vault!</div>`;
    return;
  }

  els.itemsList.innerHTML = state.items
    .map((item) => {
      const subItems = item.sub_items || [];
      const countLabel =
        item.type === "batch"
          ? `${subItems.length || (item.message_ids || []).length} items`
          : formatBytes(item.file_size);
      const dateStr = item.created_at
        ? new Date(item.created_at).toLocaleDateString()
        : "";
      const metaParts = [countLabel, `${item.downloads || 0} opens`, dateStr].filter(Boolean);

      // Rule Badges
      let ruleBadges = "";
      if (item.pin_code) ruleBadges += `<span class="badge rule-badge">🔐 PIN</span>`;
      if (item.expires_at) ruleBadges += `<span class="badge rule-badge">⌛ EXP</span>`;
      if (item.max_downloads > 0) ruleBadges += `<span class="badge rule-badge">💥 ${item.max_downloads}x</span>`;

      const previewHtml =
        item.type === "text" && item.text_content
          ? `<div class="text-preview">${escapeHtml(item.text_content)}</div>`
          : "";

      // Batch Drawer HTML
      const isExpanded = !!state.expandedBatches[item.slug];
      let batchDrawerHtml = "";
      if (item.type === "batch" && isExpanded) {
        const rows = subItems
          .map(
            (sub, idx) => `
            <div class="sub-item-row">
              <span class="sub-item-name">${idx + 1}. ${escapeHtml(sub.title || `Item #${idx + 1}`)}</span>
              <div class="sub-btns">
                <button class="mini-btn" onclick="moveSubItem('${item.slug}', ${idx}, -1)" ${idx === 0 ? "disabled" : ""}>↑</button>
                <button class="mini-btn" onclick="moveSubItem('${item.slug}', ${idx}, 1)" ${idx === subItems.length - 1 ? "disabled" : ""}>↓</button>
                <button class="mini-btn get" onclick="deliverSubItem('${item.slug}', ${sub.msg_id})">Get</button>
                <button class="mini-btn del" onclick="removeSubItem('${item.slug}', ${idx})">✕</button>
              </div>
            </div>`
          )
          .join("");
        batchDrawerHtml = `<div class="batch-drawer">${rows}</div>`;
      }

      // 3rd Button: Inspect Batch OR Preview Media OR Copy Text
      let thirdBtn = `<button class="act-btn" onclick="copyLink('${item.slug}')">🔗 Copy</button>`;
      if (item.type === "batch") {
        thirdBtn = `<button class="act-btn" onclick="toggleBatchDrawer('${item.slug}')">${isExpanded ? "▲ Hide" : "📂 Items"}</button>`;
      } else if (item.type === "single" && (item.mime_type?.startsWith("image/") || item.mime_type?.startsWith("audio/") || item.mime_type?.startsWith("video/"))) {
        thirdBtn = `<button class="act-btn" onclick="openMediaPreview('${item.slug}')">👁 View</button>`;
      }

      return `
      <div class="item-card" data-slug="${item.slug}">
        <div class="item-top">
          <div class="item-title">${escapeHtml(item.title)}</div>
          <div class="badges-wrap">
            ${ruleBadges}
            <span class="badge">${item.type === "single" ? "FILE" : item.type.toUpperCase()}</span>
          </div>
        </div>
        <div class="item-meta">${metaParts.join(" • ")}</div>
        ${previewHtml}
        ${batchDrawerHtml}
        <div class="actions-grid">
          <button class="act-btn get-btn" onclick="deliverItem('${item.slug}')">📥 Get</button>
          <button class="act-btn" onclick="shareItem('${item.slug}')">📤 Share</button>
          ${thirdBtn}
          <button class="act-btn" onclick="openQrModal('${item.slug}')">📱 QR</button>
          <button class="act-btn" onclick="openEditModal('${item.slug}')">✏️ Edit</button>
          <button class="act-btn del-btn" onclick="deleteItem('${item.slug}')">🗑 Del</button>
        </div>
      </div>`;
    })
    .join("");
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// --- Batch Drawer Actions ---
window.toggleBatchDrawer = function (slug) {
  haptic("light");
  state.expandedBatches[slug] = !state.expandedBatches[slug];
  renderItems();
};

window.deliverSubItem = async function (slug, msgId) {
  haptic("medium");
  try {
    showToast("Sending selected item to chat...");
    await apiFetch(`/api/deliver/${slug}`, {
      method: "POST",
      body: JSON.stringify({ msg_id: msgId }),
    });
    showToast("✅ Sent to chat!");
  } catch (err) {
    showToast(`❌ ${err.message}`);
  }
};

window.moveSubItem = async function (slug, idx, dir) {
  const item = state.items.find((x) => x.slug === slug);
  if (!item || !item.sub_items) return;
  const targetIdx = idx + dir;
  if (targetIdx < 0 || targetIdx >= item.sub_items.length) return;

  const updatedList = [...item.sub_items];
  const [moved] = updatedList.splice(idx, 1);
  updatedList.splice(targetIdx, 0, moved);

  try {
    haptic("light");
    const res = await apiFetch(`/api/items/${slug}`, {
      method: "PATCH",
      body: JSON.stringify({ sub_items: updatedList }),
    });
    Object.assign(item, res.item);
    renderItems();
  } catch (err) {
    showToast(`❌ ${err.message}`);
  }
};

window.removeSubItem = async function (slug, idx) {
  const item = state.items.find((x) => x.slug === slug);
  if (!item || !item.sub_items) return;
  if (item.sub_items.length <= 1) {
    return showToast("Use 🗑 Del to delete the last remaining item.");
  }

  const updatedList = item.sub_items.filter((_, i) => i !== idx);
  try {
    haptic("medium");
    const res = await apiFetch(`/api/items/${slug}`, {
      method: "PATCH",
      body: JSON.stringify({ sub_items: updatedList }),
    });
    Object.assign(item, res.item);
    renderItems();
    showToast("Removed item from batch");
  } catch (err) {
    showToast(`❌ ${err.message}`);
  }
};

// --- QR Code Modal ---
window.openQrModal = function (slug) {
  haptic("light");
  const item = state.items.find((x) => x.slug === slug);
  if (!item) return;
  const url = `https://t.me/${state.botUsername}?start=${slug}`;
  state.activeQrUrl = url;
  els.qrTitle.textContent = item.title;
  els.qrCanvas.innerHTML = "";
  new QRCode(els.qrCanvas, {
    text: url,
    width: 190,
    height: 190,
    colorDark: "#000000",
    colorLight: "#ffffff",
  });
  els.qrModal.classList.remove("hidden");
};

els.closeQrBtn.onclick = () => els.qrModal.classList.add("hidden");
els.copyQrLinkBtn.onclick = async () => {
  try {
    await navigator.clipboard.writeText(state.activeQrUrl);
    showToast("🔗 Link copied!");
  } catch (_) {
    showToast(state.activeQrUrl);
  }
};

// --- In-App Media Preview ---
window.openMediaPreview = function (slug) {
  haptic("light");
  const item = state.items.find((x) => x.slug === slug);
  if (!item) return;
  state.activePreviewSlug = slug;
  els.previewTitle.textContent = item.title;

  const streamUrl = `/api/preview/${slug}?initData=${encodeURIComponent(tg?.initData || "")}`;
  const mime = item.mime_type || "";

  if (mime.startsWith("image/")) {
    els.previewContainer.innerHTML = `<img src="${streamUrl}" alt="Preview" onerror="this.parentElement.textContent='Preview unavailable (file >15MB)'" />`;
  } else if (mime.startsWith("audio/")) {
    els.previewContainer.innerHTML = `<audio controls autoplay src="${streamUrl}"></audio>`;
  } else if (mime.startsWith("video/")) {
    els.previewContainer.innerHTML = `<video controls playsinline src="${streamUrl}"></video>`;
  } else {
    els.previewContainer.textContent = "Preview not supported for this file format.";
  }
  els.previewModal.classList.remove("hidden");
};

els.closePreviewBtn.onclick = () => {
  els.previewContainer.innerHTML = "";
  els.previewModal.classList.add("hidden");
};
els.sendFromPreviewBtn.onclick = () => {
  if (state.activePreviewSlug) {
    window.deliverItem(state.activePreviewSlug);
    els.previewModal.classList.add("hidden");
  }
};

// --- Standard Delivery, Share, Edit & Delete ---
window.deliverItem = async function (slug) {
  haptic("medium");
  try {
    showToast("Sending to your Telegram chat...");
    const res = await apiFetch(`/api/deliver/${slug}`, { method: "POST" });
    showToast(res.message || "Sent to chat!");
    loadItems();
  } catch (err) {
    showToast(`❌ ${err.message}`);
  }
};

window.copyLink = async function (slug) {
  haptic("light");
  const url = `https://t.me/${state.botUsername}?start=${slug}`;
  try {
    await navigator.clipboard.writeText(url);
    showToast("🔗 Link copied!");
  } catch (_) {
    showToast(url);
  }
};

window.shareItem = async function (slug) {
  haptic("light");
  try {
    const res = await apiFetch(`/api/prepare-share/${slug}`, { method: "POST" });
    if (res.prepared_id && tg?.shareMessage) {
      tg.shareMessage(res.prepared_id, (sent) => {
        if (sent) showToast("📤 Shared!");
      });
    } else {
      window.copyLink(slug);
    }
  } catch (_) {
    window.copyLink(slug);
  }
};

els.toggleRulesBtn.onclick = () => {
  const isHidden = els.rulesContent.classList.toggle("hidden");
  els.rulesChevron.textContent = isHidden ? "▼" : "▲";
};

window.openEditModal = function (slug) {
  haptic("light");
  const item = state.items.find((x) => x.slug === slug);
  if (!item) return;
  state.editingSlug = slug;
  els.editTitleInput.value = item.title || "";

  if (item.type === "text") {
    els.editTextGroup.classList.remove("hidden");
    els.editTextContent.value = item.text_content || "";
  } else {
    els.editTextGroup.classList.add("hidden");
    els.editTextContent.value = "";
  }

  // Populate existing Link Rules
  els.rulePinInput.value = item.pin_code || "";
  els.ruleExpirySelect.value = item.expires_at ? "24" : "0";
  els.ruleMaxDownloads.value = item.max_downloads || 0;

  // Auto-open Link Rules drawer if any rule is currently active
  const hasRules = !!(item.pin_code || item.expires_at || item.max_downloads > 0);
  els.rulesContent.classList.toggle("hidden", !hasRules);
  els.rulesChevron.textContent = hasRules ? "▲" : "▼";

  els.editModal.classList.remove("hidden");
};

els.cancelEditBtn.onclick = () => {
  state.editingSlug = null;
  els.editModal.classList.add("hidden");
};

els.saveEditBtn.onclick = async () => {
  if (!state.editingSlug) return;
  const payload = {
    title: els.editTitleInput.value.trim(),
    pin_code: els.rulePinInput.value.trim(),
    expire_hours: parseInt(els.ruleExpirySelect.value, 10) || 0,
    max_downloads: parseInt(els.ruleMaxDownloads.value, 10) || 0,
  };
  if (!els.editTextGroup.classList.contains("hidden")) {
    payload.text_content = els.editTextContent.value;
  }
  try {
    await apiFetch(`/api/items/${state.editingSlug}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    haptic("medium");
    els.editModal.classList.add("hidden");
    showToast("✅ Saved changes & link rules!");
    loadItems();
  } catch (err) {
    showToast(`❌ ${err.message}`);
  }
};

window.deleteItem = async function (slug) {
  const item = state.items.find((x) => x.slug === slug);
  if (!item) return;

  const confirmDelete = async () => {
    try {
      await apiFetch(`/api/items/${slug}`, { method: "DELETE" });
      haptic("heavy");
      showToast("🗑️ Deleted from your vault");
      loadItems();
    } catch (err) {
      showToast(`❌ ${err.message}`);
    }
  };

  if (tg?.showConfirm) {
    tg.showConfirm(`Delete "${item.title}" permanently from your vault?`, (ok) => {
      if (ok) confirmDelete();
    });
  } else if (confirm(`Delete "${item.title}" permanently?`)) {
    confirmDelete();
  }
};

let searchDebounce;
els.searchInput.addEventListener("input", () => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(loadItems, 250);
});

els.sortSelect.addEventListener("change", loadItems);
els.refreshBtn.addEventListener("click", () => {
  haptic("light");
  loadItems();
});

els.filterPills.addEventListener("click", (e) => {
  const btn = e.target.closest(".pill");
  if (!btn) return;
  document.querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
  btn.classList.add("active");
  state.filterType = btn.dataset.type;
  haptic("light");
  loadItems();
});

readCache();
loadItems();
