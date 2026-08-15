const messages = document.querySelector("#messages");
const input = document.querySelector("#messageInput");
const welcome = document.querySelector("#welcome");
const toast = document.querySelector("#toast");
const KEY = "blackcanvas-chat";

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

function addMessage(role, text, save = true) {
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
  if (save) {
    const history = JSON.parse(localStorage.getItem(KEY) || "[]");
    history.push({ role, text });
    localStorage.setItem(KEY, JSON.stringify(history));
  }
  return element;
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

async function send(text) {
  const message = text.trim();
  if (!message) return;
  addMessage("user", message);
  document.querySelector("#chatTitle").textContent = message.slice(0, 32);
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
    const answer = addMessage("assistant", data.reply);
    if (data.generated_prompt) addPromptSaveButton(answer, data);
  } catch {
    typing.remove();
    addMessage("assistant", "I couldn’t answer just now. Please try again.");
  }
}

document.querySelector("#chatForm").onsubmit = (event) => { event.preventDefault(); send(input.value); };
input.onkeydown = (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(input.value); } };
input.oninput = () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight}px`; };
document.querySelectorAll(".suggestions button").forEach((button) => { button.onclick = () => send(button.textContent); });
document.querySelectorAll("#newChat,#topNewChat").forEach((button) => {
  button.onclick = () => {
    localStorage.removeItem(KEY);
    messages.querySelectorAll(".message").forEach((message) => message.remove());
    welcome.hidden = false;
    document.querySelector("#chatTitle").textContent = "New conversation";
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
const updateGraffitiXOptions = () => {
  document.querySelector("#graffitixOptions").hidden = document.querySelector("#builderCollection").value !== "GraffitiX";
};
document.querySelector("#builderCollection").onchange = updateGraffitiXOptions;
updateGraffitiXOptions();
document.querySelector("#promptBuilder").onsubmit = (event) => {
  event.preventDefault();
  const subject = document.querySelector("#builderSubject").value.trim();
  const collection = document.querySelector("#builderCollection").value;
  const mood = document.querySelector("#builderMood").value;
  const colors = document.querySelector("#builderColors").value;
  const imageStyle = document.querySelector("#builderStyle").value;
  const aspectRatio = document.querySelector("#builderAspectRatio").value;
  if (!subject) return document.querySelector("#builderSubject").focus();
  const colorDirection = colors === "Collection colors" ? "the collection color palette" : colors;
  const graffitiDirection = collection === "GraffitiX"
    ? ` Pose: ${document.querySelector("#builderPose").value}; Camera: ${document.querySelector("#builderCamera").value}; Hero symbol: ${document.querySelector("#builderHero").value}.`
    : "";
  send(`Create an image prompt for ${subject} in the ${collection} style, with a ${mood} mood, using ${colorDirection}, as a ${imageStyle}. Aspect ratio: ${aspectRatio}.${graffitiDirection}`);
};
JSON.parse(localStorage.getItem(KEY) || "[]").forEach((message) => addMessage(message.role, message.text, false));
const openingQuestion = new URLSearchParams(window.location.search).get("q");
if (openingQuestion) { history.replaceState({}, "", "/chat"); send(openingQuestion); }
