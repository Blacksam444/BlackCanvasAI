const messages = document.querySelector("#messages");
const input = document.querySelector("#messageInput");
const welcome = document.querySelector("#welcome");
const toast = document.querySelector("#toast");
const KEY = "blackcanvas-chat";
const conversationList = document.querySelector("#conversationList");
const artworkPicker = document.querySelector("#artworkPicker");
const artworkPickerGrid = document.querySelector("#artworkPickerGrid");
let pickerArtworks = [];
let currentConversationId = null;

const escapeHtml = (text) => text.replace(/[&<>]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[character]));
const markdown = (text) => {
  let list = false;
  let html = "";
  escapeHtml(text).split("\n").forEach((line) => {
    if (line.startsWith("- ")) {
      if (!list) { html += "<ul>"; list = true; }
      html += `<li>${line.slice(2).replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")}</li>`;
    } else {
      if (list) { html += "</ul>"; list = false; }
      if (line.trim()) html += `<p>${line.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")}</p>`;
    }
  });
  return html + (list ? "</ul>" : "");
};

const notify = (message) => {
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 1800);
};

function addMessage(role, text, save = true, metadata = {}) {
  welcome.hidden = true;
  const element = document.createElement("article");
  element.className = `message ${role}`;
  element.innerHTML = `<div class="message-avatar">${role === "user" ? "J" : "✦"}</div><div><div class="message-name">${role === "user" ? "You" : "Black Canvas AI"}</div><div class="message-body">${markdown(text)}</div><button class="copy-message">Copy</button></div>`;
  element.querySelector(".copy-message").onclick = async () => {
    await navigator.clipboard.writeText(text);
    notify("Message copied.");
  };
  messages.appendChild(element);
  messages.scrollTop = messages.scrollHeight;
  if (save && currentConversationId) saveChatMessage(role, text, metadata);
  return element;
}

async function ensureConversation(title) {
  if (currentConversationId) return currentConversationId;
  const response = await fetch("/api/conversations", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title.slice(0, 60) }),
  });
  if (!response.ok) throw new Error();
  const conversation = await response.json();
  currentConversationId = conversation.id;
  await renderConversations();
  return currentConversationId;
}

async function saveChatMessage(role, text, metadata = {}) {
  if (!currentConversationId) return;
  await fetch(`/api/conversations/${currentConversationId}/messages`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role, text, metadata }),
  });
  renderConversations();
}

async function renderConversations() {
  const response = await fetch("/api/conversations");
  if (!response.ok) throw new Error();
  const conversations = await response.json();
  if (!conversations.length) {
    conversationList.innerHTML = '<p class="history-empty">Your saved chats will appear here.</p>';
    return conversations;
  }
  conversationList.innerHTML = conversations.map((conversation) => `<div class="history-row ${conversation.id === currentConversationId ? "active" : ""}" data-id="${conversation.id}"><button class="history-item"><span>${conversation.message_count} message${conversation.message_count === 1 ? "" : "s"}</span><strong>${escapeHtml(conversation.title)}</strong></button><button class="history-manage" title="Rename or delete">•••</button></div>`).join("");
  conversationList.querySelectorAll(".history-item").forEach((button) => {
    button.onclick = () => openConversation(Number(button.dataset.id), button.querySelector("strong").textContent);
  });
  conversationList.querySelectorAll(".history-row").forEach((row) => {
    row.querySelector(".history-item").dataset.id = row.dataset.id;
    row.querySelector(".history-manage").onclick = () => manageConversation(row);
  });
  return conversations;
}

