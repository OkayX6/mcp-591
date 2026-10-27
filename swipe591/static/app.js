"use strict";

// --- api -------------------------------------------------------------------

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "content-type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  if (res.status === 401 && path !== "/api/login") {
    showLogin();
    throw new Error("signed out");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const detail = Array.isArray(err.detail) ? err.detail.map((d) => d.msg).join(", ") : err.detail;
    throw new Error(detail || res.statusText);
  }
  return res.status === 204 ? null : res.json();
}

const $ = (sel) => document.querySelector(sel);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const money = (n) => (n == null ? "?" : n.toLocaleString("fr-FR") + " NT$");

// --- login -----------------------------------------------------------------

function showLogin() {
  $("#app").hidden = true;
  $("#login").hidden = false;
  $("#password").focus();
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    await api("POST", "/api/login", { password: $("#password").value });
    $("#password").value = "";
    start();
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

// --- tabs ------------------------------------------------------------------

const loaders = { deck: loadDeck, liked: () => loadList("liked"), disliked: () => loadList("disliked"), searches: loadSearches };

document.querySelectorAll(".tabs button").forEach((btn) =>
  btn.addEventListener("click", () => showView(btn.dataset.view)),
);

function showView(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== `view-${name}`));
  loaders[name]();
}

// --- deck ------------------------------------------------------------------

let queue = [];
const history = []; // post ids judged in this session, for undo

async function loadDeck() {
  queue = await api("GET", "/api/deck?limit=30");
  renderDeck();
}

function renderDeck() {
  const deck = $("#deck");
  deck.replaceChildren();
  $("#deck-empty").hidden = queue.length > 0;
  $("#deck-count").textContent = queue.length ? `${queue.length}${queue.length === 30 ? "+" : ""} à voir` : "";
  // Two cards: the top one and the one revealed under it.
  queue.slice(0, 2).reverse().forEach((listing, i, shown) => {
    const card = buildCard(listing);
    if (i === shown.length - 1) enableSwipe(card, listing);
    else card.style.transform = "scale(0.96)";
    deck.append(card);
  });
}

function buildCard(listing) {
  const card = $("#card-template").content.firstElementChild.cloneNode(true);
  const photos = listing.photos?.length ? listing.photos : [""];
  let index = 0;
  const img = card.querySelector("img");
  const dots = card.querySelector(".dots");
  const showPhoto = () => {
    img.src = photos[index];
    dots.replaceChildren(...photos.map((_, i) => Object.assign(document.createElement("span"), { className: i === index ? "on" : "" })));
  };
  showPhoto();
  card.querySelector(".photo").addEventListener("click", (e) => {
    if (card.dataset.dragged) return;
    const left = e.offsetX < e.currentTarget.clientWidth / 2;
    index = (index + (left ? photos.length - 1 : 1)) % photos.length;
    showPhoto();
  });
  card.querySelector(".price").textContent = `${money(listing.price)} / mois`;
  card.querySelector(".title").textContent = listing.title;
  card.querySelector(".meta").textContent = [listing.layout, listing.area, listing.floor, listing.address]
    .filter(Boolean)
    .join(" · ");
  card.querySelector(".tags").replaceChildren(
    ...(listing.tags || []).slice(0, 6).map((t) => Object.assign(document.createElement("span"), { textContent: t })),
  );
  return card;
}

function enableSwipe(card, listing) {
  let startX = 0, startY = 0, dx = 0, dy = 0, dragging = false;
  const stamps = {
    like: card.querySelector(".stamp-like"),
    nope: card.querySelector(".stamp-nope"),
    super: card.querySelector(".stamp-super"),
  };
  card.addEventListener("pointerdown", (e) => {
    dragging = true;
    startX = e.clientX;
    startY = e.clientY;
    dx = dy = 0;
    delete card.dataset.dragged;
    card.classList.remove("back");
    card.setPointerCapture(e.pointerId);
  });
  card.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    dx = e.clientX - startX;
    dy = e.clientY - startY;
    if (Math.abs(dx) + Math.abs(dy) > 8) card.dataset.dragged = "1";
    card.style.transform = `translate(${dx}px, ${dy}px) rotate(${dx / 18}deg)`;
    stamps.like.style.opacity = Math.max(0, dx / 100);
    stamps.nope.style.opacity = Math.max(0, -dx / 100);
    stamps.super.style.opacity = Math.max(0, -dy / 120 - Math.abs(dx) / 200);
  });
  const end = () => {
    if (!dragging) return;
    dragging = false;
    const w = card.clientWidth;
    if (dx > w * 0.3) decide(listing, "like", card);
    else if (dx < -w * 0.3) decide(listing, "dislike", card);
    else if (dy < -card.clientHeight * 0.25) decide(listing, "superlike", card);
    else {
      card.classList.add("back");
      card.style.transform = "";
      Object.values(stamps).forEach((s) => (s.style.opacity = 0));
    }
    // Let the photo click handler see that this was a drag, then forget it.
    setTimeout(() => delete card.dataset.dragged, 0);
  };
  card.addEventListener("pointerup", end);
  card.addEventListener("pointercancel", end);
}

