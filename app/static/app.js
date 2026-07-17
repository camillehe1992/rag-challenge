const loginView = document.querySelector("#login-view");
const chatView = document.querySelector("#chat-view");
const loginForm = document.querySelector("#login-form");
const chatForm = document.querySelector("#chat-form");
const loginError = document.querySelector("#login-error");
const chatError = document.querySelector("#chat-error");
const messages = document.querySelector("#messages");
const messageInput = document.querySelector("#message-input");
const logoutButton = document.querySelector("#logout-button");
const currentUser = document.querySelector("#current-user");

const history = [];

const ROUTES = {
  login: "#login",
  chat: "#chat",
};

const AUTH_STORAGE_KEY = "rag_chat_authenticated";
const USER_STORAGE_KEY = "rag_chat_username";
const HISTORY_STORAGE_KEY = "rag_chat_history";

function isAuthenticated() {
  return window.sessionStorage.getItem(AUTH_STORAGE_KEY) === "true";
}

function setAuthenticated({ username }) {
  window.sessionStorage.setItem(AUTH_STORAGE_KEY, "true");
  window.sessionStorage.setItem(USER_STORAGE_KEY, username);
  currentUser.textContent = username;
  currentUser.hidden = false;
}

function clearAuthenticated() {
  window.sessionStorage.removeItem(AUTH_STORAGE_KEY);
  window.sessionStorage.removeItem(USER_STORAGE_KEY);
  currentUser.hidden = true;
  currentUser.textContent = "";
}

function clearChatError() {
  chatError.hidden = true;
  chatError.textContent = "";
}

function showChatError(message) {
  chatError.textContent = message;
  chatError.hidden = false;
}

function showChat({ updateRoute = true } = {}) {
  loginView.hidden = true;
  chatView.hidden = false;
  clearChatError();
  if (updateRoute && window.location.hash !== ROUTES.chat) {
    window.location.hash = ROUTES.chat;
  }
  messageInput.focus();
}

function showLogin({ updateRoute = true } = {}) {
  chatView.hidden = true;
  loginView.hidden = false;
  loginError.hidden = true;
  loginError.textContent = "";
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
    if (response.status === 401) {
      clearAuthenticated();
    }
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }

  return response.json();
}

function persistHistory() {
  window.sessionStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(history));
}

function restoreHistory() {
  const raw = window.sessionStorage.getItem(HISTORY_STORAGE_KEY);
  if (!raw) return;
  try {
    const items = JSON.parse(raw);
    if (!Array.isArray(items)) return;
    for (const item of items) {
      if (!item || typeof item !== "object") continue;
      if (item.role !== "user" && item.role !== "assistant") continue;
      if (typeof item.content !== "string") continue;
      history.push({ role: item.role, content: item.content });
      appendMessage(item.role, item.content);
    }
  } catch (_) {
    return;
  }
}

function applyAuthUI() {
  const username = window.sessionStorage.getItem(USER_STORAGE_KEY);
  if (username && isAuthenticated()) {
    currentUser.textContent = username;
    currentUser.hidden = false;
  } else {
    currentUser.hidden = true;
    currentUser.textContent = "";
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.hidden = true;

  const username = document.querySelector("#username").value;
  const password = document.querySelector("#password").value;

  try {
    await postJson("/api/login", { username, password });
    setAuthenticated({ username });
    showChat();
  } catch (error) {
    loginError.textContent = error.message;
    loginError.hidden = false;
  }
});

messageInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  if (event.shiftKey) return;
  event.preventDefault();
  chatForm.requestSubmit();
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearChatError();
  const message = messageInput.value.trim();
  if (!message) return;

  appendMessage("user", message);
  history.push({ role: "user", content: message });
  persistHistory();
  messageInput.value = "";
  messageInput.disabled = true;

  const loadingText = "正在检索资料...";
  appendMessage("assistant", loadingText);
  const loadingNode = messages.lastElementChild;

  try {
    const data = await postJson("/api/chat", { message, history });
    loadingNode.remove();
    appendMessage("assistant", data.answer, data.sources || []);
    history.push({ role: "assistant", content: data.answer });
    persistHistory();
  } catch (error) {
    loadingNode.remove();
    if (!isAuthenticated()) {
      showLogin();
      loginError.textContent = "登录已失效，请重新登录。";
      loginError.hidden = false;
      return;
    }
    showChatError(error.message);
  }
  messageInput.disabled = false;
  messageInput.focus();
});

logoutButton.addEventListener("click", async () => {
  await fetch("/api/logout", {
    method: "POST",
    credentials: "include",
  });
  clearAuthenticated();
  history.length = 0;
  messages.replaceChildren();
  window.sessionStorage.removeItem(HISTORY_STORAGE_KEY);
  showLogin();
});

window.addEventListener("hashchange", () => {
  if (window.location.hash === ROUTES.chat && isAuthenticated()) {
    showChat({ updateRoute: false });
    return;
  }
  showLogin({ updateRoute: false });
});

applyAuthUI();
if (isAuthenticated()) {
  restoreHistory();
}
routeToInitialView();