async function manageConversation(row) {
  const id = Number(row.dataset.id);
  const currentTitle = row.querySelector("strong").textContent;
  const choice = window.prompt(`Rename this conversation, or type DELETE to remove it:`, currentTitle);
  if (choice === null || choice.trim() === currentTitle) return;
  if (choice.trim().toUpperCase() === "DELETE") {
    if (!window.confirm(`Remove “${currentTitle}” from your chat history?`)) return;
    const response = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
    if (!response.ok) return notify("Could not remove the conversation.");
    if (currentConversationId === id) {
      currentConversationId = null;
      messages.querySelectorAll(".message").forEach((message) => message.remove());
      welcome.hidden = false;
    }
    await renderConversations();
    notify("Conversation removed.");
    return;
  }
  const title = choice.trim();
  if (!title) return notify("The conversation needs a name.");
  const response = await fetch(`/api/conversations/${id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }),
  });
  if (!response.ok) return notify("Could not rename the conversation.");
  await renderConversations();
  notify("Conversation renamed.");
}

async function openConversation(id, title) {
  const response = await fetch(`/api/conversations/${id}/messages`);
  if (!response.ok) return notify("Could not open that conversation.");
  const savedMessages = await response.json();
  currentConversationId = id;
  messages.querySelectorAll(".message").forEach((message) => message.remove());
  welcome.hidden = savedMessages.length > 0;
  savedMessages.forEach((saved) => {
    const message = addMessage(saved.role, saved.text, false, saved.metadata || {});
    if (saved.role === "assistant" && saved.metadata?.generated_prompt) {
      addPromptSaveButton(message, saved.metadata);
      addPromptRefiner(message, saved.metadata);
    }
  });
  await renderConversations();
}

function addPromptSaveButton(message, data) {
  const button = document.createElement("button");
  button.className = "save-prompt";
  button.textContent = "＋ Save to Prompt Library";
  button.onclick = async () => {
    button.disabled = true;
    button.textContent = "Saving...";
    try {
      const response = await fetch("/api/prompts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: data.prompt_title,
          category: data.prompt_category,
          text: data.generated_prompt,
          favorite: false,
        }),
      });
      if (!response.ok) {
        if (response.status === 409) {
          button.textContent = "✓ Already saved";
          notify("That prompt is already in your library.");
          return;
        }
        throw new Error();
      }
      button.textContent = "✓ Saved to Prompt Library";
      notify("Prompt saved to your library.");
    } catch {
      button.disabled = false;
      button.textContent = "＋ Save to Prompt Library";
      notify("Could not save the prompt just now.");
    }
  };
  message.querySelector(".copy-message").parentElement.appendChild(button);
}

function addPromptRefiner(message, data) {
  const wrap = document.createElement("div");
  wrap.className = "prompt-refiner";
  wrap.innerHTML = '<span>Refine this prompt</span><div><button data-mode="cinematic">More cinematic</button><button data-mode="detailed">More detailed</button><button data-mode="simple">Simplify</button><button data-mode="style">Stronger style</button></div>';
  wrap.querySelectorAll("button").forEach((button) => {
    button.onclick = async () => {
      wrap.querySelectorAll("button").forEach((item) => { item.disabled = true; });
      const original = button.textContent;
      button.textContent = "Refining...";
      try {
        const response = await fetch("/api/prompts/refine", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt: data.generated_prompt, category: data.prompt_category, mode: button.dataset.mode }),
        });
        if (!response.ok) throw new Error();
        const refined = await response.json();
        const answer = addMessage("assistant", refined.reply, true, refined);
        addPromptSaveButton(answer, refined);
        addPromptRefiner(answer, refined);
      } catch {
        notify("Could not refine the prompt just now.");
      } finally {
        button.textContent = original;
        wrap.querySelectorAll("button").forEach((item) => { item.disabled = false; });
      }
    };
  });
  message.querySelector(".copy-message").parentElement.appendChild(wrap);
}

async function send(text) {
  const message = text.trim();
  if (!message) return;
  try { await ensureConversation(message); } catch { return notify("Could not start the conversation."); }
  addMessage("user", message);
  input.value = "";
  input.style.height = "auto";
  const typing = document.createElement("article");
  typing.className = "message assistant";
  typing.innerHTML = '<div class="message-avatar">✦</div><div><div class="message-name">Black Canvas AI</div><div class="typing"><i></i><i></i><i></i></div></div>';
  messages.appendChild(typing);
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    if (!response.ok) throw new Error();
    const data = await response.json();
    typing.remove();
    const answer = addMessage("assistant", data.reply, true, data);
    if (data.generated_prompt) {
      addPromptSaveButton(answer, data);
      addPromptRefiner(answer, data);
    }
  } catch {
    typing.remove();
    addMessage("assistant", "I couldn’t answer just now. Please try again.");
  }
}

document.querySelector("#chatForm").onsubmit = (event) => { event.preventDefault(); send(input.value); };
async function openArtworkPicker() {
  artworkPickerGrid.innerHTML = '<p class="artwork-picker-loading">Loading your artwork...</p>';
  artworkPicker.showModal();
  try {
    const response = await fetch("/api/artworks");
    if (!response.ok) throw new Error();
    pickerArtworks = await response.json();
    renderArtworkPicker("");
    document.querySelector("#artworkPickerSearch").focus();
  } catch {
    artworkPickerGrid.innerHTML = '<p class="artwork-picker-loading">Could not load the artwork catalog.</p>';
  }
}

function renderArtworkPicker(search) {
  const query = search.toLowerCase().trim();
  const shown = pickerArtworks.filter((artwork) => `${artwork.title} ${artwork.collection} ${artwork.tags} ${artwork.notes}`.toLowerCase().includes(query));
  artworkPickerGrid.innerHTML = shown.map((artwork) => `<button class="artwork-pick" data-id="${artwork.id}"><img src="${artwork.url}" alt=""><span><strong>${escapeHtml(artwork.title)}</strong><small>${escapeHtml(artwork.collection)}</small></span></button>`).join("");
  document.querySelector("#artworkPickerEmpty").hidden = shown.length > 0;
  artworkPickerGrid.querySelectorAll(".artwork-pick").forEach((button) => {
    button.onclick = () => chooseArtwork(Number(button.dataset.id));
  });
}

function chooseArtwork(id) {
  const artwork = pickerArtworks.find((item) => item.id === id);
  if (!artwork) return;
  const details = [artwork.notes, artwork.tags ? `Visual details: ${artwork.tags}` : ""].filter(Boolean).join(". ");
  input.value = `Create an image prompt for ${artwork.title} in the ${artwork.collection} style${details ? `. Use this creative direction: ${details}` : ""}.`;
  input.dispatchEvent(new Event("input"));
  artworkPicker.close();
  input.focus();
  notify("Artwork details added. Press Send when ready.");
}

document.querySelector(".attach").onclick = openArtworkPicker;
document.querySelector("#closeArtworkPicker").onclick = () => artworkPicker.close();
document.querySelector("#artworkPickerSearch").oninput = (event) => renderArtworkPicker(event.target.value);
input.onkeydown = (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(input.value); } };
input.oninput = () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight}px`; };
document.querySelectorAll(".suggestions button").forEach((button) => { button.onclick = () => send(button.textContent); });
document.querySelectorAll("#newChat,#topNewChat").forEach((button) => {
  button.onclick = () => {
    currentConversationId = null;
    messages.querySelectorAll(".message").forEach((message) => message.remove());
    welcome.hidden = false;
    renderConversations();
    input.focus();
  };
});
document.querySelectorAll("[data-coming]").forEach((button) => { button.onclick = () => notify(`${button.dataset.coming} is next on our build list.`); });
document.querySelector("#menuButton").onclick = () => document.querySelector("#sidebar").classList.toggle("open");
document.querySelector("#builderToggle").onclick = () => {
  const builder = document.querySelector("#promptBuilder");
  builder.hidden = !builder.hidden;
  document.querySelector("#builderToggle").textContent = builder.hidden ? "✦ Open Prompt Builder" : "× Close Prompt Builder";
  if (!builder.hidden) document.querySelector("#builderSubject").focus();
};
document.querySelector("#promptBuilder").onsubmit = (event) => {
  event.preventDefault();
  const subject = document.querySelector("#builderSubject").value.trim();
  const collection = document.querySelector("#builderCollection").value;
  const mood = document.querySelector("#builderMood").value;
  const colors = document.querySelector("#builderColors").value;
  const imageStyle = document.querySelector("#builderStyle").value;
  if (!subject) return document.querySelector("#builderSubject").focus();
  const colorDirection = colors === "Collection colors" ? "the collection color palette" : colors;
  send(`Create an image prompt for ${subject} in the ${collection} style, with a ${mood} mood, using ${colorDirection}, as a ${imageStyle}.`);
};
const openingQuestion = new URLSearchParams(window.location.search).get("q");
async function initializeChat() {
  try {
    const conversations = await renderConversations();
    const legacy = JSON.parse(localStorage.getItem(KEY) || "[]");
    if (!conversations.length && legacy.length) {
      await ensureConversation(legacy.find((item) => item.role === "user")?.text || "Saved conversation");
      for (const item of legacy) await saveChatMessage(item.role, item.text);
      localStorage.removeItem(KEY);
      await openConversation(currentConversationId, legacy.find((item) => item.role === "user")?.text.slice(0, 60) || "Saved conversation");
    } else if (!openingQuestion && conversations.length) {
      await openConversation(conversations[0].id, conversations[0].title);
    }
    if (openingQuestion) { history.replaceState({}, "", "/chat"); send(openingQuestion); }
  } catch { notify("Could not load saved conversations."); }
}
initializeChat();
