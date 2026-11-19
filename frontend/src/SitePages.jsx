import { useState } from "react";
import "./Layout.css";

const TEAM = [
  {
    name: "Kattika Mohammed Sameer Wahab",
    initials: "KM",
    regNo: "23BCE20316",
    role: "AI Retrieval & Context Engineering",
    focus:
      "Designs and implements the AI-driven retrieval and context generation layer. Ensures the system retrieves relevant repository information using semantic similarity and combines it with other retrieval mechanisms before supplying the final context to the LLM.",
    duties: [
      "Semantic similarity retrieval pipeline",
      "Context generation and fusion across retrieval sources",
      "Supplying structured context to the language model",
    ],
  },
  {
    name: "Angelina Ruth Robert",
    initials: "AR",
    regNo: "23BCE8127",
    role: "Knowledge Graph & Search Infrastructure",
    focus:
      "Responsible for the design and implementation of the repository knowledge graph and keyword-search infrastructure. Works on representing relationships between software entities — files, functions, classes, modules, and dependencies — in a structured graph.",
    duties: [
      "Repository knowledge graph design and construction",
      "Keyword-search infrastructure",
      "Modelling entity relationships across the codebase",
    ],
  },
  {
    name: "Mohammed Aadil M",
    initials: "MA",
    regNo: "23BCE8913",
    role: "Repository Analysis & Program Intelligence",
    focus:
      "Converts raw source code into structured repository knowledge. Analyses repository files and extracts information such as files, functions, classes, methods, imports, function calls, and relationships to support the graph, keyword, and RAG retrieval modules.",
    duties: [
      "Source code parsing and entity extraction",
      "Structured output for graph and retrieval modules",
      "Function call and import relationship mapping",
    ],
  },
  {
    name: "Samruddha Kalyankar",
    initials: "SK",
    regNo: "23BCE8851",
    role: "Full-Stack & System Integration",
    focus:
      "Full-Stack Developer and System Integration Engineer. Focuses on designing and implementing the application layer and integrating the components developed by other team members into a unified, cohesive software system.",
    duties: [
      "Application layer design and implementation",
      "Component integration across retrieval, graph, and AI modules",
      "End-to-end system cohesion and deployment",
    ],
  },
];

export function AboutPage() {
  const [activeTab, setActiveTab] = useState(0);

  const pillars = [
    {
      num: "01",
      badge: "PURPOSE",
      title: "What RACA does",
      desc: "RACA retrieves relevant files, function definitions, and module relationships directly from your repository snapshot. It answers every question grounded in actual source code and verifiable symbols — eliminating LLM hallucinations.",
      tags: ["Deterministic Lookup", "Repository Snapshot", "Grounded Context"],
    },
    {
      num: "02",
      badge: "ARCHITECTURE",
      title: "Three retrieval layers",
      desc: "Semantic vector search, exact keyword matching, and an entity call-graph execute in unison across PostgreSQL and Neo4j. The code editor and analysis tools all consume this single source of verified truth.",
      tags: ["Vector Embeddings", "Full-Text Index", "Neo4j Call Graph"],
    },
    {
      num: "03",
      badge: "WORKFLOW",
      title: "Who it is built for",
      desc: "Engineers onboarding onto large legacy codebases, debugging multi-file execution paths, or investigating stack traces. Every output points directly to file paths, lines, and call relationships.",
      tags: ["Instant Onboarding", "Cross-file Debugging", "Architecture Mapping"],
    },
  ];

  return (
    <article className="site-page modern-page reveal-page">
      <header className="site-page-hero modern-glass-hero">
        <span className="eyebrow modern-eyebrow">ABOUT RACA</span>
        <h1 className="modern-hero-headline">
          Grounded intelligence for the codebase you actually work in.
        </h1>
        <p className="modern-hero-sub">
          RACA clones your GitHub project, indexes the source code, and binds every
          answer to verifiable files and symbols rather than generic training data.
        </p>
      </header>

      {/* Modern Glass Pillar Cards */}
      <div className="modern-info-grid">
        {pillars.map((pillar, idx) => (
          <section
            key={pillar.title}
            className={`modern-info-card ${activeTab === idx ? "active" : ""}`}
            onMouseEnter={() => setActiveTab(idx)}
          >
            <div className="card-top-row">
              <span className="pillar-num">{pillar.num}</span>
              <span className="pillar-badge">{pillar.badge}</span>
            </div>
            <h2>{pillar.title}</h2>
            <p>{pillar.desc}</p>
            <div className="pillar-tags">
              {pillar.tags.map((tag) => (
                <span key={tag} className="pillar-tag">{tag}</span>
              ))}
            </div>
          </section>
        ))}
      </div>

      {/* Capabilities Overview Section */}
      <div className="modern-glass-banner">
        <div className="banner-text">
          <h3>Local Privacy &amp; Fallback Resilience</h3>
          <p>
            Code embeddings run locally in your environment. RACA automatically falls back
            through configured LLM providers (Google, Groq, Cloudflare, NVIDIA NIM) if any rate limit is hit.
          </p>
        </div>
        <div className="banner-stats">
          <div className="stat-box">
            <strong>3-Way</strong>
            <span>Retrieval Fusion</span>
          </div>
          <div className="stat-box">
            <strong>16-Way</strong>
            <span>Robustness</span>
          </div>
        </div>
      </div>
    </article>
  );
}

