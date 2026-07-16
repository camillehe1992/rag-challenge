const loginView = document.querySelector("#login-view");
const chatView = document.querySelector("#chat-view");
const loginForm = document.querySelector("#login-form");
const chatForm = document.querySelector("#chat-form");
const loginError = document.querySelector("#login-error");
const messages = document.querySelector("#messages");
const messageInput = document.querySelector("#message-input");
const logoutButton = document.querySelector("#logout-button");

const history = [];

const ROUTES = {
  login: "#login",
  chat: "#chat",
};

const AUTH_STORAGE_KEY = "rag_chat_authenticated";

function isAuthenticated() {
  return window.sessionStorage.getItem(AUTH_STORAGE_KEY) === "true";
}

function showChat({ updateRoute = true } = {}) {
  loginView.hidden = true;
  chatView.hidden = false;
  if (updateRoute && window.location.hash !== ROUTES.chat) {
    window.location.hash = ROUTES.chat;
  }
  messageInput.focus();
}

function showLogin({ updateRoute = true } = {}) {
  chatView.hidden = true;
  loginView.hidden = false;
  if (updateRoute && window.location.hash !== ROUTES.login) {
    window.location.hash = ROUTES.login;
  }
}

function routeToInitialView() {
  if (window.location.hash === ROUTES.chat && isAuthenticated()) {
    showChat({ updateRoute: false });
    return;
  }
  showLogin({ updateRoute: false });
}

function appendMessage(role, text, sources = []) {
  const item = document.createElement("article");
  item.className = `message ${role}`;
  item.textContent = text;

  if (sources.length > 0) {
    const sourceBox = document.createElement("div");
    sourceBox.className = "sources";

    for (const source of sources) {
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = source.title || source.url;
      sourceBox.appendChild(link);
    }

    item.appendChild(sourceBox);
  }

  messages.appendChild(item);
  messages.scrollTop = messages.scrollHeight;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }

  return response.json();
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.hidden = true;

  const username = document.querySelector("#username").value;
  const password = document.querySelector("#password").value;

  try {
    await postJson("/api/login", { username, password });
    window.sessionStorage.setItem(AUTH_STORAGE_KEY, "true");
    showChat();
  } catch (error) {
    loginError.textContent = error.message;
    loginError.hidden = false;
  }
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message) return;

  appendMessage("user", message);
  history.push({ role: "user", content: message });
  messageInput.value = "";

  const loadingText = "正在检索资料...";
  appendMessage("assistant", loadingText);
  const loadingNode = messages.lastElementChild;

  try {
    const data = await postJson("/api/chat", { message, history });
    loadingNode.remove();
    appendMessage("assistant", data.answer, data.sources || []);
    history.push({ role: "assistant", content: data.answer });
  } catch (error) {
    loadingNode.textContent = error.message;
  }
});

logoutButton.addEventListener("click", async () => {
  await fetch("/api/logout", {
    method: "POST",
    credentials: "include",
  });
  window.sessionStorage.removeItem(AUTH_STORAGE_KEY);
  history.length = 0;
  messages.replaceChildren();
  showLogin();
});

window.addEventListener("hashchange", () => {
  if (window.location.hash === ROUTES.chat && isAuthenticated()) {
    showChat({ updateRoute: false });
    return;
  }
  showLogin({ updateRoute: false });
});

routeToInitialView();
