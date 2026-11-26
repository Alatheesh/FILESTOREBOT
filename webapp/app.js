const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

let state = {
  items: [],
  botUsername: "",
  filterType: "all",
  editingSlug: null,
};

const els = {
  vaultTitle: document.getElementById("vaultTitle"),
  vaultStats: document.getElementById("vaultStats"),
  searchInput: document.getElementById("searchInput"),
  sortSelect: document.getElementById("sortSelect"),
  filterPills: document.getElementById("filterPills"),
  itemsList: document.getElementById("itemsList"),
  refreshBtn: document.getElementById("refreshBtn"),
  editModal: document.getElementById("editModal"),
  editTitleInput: document.getElementById("editTitleInput"),
  editTextGroup: document.getElementById("editTextGroup"),
  editTextContent: document.getElementById("editTextContent"),
  cancelEditBtn: document.getElementById("cancelEditBtn"),
  saveEditBtn: document.getElementById("saveEditBtn"),
  toast: document.getElementById("toast"),
};

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
    const ownerName = data.user?.first_name ? `${data.user.first_name}'s Vault` : "My Vault";
    els.vaultTitle.textContent = ownerName;
    els.vaultStats.textContent = `${state.items.length} item(s) stored by you`;
    renderItems();
  } catch (err) {
    els.itemsList.innerHTML = `<div class="empty-state">⚠️ ${err.message}<br/>Open this Mini App directly from your Telegram bot chat.</div>`;
  }
}

function renderItems() {
  if (!state.items.length) {
    els.itemsList.innerHTML = `<div class="empty-state">No stored items found.<br/>Send any file, <b>/text</b>, or <b>/wizard</b> to the bot to populate your vault!</div>`;
    return;
  }

  els.itemsList.innerHTML = state.items
    .map((item) => {
      const countLabel =
        item.type === "batch"
          ? `${(item.message_ids || []).length} items`
          : formatBytes(item.file_size);
      const dateStr = item.created_at
        ? new Date(item.created_at).toLocaleDateString()
        : "";
      const metaParts = [countLabel, `${item.downloads || 0} opens`, dateStr].filter(Boolean);

      const previewHtml =
        item.type === "text" && item.text_content
          ? `<div class="text-preview">${escapeHtml(item.text_content)}</div>`
          : "";

      return `
      <div class="item-card" data-slug="${item.slug}">
        <div class="item-top">
          <div class="item-title">${escapeHtml(item.title)}</div>
          <span class="badge">${item.type === "single" ? "FILE" : item.type.toUpperCase()}</span>
        </div>
        <div class="item-meta">${metaParts.join(" • ")}</div>
        ${previewHtml}
        <div class="actions-grid">
          <button class="act-btn get-btn" onclick="deliverItem('${item.slug}')">📥 Get</button>
          <button class="act-btn" onclick="shareItem('${item.slug}')">📤 Share</button>
          <button class="act-btn" onclick="copyLink('${item.slug}')">🔗 Copy</button>
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
  } catch (err) {
    window.copyLink(slug);
  }
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
  els.editModal.classList.remove("hidden");
};

els.cancelEditBtn.onclick = () => {
  state.editingSlug = null;
  els.editModal.classList.add("hidden");
};

els.saveEditBtn.onclick = async () => {
  if (!state.editingSlug) return;
  const payload = { title: els.editTitleInput.value.trim() };
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
    showToast("✅ Updated successfully!");
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

// Event Listeners
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

loadItems();
