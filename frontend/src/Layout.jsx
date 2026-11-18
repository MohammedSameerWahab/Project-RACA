import { useEffect, useState } from "react";
import "./Layout.css";

const THEME_KEY = "raca.theme";
const USER_KEY = "raca.sessionUser";

export function getStoredTheme() {
  return window.localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
}

export function applyTheme(theme) {
  const next = theme === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  document.documentElement.style.colorScheme = next;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.setAttribute("content", next === "light" ? "#f6f8fa" : "#0d1117");
  }
  window.localStorage.setItem(THEME_KEY, next);
  window.dispatchEvent(new CustomEvent("raca-theme", { detail: next }));
  return next;
}

const NAV_LINKS = [
  { id: "home", label: "Home" },
  { id: "about", label: "About" },
  { id: "team", label: "Team" },
  { id: "contact", label: "Contact" },
];

export default function Layout({
  page,
  onNavigate,
  repository,
  children,
  compact = false,
}) {
  const [theme, setTheme] = useState(() => getStoredTheme());
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(window.localStorage.getItem(USER_KEY) || "null");
    } catch {
      return null;
    }
  });
  const [loginOpen, setLoginOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    setMenuOpen(false);
  }, [page]);

  function toggleTheme() {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  }

  function handleLogin(event) {
    event.preventDefault();
    if (!email.trim() || password.trim().length < 4) {
      setLoginError("Enter an email and a password with at least 4 characters.");
      return;
    }
    const nextUser = {
      name: email.split("@")[0],
      email: email.trim(),
    };
    window.localStorage.setItem(USER_KEY, JSON.stringify(nextUser));
    setUser(nextUser);
    setPassword("");
    setLoginError("");
    setLoginOpen(false);
  }

  function logout() {
    window.localStorage.removeItem(USER_KEY);
    setUser(null);
  }

  return (
    <div className={`site-shell ${compact ? "compact" : ""} ${page}`}>
      <header className="site-navbar">
        <div className="navbar-inner">
          <button className="navbar-brand" type="button" onClick={() => onNavigate("home")}>
            <span className="brand-mark">R</span>
            <span>
              <strong>RACA</strong>
              <em>Repository intelligence</em>
            </span>
          </button>

          <nav className={`navbar-links ${menuOpen ? "open" : ""}`} aria-label="Primary">
            {NAV_LINKS.map((link) => (
              <button
                key={link.id}
                type="button"
                className={page === link.id ? "active" : ""}
                onClick={() => onNavigate(link.id)}
              >
                {link.label}
              </button>
            ))}
          </nav>

          <div className="navbar-actions">
            {repository && <span className="navbar-repo" title={repository}>{repository}</span>}
            <button
              type="button"
              className="theme-switch"
              onClick={toggleTheme}
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              title={theme === "dark" ? "Light mode" : "Dark mode"}
            >
              <span className={`theme-knob ${theme}`} />
              <span className="theme-icon sun" aria-hidden="true">☀</span>
              <span className="theme-icon moon" aria-hidden="true">☾</span>
            </button>
            {user ? (
              <div className="navbar-user">
                <span className="user-avatar">{user.name.slice(0, 1).toUpperCase()}</span>
                <span className="user-name">{user.name}</span>
                <button type="button" className="ghost-button" onClick={logout}>Log out</button>
              </div>
            ) : (
              <button type="button" className="login-button" onClick={() => { setLoginOpen(true); setLoginError(""); }}>
                Log in
              </button>
            )}
            <button
              type="button"
              className="menu-toggle"
              aria-label="Open menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((open) => !open)}
            >
              <span />
              <span />
              <span />
            </button>
          </div>
        </div>
      </header>

      <main className="site-main">{children}</main>

      <footer className="site-footer">
        <div className="footer-grid">
          <div>
            <div className="navbar-brand footer-brand">
              <span className="brand-mark">R</span>
              <strong>RACA</strong>
            </div>
            <p>Repository Aware Coding Assistant. Grounded navigation, investigation, and understanding for your codebase.</p>
          </div>
          <div>
            <h3>Product</h3>
            <button type="button" onClick={() => onNavigate("home")}>Home</button>
            <button type="button" onClick={() => onNavigate("about")}>About</button>
          </div>
          <div>
            <h3>Team</h3>
            <button type="button" onClick={() => onNavigate("team")}>Team</button>
            <button type="button" onClick={() => onNavigate("contact")}>Contact</button>
            <a href="https://github.com" target="_blank" rel="noreferrer">GitHub</a>
          </div>
          <div>
            <h3>Capabilities</h3>
            <span>Semantic retrieval</span>
            <span>Keyword search</span>
            <span>Code graph</span>
          </div>
        </div>
        <div className="footer-bottom">
          <span>© {new Date().getFullYear()} RACA · Repository Aware Coding Assistant</span>
          <span>Semantic · Keyword · Graph</span>
        </div>
      </footer>

      {loginOpen && (
        <div
          className="modal-backdrop login-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setLoginOpen(false);
          }}
        >
          <section className="replace-dialog login-dialog" role="dialog" aria-modal="true" aria-labelledby="login-title">
            <button className="dialog-close" aria-label="Close login" onClick={() => setLoginOpen(false)}>×</button>
            <span className="eyebrow">ACCOUNT</span>
            <h2 id="login-title">Log in to RACA</h2>
            <p>This is a local workspace login. Your session stays in this browser and does not change the backend.</p>
            <form className="repository-form" onSubmit={handleLogin}>
              <input
                type="email"
                required
                placeholder="you@example.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="username"
              />
              <input
                type="password"
                required
                minLength={4}
                placeholder="Password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
              />
              <button type="submit">Continue</button>
            </form>
            {loginError && <div className="error-message">{loginError}</div>}
          </section>
        </div>
      )}
    </div>
  );
}