async function decide(listing, verdict, card = $("#deck .card:last-child")) {
  if (!listing) return;
  if (card) {
    const x = verdict === "like" ? 1 : verdict === "dislike" ? -1 : 0;
    card.classList.add("leaving");
    card.style.transform = `translate(${x * 150}%, ${x ? 0 : -150}%) rotate(${x * 30}deg)`;
    card.style.opacity = 0;
  }
  queue = queue.filter((l) => l.post_id !== listing.post_id);
  history.push(listing);
  setTimeout(renderDeck, 250);
  try {
    await api("PUT", `/api/listings/${listing.post_id}/verdict`, { verdict });
  } catch (err) {
    alert(`Pas enregistré : ${err.message}`);
    queue.unshift(listing);
    history.pop();
    renderDeck();
    return;
  }
  if (queue.length < 5) {
    const more = await api("GET", "/api/deck?limit=30");
    const known = new Set(queue.map((l) => l.post_id));
    queue.push(...more.filter((l) => !known.has(l.post_id)));
    if (!$("#deck .card")) renderDeck();
  }
}

async function undo() {
  const listing = history.pop();
  if (!listing) return;
  await api("PUT", `/api/listings/${listing.post_id}/verdict`, { verdict: null });
  queue.unshift(listing);
  renderDeck();
}

$("#btn-like").addEventListener("click", () => decide(queue[0], "like"));
$("#btn-dislike").addEventListener("click", () => decide(queue[0], "dislike"));
$("#btn-superlike").addEventListener("click", () => decide(queue[0], "superlike"));
$("#btn-undo").addEventListener("click", undo);
$("#btn-info").addEventListener("click", () => queue[0] && showDetail(queue[0]));
document.addEventListener("keydown", (e) => {
  if ($("#view-deck").hidden || $("#detail").open || e.target.closest("input, select")) return;
  const keys = { ArrowRight: "like", ArrowLeft: "dislike", ArrowUp: "superlike" };
  if (keys[e.key]) decide(queue[0], keys[e.key]);
  else if (e.key === "Backspace" || (e.key === "z" && (e.metaKey || e.ctrlKey))) undo();
});

// --- detail ----------------------------------------------------------------

const VERDICT_LABEL = { like: "♥ Liké", superlike: "★ Coup de cœur", dislike: "✕ Rejeté" };

function showDetail(l) {
  const d = l.detail || {};
  const facts = [
    ["Loyer", `${money(l.price)} / mois`],
    ["Caution", d.deposit],
    ["Type", d.kind || l.kind],
    ["Surface", d.area || l.area],
    ["Étage", d.floor || l.floor],
    ["Immeuble", d.shape],
    ["Disposition", d.layout || l.layout],
    ["Adresse", d.address || l.address],
    ["Transports", d.traffic && JSON.stringify(d.traffic)],
    ["Bail", d.lease],
    ["Dispo le", d.move_in],
    ["Animaux", d.pet],
    ["Cuisine", d.cook],
    ["Équipements", d.facilities],
    ["Contact", [d.agent, d.agent_role, d.phone].filter(Boolean).join(" · ")],
    ["Avis", VERDICT_LABEL[l.verdict]],
  ].filter(([, v]) => v);
  const map = l.lat && l.lng ? `https://www.google.com/maps/search/?api=1&query=${l.lat},${l.lng}` : null;
  $("#detail-body").innerHTML = `
    <div class="gallery">${(l.photos || []).map((p) => `<img src="${esc(p)}" alt="" referrerpolicy="no-referrer" loading="lazy">`).join("")}</div>
    <h2>${esc(l.title)}</h2>
    ${l.delisted ? '<p class="error">Annonce retirée de 591.</p>' : ""}
    <div class="links">
      <a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">Voir sur 591</a>
      ${map ? `<a href="${esc(map)}" target="_blank" rel="noopener noreferrer">Carte</a>` : ""}
      ${d.phone ? `<a href="tel:${esc(d.phone)}">Appeler</a>` : ""}
    </div>
    <dl class="facts">${facts.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
    <p class="remark">${esc(d.remark)}</p>`;
  $("#detail").showModal();
}

// --- liked / disliked ------------------------------------------------------