export function TeamPage() {
  return (
    <article className="site-page modern-page reveal-page">
      <header className="site-page-hero modern-glass-hero">
        <span className="eyebrow modern-eyebrow">OUR TEAM</span>
        <h1 className="modern-hero-headline">Our Team.</h1>
        <p className="modern-hero-sub">
          Four engineers specializing in retrieval, knowledge graphs, source analysis, and full-stack integration.
        </p>
      </header>

      {/* Balanced Modern Grid with Proportional Square/Wide Cards */}
      <div className="modern-team-grid">
        {TEAM.map((member, i) => (
          <section
            className="modern-team-card"
            key={member.name}
            style={{ animationDelay: `${i * 90}ms` }}
          >
            <div className="modern-team-header">
              <div className="modern-avatar-badge">{member.initials}</div>
              <div className="modern-member-meta">
                <h2>{member.name}</h2>
                <div className="modern-reg-pill">{member.regNo}</div>
                <span className="modern-role-pill">{member.role}</span>
              </div>
            </div>

            <p className="modern-team-focus">{member.focus}</p>

            <div className="modern-duties-wrapper">
              <span className="duties-label">KEY CONTRIBUTIONS:</span>
              <div className="modern-duties-chips">
                {member.duties.map((duty) => (
                  <span key={duty} className="modern-duty-chip">
                    {duty}
                  </span>
                ))}
              </div>
            </div>
          </section>
        ))}
      </div>
    </article>
  );
}

export function ContactPage() {
  function handleSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const name = form.querySelector('[name="name"]').value.trim();
    window.alert(
      `Thanks${name ? `, ${name}` : ""}. Your message is saved in the browser only — nothing is sent to any server.`
    );
    form.reset();
  }

  return (
    <article className="site-page modern-page reveal-page">
      <header className="site-page-hero modern-glass-hero">
        <span className="eyebrow modern-eyebrow">GET IN TOUCH</span>
        <h1 className="modern-hero-headline">Have feedback or an indexing suggestion?</h1>
        <p className="modern-hero-sub">
          Share your experience, suggest architectural improvements, or report retrieval edge cases.
        </p>
      </header>

      <form className="modern-contact-form" onSubmit={handleSubmit}>
        <div className="form-row-2">
          <label>
            Name
            <input name="name" type="text" required placeholder="Your name" />
          </label>
          <label>
            Email
            <input name="email" type="email" required placeholder="you@example.com" />
          </label>
        </div>
        <label>
          Topic
          <select name="topic" defaultValue="product">
            <option value="product">Product feedback</option>
            <option value="workspace">Editor &amp; Workspace</option>
            <option value="indexing">Indexing &amp; Graph Retrieval</option>
            <option value="team">Team or Roles</option>
            <option value="other">General Question</option>
          </select>
        </label>
        <label>
          Message
          <textarea name="message" required rows={5} placeholder="Describe your question or feedback in detail…" />
        </label>
        <button type="submit" className="modern-submit-btn">Send Message →</button>
      </form>
    </article>
  );
}
