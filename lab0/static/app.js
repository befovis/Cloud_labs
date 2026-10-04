const form = document.querySelector('#note-form');
const input = document.querySelector('#note-text');
const list = document.querySelector('#notes');
const message = document.querySelector('#message');
const button = form.querySelector('button');

async function loadNotes() {
  const response = await fetch('/api/notes', { cache: 'no-store' });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Не удалось загрузить записи');
  list.replaceChildren();
  if (data.length === 0) {
    const item = document.createElement('li');
    item.textContent = 'Пока нет записей';
    list.append(item);
  }
  for (const note of data) {
    const item = document.createElement('li');
    const title = document.createElement('strong');
    const text = document.createElement('p');
    title.textContent = `Запись № ${note.id}`;
    text.textContent = note.text;
    item.append(title, text);
    list.append(item);
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  button.disabled = true;
  message.textContent = '';
  try {
    const response = await fetch('/api/notes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: input.value }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Не удалось сохранить');
    input.value = '';
    await loadNotes();
    message.textContent = `Сохранена запись № ${data.id}`;
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

loadNotes().catch((error) => { message.textContent = error.message; });
