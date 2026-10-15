const form = document.querySelector("#note-form");
const input = document.querySelector("#note-text");
const saveButton = document.querySelector("#save-button");
const refreshButton = document.querySelector("#refresh-button");
const statusLine = document.querySelector("#status");
const list = document.querySelector("#notes");
const empty = document.querySelector("#empty");
const counter = document.querySelector("#counter");
const backendLabel = document.querySelector("#backend");

function showStatus(message, isError = false) {
  statusLine.textContent = message;
  statusLine.classList.toggle("error", isError);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    ...options,
  });
  const backend = response.headers.get("X-Backend-ID");
  if (backend) backendLabel.textContent = `API отвечает: ${backend}`;
  const type = response.headers.get("Content-Type") || "";
  if (!type.includes("application/json")) {
    throw new Error(`Ошибка HTTP ${response.status}. Повторите позже.`);
  }
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Ошибка HTTP ${response.status}`);
  }
  return data;
}

async function loadNotes() {
  const notes = await api("/api/notes");
  list.replaceChildren();
  for (const note of notes) {
    const item = document.createElement("li");
    const text = document.createElement("p");
    const meta = document.createElement("small");
    text.textContent = note.text;
    const date = new Date(note.created_at).toLocaleString("ru-RU");
    meta.textContent = `№ ${note.id} · ${date}`;
    item.append(text, meta);
    list.append(item);
  }
  counter.textContent = `Сохранено записей: ${notes.length}`;
  empty.hidden = notes.length !== 0;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) {
    showStatus("Введите текст заметки.", true);
    return;
  }
  saveButton.disabled = true;
  showStatus("Сохраняем…");
  let saved = false;
  try {
    await api("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    saved = true;
    input.value = "";
    await loadNotes();
    showStatus("Заметка сохранена.");
    input.focus();
  } catch (error) {
    const prefix = saved ? "Запись сохранена, но список не обновлён. " : "";
    showStatus(prefix + error.message, true);
  } finally {
    saveButton.disabled = false;
  }
});

refreshButton.addEventListener("click", async () => {
  refreshButton.disabled = true;
  try {
    await loadNotes();
    showStatus("Список обновлён.");
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    refreshButton.disabled = false;
  }
});

loadNotes().catch((error) => {
  counter.textContent = "Список не загружен";
  showStatus(error.message, true);
});
