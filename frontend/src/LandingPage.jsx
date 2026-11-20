import { useEffect, useRef, useState } from "react";
import heroArt from "./assets/hero.png";
import ShaderBackground from "./ShaderBackground";
import RacaLogo from "./RacaLogo";
import { SplitText, useInView, useSmoothScrollTracking, mapRange } from "./motionUtils";
import "./LandingPage.css";

const DEFAULT_REPO = "https://github.com/MohammedSameerWahab/Project-RACA";
const GITHUB_REPO_URL = "https://github.com/MohammedSameerWahab/Project-RACA/";
const GITHUB_PREFIX = "git://";
const USER_KEY = "raca.sessionUser";
export const DOWNLOAD_URL = "dummyurl";

export default function LandingPage({
  onNavigate,
  theme,
  onToggleTheme,
  repository,
  onConnectRepository,
  workspaceSection,
}) {
  const [repoInput, setRepoInput] = useState("");
  const [isInputFocused, setIsInputFocused] = useState(false);
  const [typedPlaceholder, setTypedPlaceholder] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (isInputFocused || repoInput.length > 0) {
      setTypedPlaceholder("");
      return;
    }

    let index = 0;
    let isDeleting = false;
    let timeoutId;

    const animateText = () => {
      if (!isDeleting) {
        index += 1;
        setTypedPlaceholder(DEFAULT_REPO.slice(0, index));

        if (index === DEFAULT_REPO.length) {
          isDeleting = true;
          timeoutId = setTimeout(animateText, 1600);
          return;
        }
        timeoutId = setTimeout(animateText, 55);
      } else {
        index -= 1;
        setTypedPlaceholder(DEFAULT_REPO.slice(0, index));

        if (index === 0) {
          isDeleting = false;
          timeoutId = setTimeout(animateText, 450);
          return;
        }
        timeoutId = setTimeout(animateText, 30);
      }
    };

    timeoutId = setTimeout(animateText, 350);

    return () => clearTimeout(timeoutId);
  }, [isInputFocused, repoInput]);

  const [heroCardRef, isHeroCardInView] = useInView({ threshold: 0.1 });
  const [mouseParallax, setMouseParallax] = useState({ x: 0, y: 0 });

  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(window.localStorage.getItem(USER_KEY) || "null");
    } catch {
      return null;
    }
  });
  const [loginOpen, setLoginOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");

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

  function handleLogout() {
    window.localStorage.removeItem(USER_KEY);
    setUser(null);
  }

  const workspaceRef = useRef(null);
  const { scrollProgress } = useSmoothScrollTracking();

  function scrollToWorkspace() {
    if (workspaceRef.current) {
      workspaceRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      onNavigate("workspace");
    }
  }

  function handleIngest(e) {
    e.preventDefault();
    const finalUrl = (repoInput || DEFAULT_REPO).trim();
    if (onConnectRepository) {
      onConnectRepository(finalUrl);
    }
  }

  function handleDownloadClick() {
    if (DOWNLOAD_URL === "dummyurl") {
      const element = document.createElement("a");
      const file = new Blob(
        ["RACA Project Source & Assets\nURL: " + DOWNLOAD_URL],
        { type: "text/plain" }
      );
      element.href = URL.createObjectURL(file);
      element.download = "RACA-setup.txt";
      document.body.appendChild(element);
      element.click();
      document.body.removeChild(element);
    } else {
      window.open(DOWNLOAD_URL, "_blank");
    }
  }

  function handleMouseMove(e) {
    const { clientX, clientY } = e;
    const w = window.innerWidth;
    const h = window.innerHeight;
    const x = mapRange(clientX, 0, w, -12, 12);
    const y = mapRange(clientY, 0, h, -12, 12);
    setMouseParallax({ x, y });
  }

  return (
    <>
      <div className="raca-landing-shell" onMouseMove={handleMouseMove}>
        {/* ── SCROLL PROGRESS GLOW RIBBON (Glass UI) ── */}
        <div
          className="raca-scroll-progress-bar"
          style={{ transform: `scaleX(${scrollProgress})` }}
          aria-hidden="true"
        />

        {/* ── STICKY GLASS HEADER RIBBON ── */}
        <header className="raca-navbar raca-glass-ribbon">
          <div className="raca-navbar-inner">
            <div className="raca-brand" onClick={() => onNavigate("landing")}>
              <RacaLogo size={34} />
              <div className="raca-brand-text">
                <span className="raca-brand-title">RACA</span>
                <span className="raca-brand-sub">Repository Aware Coding Assistant</span>
              </div>
            </div>

            <nav className={`raca-nav-links ${menuOpen ? "open" : ""}`}>
              <button
                type="button"
                className="raca-nav-link active"
                onClick={() => { setMenuOpen(false); onNavigate("landing"); }}
              >
                Home
              </button>
              <button
                type="button"
                className="raca-nav-link"
                onClick={() => { setMenuOpen(false); onNavigate("about"); }}
              >
                About
              </button>
              <button
                type="button"
                className="raca-nav-link"
                onClick={() => { setMenuOpen(false); onNavigate("team"); }}
              >
                Team
              </button>
              <button
                type="button"
                className="raca-nav-link"
                onClick={() => { setMenuOpen(false); onNavigate("contact"); }}
              >
                Contact
              </button>
            </nav>

            <div className="raca-nav-actions">
              <a
                className="raca-github-link raca-glass-pill"
                href={GITHUB_REPO_URL}
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Open RACA on GitHub"
                title="GitHub"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    fill="currentColor"
                    d="M12 .5a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58v-2.23c-3.34.73-4.04-1.42-4.04-1.42-.55-1.4-1.33-1.77-1.33-1.77-1.09-.75.08-.74.08-.74 1.2.08 1.83 1.23 1.83 1.23 1.07 1.83 2.8 1.3 3.49.99.11-.78.42-1.3.76-1.6-2.67-.3-5.47-1.34-5.47-5.95 0-1.31.47-2.38 1.23-3.22-.12-.3-.53-1.52.12-3.17 0 0 1-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.29-1.55 3.29-1.23 3.29-1.23.66 1.65.25 2.87.13 3.17.77.84 1.23 1.91 1.23 3.22 0 4.62-2.8 5.64-5.48 5.94.43.37.81 1.1.81 2.22v3.3c0 .32.22.69.83.57A12 12 0 0 0 12 .5Z"
                  />
                </svg>
              </a>

              {/* Theme switch toggle */}
              <button
                type="button"
                className="raca-theme-toggle raca-glass-pill"
                onClick={onToggleTheme}
                aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
                title={theme === "dark" ? "Light mode" : "Dark mode"}
              >
                <span className={`raca-toggle-knob ${theme}`} />
              </button>

              {/* Glass Docs Button with dummyurl for GDrive */}
              <button
                type="button"
                className="raca-download-btn raca-glass-btn"
                onClick={handleDownloadClick}
                title="Download documentation"
              >
                Docs ↓
              </button>

              {/* Glowing Glass Workspace Button */}
              <button
                type="button"
                className="raca-workspace-btn"
                onClick={scrollToWorkspace}
              >
                Workspace
              </button>

              {/* Log in / User session controls matching Layout */}
              {user ? (
                <div className="navbar-user">
                  <span className="user-avatar">{user.name.slice(0, 1).toUpperCase()}</span>
                  <span className="user-name">{user.name}</span>
                  <button type="button" className="ghost-button" onClick={handleLogout}>
                    Log out
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  className="login-button"
                  onClick={() => {
                    setLoginOpen(true);
                    setLoginError("");
                  }}
                >
                  Log in
                </button>
              )}

              <button
                type="button"
                className="raca-mobile-toggle raca-glass-pill"
                aria-label="Toggle navigation menu"
                onClick={() => setMenuOpen((o) => !o)}
              >
                <span />
                <span />
                <span />
              </button>
            </div>
          </div>
        </header>

        {/* ── HERO WRAPPER WITH INTERACTIVE SHADER CANVAS ── */}
        <div className="raca-hero-canvas-wrapper">
          <ShaderBackground />

          <main className="raca-main-container" style={{ position: "relative", zIndex: 1 }}>
            <section className="raca-hero-section">
              <div className="raca-hero-left">
                <span className="raca-eyebrow">
                  <SplitText text="YOUR CODEBASE. UNDERSTOOD." delay={0.1} />
                </span>
                <h1 className="raca-hero-title">
                  <SplitText text="RACA" delay={0.2} charDelay={0.05} />
                </h1>
                <h2 className="raca-hero-subtitle">
                  Repository-Aware AI Coding Assistant
                </h2>
                <p className="raca-hero-description">
                  Navigate, investigate, and understand any GitHub repository with an
                  assistant that reads the entire codebase architecture — not isolated
                  files.
                </p>
              </div>

              <div
                className="raca-hero-right"
                style={{
                  transform: `translate3d(${mouseParallax.x * -0.7}px, ${mouseParallax.y * -0.7}px, 0)`,
                  transition: "transform 0.2s cubic-bezier(0.16, 1, 0.3, 1)",
                }}
              >
                <img
                  src={heroArt}
                  alt="RACA 3-layer architecture"
                  className="raca-hero-image"
                />
              </div>
            </section>

            {/* ── ACTIVE REPOSITORY GLASS CARD (MATCHING SCREENSHOT) ── */}
            <section
              ref={heroCardRef}
              className={`raca-active-repo-card raca-glass-card ${isHeroCardInView ? "revealed" : ""}`}
            >
              <div className="raca-card-header">
                <div className="raca-card-label">
                  <span className="raca-live-dot" />
                  <span>ACTIVE REPOSITORY</span>
                </div>
                <span className="raca-status-badge raca-glass-pill">Ready to Connect</span>
              </div>

              <form className="raca-ingest-bar" onSubmit={handleIngest}>
                <div className="raca-input-wrapper raca-glass-input">
                  <span className="raca-prefix">{GITHUB_PREFIX}</span>
                  <input
                    type="text"
                    className="raca-repo-input"
                    value={repoInput}
                    onChange={(e) => setRepoInput(e.target.value)}
                    onFocus={() => setIsInputFocused(true)}
                    onBlur={() => setIsInputFocused(false)}
                    placeholder={typedPlaceholder}
                    aria-label="Repository URL"
                    spellCheck={false}
                    autoComplete="off"
                  />
                </div>
                <button type="submit" className="raca-ingest-btn raca-glow-btn">
                  Ingest Repository →
                </button>
              </form>
            </section>
          </main>
        </div>

        {/* ── SCROLL SECTION: 2ND PAGE / WORKSPACE SECTION ── */}
        <div ref={workspaceRef} id="workspace-section" className="raca-workspace-scroll-section">
          <div className="raca-main-container">
            <div className="raca-section-header">
              <span className="raca-eyebrow">WORKSPACE &amp; CAPABILITIES</span>
              <h2 className="raca-section-heading">Connected Repository Tools</h2>
            </div>
            {workspaceSection}
          </div>
        </div>

        {/* ── FOOTER WITH GLASS TOUCHES ── */}
        <footer className="raca-footer raca-glass-ribbon">
          <div className="raca-main-container raca-footer-content">
            <div className="raca-footer-left">
              <span className="raca-footer-brand">RACA</span>
              <span className="raca-footer-copy">
                © {new Date().getFullYear()} Repository-Aware Coding Assistant
              </span>
            </div>
            <div className="raca-footer-links">
              <button type="button" onClick={() => onNavigate("about")}>About</button>
              <button type="button" onClick={() => onNavigate("team")}>Team</button>
              <button type="button" onClick={() => onNavigate("contact")}>Contact</button>
              <button type="button" onClick={handleDownloadClick}>Docs</button>
            </div>
          </div>
        </footer>
      </div>

      {loginOpen && (
        <div
          className="modal-backdrop login-backdrop"
          style={{ zIndex: 9999 }}
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setLoginOpen(false);
          }}
        >
          <section className="replace-dialog login-dialog" role="dialog" aria-modal="true" aria-labelledby="login-title">
            <button type="button" className="dialog-close" aria-label="Close login" onClick={() => setLoginOpen(false)}>×</button>
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
    </>
  );
}