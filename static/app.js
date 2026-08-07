const toast = document.querySelector("#toast");
const showToast = (message) => {
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2200);
};

const hour = new Date().getHours();
const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
document.querySelector("#greeting").textContent = `${greeting}, Jeffrey.`;

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    showToast(`${button.dataset.view} is next on our build list.`);
    document.querySelector("#sidebar").classList.remove("open");
  });
});

document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", () => showToast(`${button.dataset.action} is ready for the next sprint.`));
});

document.querySelector("#askForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.querySelector("#askInput");
  if (!input.value.trim()) return input.focus();
  showToast("Message saved. Live AI chat is coming next.");
  input.value = "";
});

document.querySelector("#copyPrompt").addEventListener("click", async () => {
  const prompt = document.querySelector("blockquote").textContent.replace(/[“”]/g, "");
  await navigator.clipboard.writeText(prompt);
  showToast("Prompt copied.");
});

document.querySelector("#menuButton").addEventListener("click", () => {
  document.querySelector("#sidebar").classList.toggle("open");
});