async function loadList(kind) {
  const list = $(`#${kind}-list`);
  const items = await api("GET", `/api/listings?verdict=${kind}`);
  if (!items.length) {
    list.innerHTML = `<li class="empty" style="display:block">Rien pour l'instant.</li>`;
    return;
  }
  list.replaceChildren(
    ...items.map((l) => {
      const li = document.createElement("li");
      if (l.delisted) li.className = "delisted";
      li.innerHTML = `
        <img src="${esc(l.photos?.[0] || "")}" alt="" referrerpolicy="no-referrer" loading="lazy">
        <div class="grow">
          <div><strong>${l.verdict === "superlike" ? "★ " : ""}${esc(money(l.price))}</strong> · ${esc(l.layout || "")} · ${esc(l.area || "")}</div>
          <div class="muted">${esc(l.title)}</div>
          <div class="muted">${esc(l.address || "")}</div>
        </div>
        <button title="${kind === "liked" ? "Rejeter" : "Remettre dans le deck"}">${kind === "liked" ? "✕" : "↶"}</button>`;
      li.querySelector(".grow").addEventListener("click", () => showDetail(l));
      li.querySelector("button").addEventListener("click", async () => {
        await api("PUT", `/api/listings/${l.post_id}/verdict`, { verdict: kind === "liked" ? "dislike" : null });
        loadList(kind);
      });
      return li;
    }),
  );
}

// --- searches --------------------------------------------------------------

let options = null;
const form = $("#search-form");

function fillSelect(select, values, empty) {
  select.replaceChildren(
    ...(empty ? [new Option(empty, "")] : []),
    ...values.map((v) => new Option(v, v)),
  );
}

function fillSections() {
  const region = options.regions.find((r) => r.name === form.region.value);
  fillSelect(form.section, region ? region.sections : [], "Toute la ville");
}

async function loadSearches() {
  if (!options) {
    options = await api("GET", "/api/options");
    fillSelect(form.region, options.regions.map((r) => r.name));
    fillSelect(form.kind, options.kinds, "Tous");
    fillSelect(form.shape, options.shapes, "Tous");
    fillSelect(form.pattern, options.patterns, "Toutes");
    form.region.addEventListener("change", fillSections);
    fillSections();
  }
  const searches = await api("GET", "/api/searches");
  $("#search-list").replaceChildren(
    ...searches.map((s) => {
      const li = document.createElement("li");
      li.style.gridTemplateColumns = "1fr auto";
      const price = s.price_min || s.price_max ? `${s.price_min || 0}–${s.price_max || "∞"} NT$` : "";
      li.innerHTML = `
        <div class="grow">
          <div><strong>${esc(s.name)}</strong>${s.active ? "" : ' <span class="muted">(en pause)</span>'}</div>
          <div class="muted">${esc([s.region, s.section, s.kind, s.shape, s.pattern, price, s.keywords].filter(Boolean).join(" · "))}</div>
        </div>
        <button title="Supprimer">🗑</button>`;
      li.querySelector(".grow").addEventListener("click", () => editSearch(s));
      li.querySelector("button").addEventListener("click", async () => {
        if (!confirm(`Supprimer « ${s.name} » ?`)) return;
        await api("DELETE", `/api/searches/${s.id}`);
        loadSearches();
      });
      return li;
    }),
  );
}

function editSearch(s) {
  $("#search-form-title").textContent = `Modifier « ${s.name} »`;
  form.id.value = s.id;
  form.name.value = s.name;
  form.region.value = s.region;
  fillSections();
  for (const key of ["section", "kind", "shape", "pattern", "price_min", "price_max", "keywords"]) form[key].value = s[key] ?? "";
  form.active.checked = s.active;
  form.scrollIntoView({ behavior: "smooth" });
}

form.addEventListener("reset", () => {
  $("#search-form-title").textContent = "Nouvelle recherche";
  setTimeout(fillSections, 0);
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#search-error").textContent = "";
  const orNull = (v) => (v === "" ? null : v);
  const body = {
    name: form.name.value.trim(),
    active: form.active.checked,
    region: form.region.value,
    section: orNull(form.section.value),
    kind: orNull(form.kind.value),
    shape: orNull(form.shape.value),
    pattern: orNull(form.pattern.value),
    price_min: form.price_min.value ? Number(form.price_min.value) : null,
    price_max: form.price_max.value ? Number(form.price_max.value) : null,
    keywords: orNull(form.keywords.value.trim()),
  };
  try {
    if (form.id.value) await api("PUT", `/api/searches/${form.id.value}`, body);
    else await api("POST", "/api/searches", body);
    form.reset();
    loadSearches();
  } catch (err) {
    $("#search-error").textContent = err.message;
  }
});

// --- start -----------------------------------------------------------------

async function start() {
  try {
    await api("GET", "/api/me");
  } catch {
    return;
  }
  $("#login").hidden = true;
  $("#app").hidden = false;
  showView("deck");
}

start();
