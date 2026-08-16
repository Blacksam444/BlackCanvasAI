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
document.querySelector("#graffitixOptions").insertAdjacentHTML("beforeend", `<label>Wardrobe construction<select id="builderWardrobe"><option value="oversized deeply pleated black chinos stacked at the ankles, a loose white pocket tee, an open flannel, and retro high-top sneakers">Pleated chinos + flannel</option><option value="oversized tan chinos with deep pleats, a fitted cropped tank, a vintage windbreaker, and retro statement sneakers">Tan chinos + windbreaker</option><option value="baggy charcoal denim, a loose graphic-free tee, a tied bandana, and scuffed high-top sneakers">Baggy denim + bandana</option><option value="wide black work pants, a sleeveless pocket tee, a backward snapback, and heavy retro trainers">Work pants + snapback</option></select></label><label>Lighting direction<select id="builderLighting"><option value="stark graphic directional lighting with brutal contrast and hard-edged shadows">Stark graphic contrast</option><option value="a hot-magenta side light cut by a cold cyan rim light, with deep matte shadows">Magenta + cyan split</option><option value="a single overhead streetlight creating a tight pool of light and long broken shadows">Overhead streetlight</option><option value="flat frontal flash with a dark falloff, raw highlights, and confrontational poster-like tension">Raw frontal flash</option></select></label>`);
document.querySelector("#graffitixOptions").insertAdjacentHTML("beforeend", `<label>Supporting symbols<select id="builderSupporting"><option value="one crude diamond and one primitive pyramid, both small and visually subordinate">Diamond + pyramid</option><option value="two tiny xxx marks used as quiet directional accents">Tiny xxx marks</option><option value="one small nova glyph and one scratched diamond, kept away from the face">Nova + diamond</option><option value="one primitive pyramid only, isolated as a secondary accent">Single pyramid</option></select></label><label>Background marks<select id="builderBackground"><option value="restrained ledger numbers, anatomical labels, and a few crossed-out notes fading into controlled negative space">Ledger + anatomy notes</option><option value="sparse cryptic phrases, chalk geometry, and directional charcoal scribbles following the line of action">Cryptic chalk marks</option><option value="torn paper fragments, faded inventory stamps, and loose oil-stick calculations at the outer edges">Collage + inventory marks</option><option value="minimal scratched paint and two faint handwritten number clusters, leaving most of the canvas exposed">Minimal scratched marks</option></select></label>`);
document.querySelector("#graffitixOptions").insertAdjacentHTML("beforeend", `<label>Physical media<select id="builderMedia"><option value="heavy oil stick, thick oil pastel, viscous dripping acrylic, palette-knife impasto, aerosol haze, charcoal drag marks, scratches, torn collage, and exposed unprimed canvas">Full mixed-media stack</option><option value="dominant oil stick and thick oil pastel with dry charcoal drag marks, scratched pigment, and broad areas of exposed raw canvas">Oil stick + charcoal</option><option value="viscous dripping acrylic and palette-knife impasto over torn pasted-paper collage, with restrained aerosol overspray">Acrylic + collage</option><option value="aerosol haze, chalk geometry, scraped matte paint, and sparse oil-stick accents over heavily exposed unprimed canvas">Aerosol + raw canvas</option></select></label>`);
document.querySelector("#graffitixOptions").insertAdjacentHTML("beforeend", `<button class="shuffle-direction" id="shuffleBuilder" type="button">↻ Shuffle GraffitiX direction</button>`);
document.querySelector("#shuffleBuilder").onclick = () => {
  document.querySelectorAll("#graffitixOptions select").forEach((select) => {
    if (select.options.length > 1) select.selectedIndex = (select.selectedIndex + 1 + Math.floor(Math.random() * (select.options.length - 1))) % select.options.length;
  });
  notify("New GraffitiX direction ready.");
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
    ? ` Pose: ${document.querySelector("#builderPose").value}; Camera: ${document.querySelector("#builderCamera").value}; Wardrobe: ${document.querySelector("#builderWardrobe").value}; Hero symbol: ${document.querySelector("#builderHero").value}; Supporting symbols: ${document.querySelector("#builderSupporting").value}; Physical media: ${document.querySelector("#builderMedia").value}; Background marks: ${document.querySelector("#builderBackground").value}; Lighting: ${document.querySelector("#builderLighting").value}.`
    : "";
  send(`Create an image prompt for ${subject} in the ${collection} style, with a ${mood} mood, using ${colorDirection}, as a ${imageStyle}. Aspect ratio: ${aspectRatio}.${graffitiDirection}`);
};
JSON.parse(localStorage.getItem(KEY) || "[]").forEach((message) => addMessage(message.role, message.text, false));
const openingQuestion = new URLSearchParams(window.location.search).get("q");
if (openingQuestion) { history.replaceState({}, "", "/chat"); send(openingQuestion); }
