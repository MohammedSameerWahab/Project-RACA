const TEAM = [
  {
    name: "Kattika Mohammed Sameer Wahab",
    initials: "KM",
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
  return (
    <article className="site-page reveal-page">
      <header className="site-page-hero">
        <span className="eyebrow">ABOUT</span>
        <h1>Built around the repository you are actually working in.</h1>
        <p>
          RACA clones your GitHub project, indexes the source, and keeps every
          answer tied to real files and symbols — not generic training data.
        </p>
      </header>
      <div className="info-grid">
        <section className="info-card">
          <h2>What RACA does</h2>
          <p>
            It retrieves relevant files, function definitions, and module
            relationships from the active codebase, then uses that evidence when
            answering. You can point it at any public GitHub repository and start
            asking questions within minutes.
          </p>
        </section>
        <section className="info-card">
          <h2>How the index works</h2>
          <p>
            Semantic search, keyword retrieval, and a code-graph run together on
            the same indexed snapshot. The editor, repository understanding,
            navigation, and bug investigation pages all read from that single
            source of truth.
          </p>
        </section>
        <section className="info-card">
          <h2>Who it is for</h2>
          <p>
            Developers joining an unfamiliar codebase, tracing a failure across
            multiple files, or asking questions that should point back to real
            source locations rather than guessed answers.
          </p>
        </section>
      </div>
    </article>
  );
}

export function TeamPage() {
  return (
    <article className="site-page reveal-page">
      <header className="site-page-hero">
        <span className="eyebrow">TEAM</span>
        <h1>Who built this.</h1>
        <p>
          Four people, each responsible for a different part of the system —
          retrieval, knowledge graph, source analysis, and integration.
        </p>
      </header>
      <div className="role-grid">
        {TEAM.map((member, i) => (
          <section className="role-card" key={member.name} style={{ "--card-delay": `${i * 60}ms` }}>
            <div className="member-header">
              <span className="member-avatar">{member.initials}</span>
              <div>
                <h2>{member.name}</h2>
                <span className="member-role-tag">{member.role}</span>
              </div>
            </div>
            <p>{member.focus}</p>
            <ul>
              {member.duties.map((duty) => (
                <li key={duty}>{duty}</li>
              ))}
            </ul>
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
    <article className="site-page reveal-page">
      <header className="site-page-hero">
        <span className="eyebrow">CONTACT</span>
        <h1>Got a question or something you want RACA to handle better?</h1>
        <p>
          Use this form to share feedback, report a retrieval issue, or ask about
          the project. It runs entirely in the browser and does not call the RACA
          API.
        </p>
      </header>
      <form className="contact-form" onSubmit={handleSubmit}>
        <label>
          Name
          <input name="name" type="text" required placeholder="Your name" />
        </label>
        <label>
          Email
          <input name="email" type="email" required placeholder="you@example.com" />
        </label>
        <label>
          Topic
          <select name="topic" defaultValue="product">
            <option value="product">Product feedback</option>
            <option value="workspace">Editor or workspace</option>
            <option value="indexing">Indexing or retrieval</option>
            <option value="team">Team or roles</option>
            <option value="other">Something else</option>
          </select>
        </label>
        <label>
          Message
          <textarea name="message" required rows={6} placeholder="What's on your mind?" />
        </label>
        <button type="submit">Send message</button>
      </form>
    </article>
  );
}
