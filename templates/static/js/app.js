/* ==========================================================
   MediAssist — shared app.js
   Generic helpers reused across pages. Page-specific data
   handling lives in an inline <script> at the bottom of each
   HTML file (placeholder logic — will be replaced by real
   Flask/MySQL calls during backend integration).
   ========================================================== */

function openModal(id) {
  const overlay = document.getElementById(id);
  if (overlay) overlay.classList.add("open");
}

function closeModal(id) {
  const overlay = document.getElementById(id);
  if (overlay) overlay.classList.remove("open");
}

// Close modal when clicking the dark overlay (not the modal box itself)
document.addEventListener("click", function (e) {
  if (e.target.classList && e.target.classList.contains("modal-overlay")) {
    e.target.classList.remove("open");
  }
});

// Close modal on Escape key
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape") {
    document.querySelectorAll(".modal-overlay.open").forEach((el) => el.classList.remove("open"));
  }
});

// Format an ISO date string as "12 Sep 2026"
function formatDate(isoDate) {
  const d = new Date(isoDate);
  if (isNaN(d)) return isoDate;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

// Format an ISO datetime string as "12 Sep, 10:30 AM"
function formatDateTime(isoDateTime) {
  const d = new Date(isoDateTime);
  if (isNaN(d)) return isoDateTime;
  const date = d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  const time = d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true });
  return `${date}, ${time}`;
}

/* ---------- Profile menu (top-right corner) ---------- */
function toggleProfileMenu(event) {
  event.stopPropagation();
  const menu = document.getElementById("profileMenu");
  if (!menu) return;
  const open = menu.classList.toggle("open");
  const trigger = menu.querySelector(".profile-trigger");
  if (trigger) trigger.setAttribute("aria-expanded", open ? "true" : "false");
}

// click anywhere else / press Escape -> close the profile menu
document.addEventListener("click", function (e) {
  const menu = document.getElementById("profileMenu");
  if (menu && !menu.contains(e.target)) menu.classList.remove("open");
});
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape") {
    const menu = document.getElementById("profileMenu");
    if (menu) menu.classList.remove("open");
  }
});
