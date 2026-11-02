/**
 * Portfolio / Visual CV
 * Renders every section from cv.json (exported by portfolio_builder.py) and wires the
 * skill -> project filter, category filter, and light/dark theme toggle.
 */

let cv = null;
let activeCategory = 'All';
let activeSkill = null;

const ICONS = {
  mail: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
  github: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.05-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.56-.29-5.25-1.28-5.25-5.69 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.42-2.7 5.4-5.27 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5Z"/></svg>',
  linkedin: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28ZM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13ZM7.12 20.45H3.56V9h3.56v11.45ZM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0Z"/></svg>',
  external: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
  pin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
  lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
  sun: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>',
  moon: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z"/></svg>',
};

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
  initThemeToggle();
  try {
    const res = await fetch('cv.json', { cache: 'no-cache' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    cv = await res.json();
  } catch (err) {
    document.getElementById('main').innerHTML = `
      <div class="load-error wrap">
        <h2>CV data could not be loaded</h2>
        <p>Run <code>python portfolio_builder.py</code> and open this page through a web server
        (for example the dashboard at <code>/portfolio/</code>), not straight from the file system.</p>
      </div>`;
    return;
  }
  if (document.body.dataset.page === 'project') {
    renderProjectPage();
  } else {
    renderAll();
  }
});

function renderAll() {
  renderNav();
  renderHero();
  renderSkills();
  renderHowIBuild();
  renderProjectFilters();
  renderProjects();
  renderSystemMap();
  renderTimeline();
  renderEducation();
  renderContact();
  renderFooter();
}

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------
function renderNav() {
  const p = cv.profile || {};
  document.getElementById('nav-name').textContent = p.name || '';
  document.getElementById('nav-mark').textContent = initials(p.name);
}

function renderHero() {
  const p = cv.profile || {};
  const links = p.links || {};
  const openTo = (p.open_to || []).map(r => `<span class="chip">${esc(r)}</span>`).join('');

  document.getElementById('hero-main').innerHTML = `
    ${p.availability ? `<span class="availability">${esc(p.availability)}</span>` : ''}
    <h1>${esc(p.name)}</h1>
    <div class="hero-title">${esc(p.title)}</div>
    ${p.tagline ? `<p class="hero-tagline">${esc(p.tagline)}</p>` : ''}
    ${p.summary ? `<p class="hero-summary">${esc(p.summary)}</p>` : ''}
    ${p.location ? `<div class="hero-location">${ICONS.pin}${esc(p.location)}</div>` : ''}
    ${openTo ? `<div class="hero-meta"><span class="label">Open to</span>${openTo}</div>` : ''}
    <div class="hero-actions">${contactButtons(p, links, true)}</div>
  `;

  const skillCount = (cv.skills || []).reduce((n, g) => n + (g.items || []).length, 0);
  const stats = [
    [(cv.projects || []).length, 'Projects'],
    [skillCount, 'Skills'],
    [(cv.experience || []).length, (cv.experience || []).length === 1 ? 'Role' : 'Roles'],
    [(cv.certifications || []).length, 'Certifications'],
  ];

  // Rated skills show average level per area; without ratings, show how many skills each area holds
  const groups = (cv.skills || []).map(g => {
    const items = g.items || [];
    const rated = items.filter(i => hasLevel(i));
    return {
      name: g.category,
      count: items.length,
      avg: rated.length ? rated.reduce((s, i) => s + i.level, 0) / rated.length : null,
    };
  });
  const anyRated = groups.some(g => g.avg !== null);
  const maxCount = Math.max(1, ...groups.map(g => g.count));
  const rows = anyRated
    ? groups.filter(g => g.avg !== null).sort((a, b) => b.avg - a.avg)
        .map(g => ({ name: g.name, value: `${g.avg.toFixed(1)} / 5`, pct: (g.avg / 5) * 100 }))
    : [...groups].sort((a, b) => b.count - a.count)
        .map(g => ({ name: g.name, value: `${g.count} skill${g.count === 1 ? '' : 's'}`, pct: (g.count / maxCount) * 100 }));

  document.getElementById('hero-card').innerHTML = `
    <h2>At a glance</h2>
    <div class="stat-grid">
      ${stats.map(([v, l]) => `<div class="stat"><div class="stat-value">${v}</div><div class="stat-label">${l}</div></div>`).join('')}
    </div>
    <h2>${anyRated ? 'Strongest areas' : 'Skills by area'}</h2>
    <ul class="strength-list">
      ${rows.map(r => `
        <li class="strength-row">
          <span class="name">${esc(r.name)}</span>
          <span class="value">${r.value}</span>
          <span class="strength-bar" aria-hidden="true"><span style="width: ${r.pct}%"></span></span>
        </li>`).join('')}
    </ul>
  `;
}

function renderSkills() {
  const grid = document.getElementById('skills-grid');
  grid.innerHTML = (cv.skills || []).map(group => `
    <div class="skill-group">
      <h3>${esc(group.category)}</h3>
      <ul class="skill-list">
        ${(group.items || []).map(skill => {
          const rated = hasLevel(skill);
          const uses = projectsUsing(skill.name).length;
          const meter = rated
            ? `<span class="meter" aria-hidden="true">${[1, 2, 3, 4, 5].map(i => `<i class="${i <= skill.level ? 'on' : ''}"></i>`).join('')}</span>`
            : '<span></span>';
          return `
            <li>
              <button class="skill-btn" type="button" data-skill="${esc(skill.name)}" aria-pressed="${activeSkill === skill.name}"
                aria-label="${esc(skill.name)}${rated ? `, level ${skill.level} of 5` : ''}, used in ${uses} project${uses === 1 ? '' : 's'}">
                <span class="skill-name">${esc(skill.name)}</span>
                <span class="skill-uses">${uses ? `${uses} proj` : ''}</span>
                ${meter}
              </button>
            </li>`;
        }).join('')}
      </ul>
    </div>
  `).join('');

  grid.querySelectorAll('.skill-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const name = btn.dataset.skill;
      activeSkill = activeSkill === name ? null : name;
      renderSkills();
      renderProjects();
      if (activeSkill) document.getElementById('projects').scrollIntoView({ behavior: 'smooth' });
    });
  });
}

function renderHowIBuild() {
  const how = cv.how_i_build;
  if (!how || !(how.steps || []).length) return;
  document.getElementById('how-i-build').hidden = false;
  if (how.title) document.getElementById('build-title').textContent = how.title;
  document.getElementById('build-intro').textContent = how.intro || '';
  document.getElementById('build-steps').innerHTML = how.steps.map((s, i) => `
    <li class="diagram-node">
      <span class="diagram-step" aria-hidden="true">${i + 1}</span>
      <strong>${esc(s.label)}</strong>
      <span>${esc(s.detail)}</span>
    </li>`).join('');
  document.getElementById('build-tools').innerHTML = (how.tools || []).length
    ? `<span>Tools</span>${how.tools.map(t => `<span class="chip tech">${esc(t)}</span>`).join('')}`
    : '';
}

function renderProjectFilters() {
  const categories = ['All', ...new Set((cv.projects || []).map(p => p.category).filter(Boolean))];
  const bar = document.getElementById('project-filters');
  bar.hidden = categories.length <= 2;
  bar.innerHTML = categories.map(c =>
    `<button class="filter-btn" type="button" data-category="${esc(c)}" aria-pressed="${c === activeCategory}">${esc(c)}</button>`
  ).join('');
  bar.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      activeCategory = btn.dataset.category;
      renderProjectFilters();
      renderProjects();
    });
  });
}

function renderProjects() {
  const all = sortedProjects();
  const visible = all.filter(p =>
    (activeCategory === 'All' || p.category === activeCategory) &&
    (!activeSkill || usesSkill(p, activeSkill))
  );

  document.getElementById('projects-caption').textContent =
    `${visible.length} of ${all.length} project${all.length === 1 ? '' : 's'}`;

  const skillBar = document.getElementById('active-skill');
  skillBar.hidden = !activeSkill;
  if (activeSkill) {
    skillBar.innerHTML = `<span>Projects using <span class="chip match">${esc(activeSkill)}</span></span>
      <button class="clear-btn" type="button">Clear filter</button>`;
    skillBar.querySelector('.clear-btn').addEventListener('click', () => {
      activeSkill = null;
      renderSkills();
      renderProjects();
    });
  }

  const grid = document.getElementById('projects-grid');
  if (!visible.length) {
    grid.innerHTML = `<div class="empty-state">No projects match this filter yet.</div>`;
    return;
  }

  grid.innerHTML = visible.map(p => {
    const caseUrl = p.slug ? `project.html?p=${encodeURIComponent(p.slug)}` : '';
    const cover = (p.gallery || [])[0];
    const linkHtml = [
      caseUrl && `<a href="${caseUrl}">Read case study →</a>`,
      ...projectLinks(p),
    ].filter(Boolean).join('');

    return `
      <article class="project-card ${p.featured ? 'featured' : ''} ${cover ? 'has-cover' : ''}">
        ${cover ? `
          <a class="project-cover" href="${caseUrl || '#'}" tabindex="-1" aria-hidden="true">
            <img src="${esc(cover.src)}" alt="" loading="lazy">
          </a>` : ''}
        <div class="project-top">
          <span class="project-category">${esc(p.category || '')}</span>
          ${p.featured ? '<span class="badge-featured">Featured</span>' : ''}
        </div>
        <h3>${caseUrl ? `<a class="project-title-link" href="${caseUrl}">${esc(p.name)}</a>` : esc(p.name)}</h3>
        ${p.summary ? `<p class="project-summary">${esc(p.summary)}</p>` : ''}
        ${(p.highlights || []).length ? `<ul class="project-highlights">${p.highlights.slice(0, 2).map(h => `<li>${esc(h)}</li>`).join('')}</ul>` : ''}
        <div class="project-tech">
          ${(p.tech || []).map(t => `<span class="chip tech ${activeSkill && sameSkill(t, activeSkill) ? 'match' : ''}">${esc(t)}</span>`).join('')}
        </div>
        ${linkHtml ? `<div class="project-links">${linkHtml}</div>` : ''}
      </article>`;
  }).join('');
}

// Live site and public code links shared by the cards and the case-study page
function projectLinks(p) {
  const links = p.links || {};
  return [
    safeUrl(links.live) && `<a href="${esc(safeUrl(links.live))}" target="_blank" rel="noopener">${ICONS.external}Live site</a>`,
    safeUrl(links.github) && `<a href="${esc(safeUrl(links.github))}" target="_blank" rel="noopener">${ICONS.github}Code</a>`,
    safeUrl(links.demo) && `<a href="${esc(safeUrl(links.demo))}" target="_blank" rel="noopener">${ICONS.external}Live demo</a>`,
  ].filter(Boolean);
}

function sortedProjects() {
  return [...(cv.projects || [])].sort((a, b) => Number(!!b.featured) - Number(!!a.featured));
}

// ---------------------------------------------------------------------------
// Case-study page (project.html?p=<slug>)
// ---------------------------------------------------------------------------
function renderProjectPage() {
  renderNav();
  renderFooter();
  const slug = new URLSearchParams(window.location.search).get('p');
  const projects = sortedProjects().filter(p => p.slug);
  const index = projects.findIndex(p => p.slug === slug);
  const main = document.getElementById('main');

  if (index < 0) {
    main.innerHTML = `
      <div class="load-error wrap">
        <h2>Project not found</h2>
        <p><a href="./#projects">See all projects</a></p>
      </div>`;
    return;
  }

  const p = projects[index];
  const prev = projects[(index - 1 + projects.length) % projects.length];
  const next = projects[(index + 1) % projects.length];
  document.title = `${p.name} | ${(cv.profile || {}).name || 'Portfolio'}`;

  const overview = [].concat(p.overview || p.summary || []);
  const links = projectLinks(p).map(l => l.replace('<a ', '<a class="btn" '));
  const list = items => `<ul class="case-list">${items.map(i => `<li>${esc(i)}</li>`).join('')}</ul>`;

  main.innerHTML = `
    <article class="case wrap">
      <a class="back-link" href="./#projects">← All projects</a>
      <header class="case-head">
        <div class="project-top">
          <span class="project-category">${esc(p.category || '')}</span>
          ${p.featured ? '<span class="badge-featured">Featured</span>' : ''}
        </div>
        <h1>${esc(p.name)}</h1>
        ${p.summary ? `<p class="case-summary">${esc(p.summary)}</p>` : ''}
        <div class="case-links">
          ${links.join('')}
          ${p.code_note ? `<span class="code-note">${ICONS.lock}${esc(p.code_note)}</span>` : ''}
        </div>
      </header>

      <section class="case-section">
        <h2>Overview</h2>
        ${overview.map(t => `<p>${esc(t)}</p>`).join('')}
        ${(p.highlights || []).length ? list(p.highlights) : ''}
      </section>

      ${(p.gallery || []).length ? `
        <section class="case-section">
          <h2>Screens & results</h2>
          <div class="gallery">
            ${p.gallery.map((g, i) => `
              <figure>
                <button class="shot" type="button" data-index="${i}" aria-label="Enlarge: ${esc(g.caption || p.name)}">
                  <img src="${esc(g.src)}" alt="${esc(g.caption || p.name)}" loading="lazy">
                </button>
                ${g.caption ? `<figcaption>${esc(g.caption)}</figcaption>` : ''}
              </figure>`).join('')}
          </div>
        </section>` : ''}

      ${(p.architecture || []).length ? `
        <section class="case-section">
          <h2>Architecture</h2>
          ${renderDiagram(p)}
        </section>` : ''}

      ${(p.diagrams || []).map(d => `
        <section class="case-section">
          <h2>${esc(d.title)}</h2>
          ${d.caption ? `<p>${esc(d.caption)}</p>` : ''}
          ${renderDiagram({ name: d.title, diagram: d.style, architecture: d.steps || [] })}
        </section>`).join('')}

      ${p.proof ? renderProof(p.proof) : ''}

      ${(p.decisions || []).length || (p.results || []).length ? `
        <section class="case-section case-columns">
          ${(p.decisions || []).length ? `<div><h2>Key engineering decisions</h2>${list(p.decisions)}</div>` : ''}
          ${(p.results || []).length ? `<div><h2>Results</h2>${list(p.results)}</div>` : ''}
        </section>` : ''}

      ${(p.outcome || []).length ? `
        <section class="case-section">
          <h2>Outcome</h2>
          ${p.outcome.map(t => `<p>${esc(t)}</p>`).join('')}
        </section>` : ''}

      ${(p.tech || []).length ? `
        <section class="case-section">
          <h2>Built with</h2>
          <div class="project-tech">${p.tech.map(t => `<span class="chip tech">${esc(t)}</span>`).join('')}</div>
        </section>` : ''}

      <nav class="case-nav" aria-label="More projects">
        <a href="project.html?p=${encodeURIComponent(prev.slug)}"><span>Previous</span>${esc(prev.name)}</a>
        <a href="project.html?p=${encodeURIComponent(next.slug)}"><span>Next</span>${esc(next.name)}</a>
      </nav>
    </article>
  `;

  initLightbox(p.gallery || []);
}

// ---------------------------------------------------------------------------
// System map: how the projects connect (inline SVG from cv.system_map)
// ---------------------------------------------------------------------------
const MAP_NODE_W = 210;
const MAP_NODE_H = 104;

function wrapText(text, maxChars) {
  const lines = [];
  let line = '';
  String(text || '').split(/\s+/).forEach(word => {
    if ((line + ' ' + word).trim().length > maxChars && line) {
      lines.push(line);
      line = word;
    } else {
      line = (line + ' ' + word).trim();
    }
  });
  if (line) lines.push(line);
  return lines;
}

function edgePath(from, to) {
  const fc = { x: from.x + MAP_NODE_W / 2, y: from.y + MAP_NODE_H / 2 };
  const tc = { x: to.x + MAP_NODE_W / 2, y: to.y + MAP_NODE_H / 2 };
  const dx = tc.x - fc.x;
  const dy = tc.y - fc.y;
  let a, b, c1, c2;
  if (Math.abs(dx) >= Math.abs(dy)) {
    const dir = Math.sign(dx) || 1;
    a = { x: fc.x + dir * MAP_NODE_W / 2, y: fc.y };
    b = { x: tc.x - dir * (MAP_NODE_W / 2 + 6), y: tc.y };
    const bend = (b.x - a.x) / 2;
    c1 = { x: a.x + bend, y: a.y };
    c2 = { x: b.x - bend, y: b.y };
  } else {
    const dir = Math.sign(dy) || 1;
    a = { x: fc.x, y: fc.y + dir * MAP_NODE_H / 2 };
    b = { x: tc.x, y: tc.y - dir * (MAP_NODE_H / 2 + 6) };
    const bend = (b.y - a.y) / 2;
    c1 = { x: a.x, y: a.y + bend };
    c2 = { x: b.x, y: b.y - bend };
  }
  const mid = { x: (a.x + 3 * c1.x + 3 * c2.x + b.x) / 8, y: (a.y + 3 * c1.y + 3 * c2.y + b.y) / 8 };
  return { d: `M${a.x},${a.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${b.x},${b.y}`, mid };
}

function renderSystemMap() {
  const map = cv.system_map;
  const section = document.getElementById('system');
  if (!map || !(map.nodes || []).length) return;
  section.hidden = false;
  if (map.title) document.getElementById('system-title').textContent = map.title;
  document.getElementById('system-intro').textContent = map.intro || '';
  document.getElementById('system-note').textContent = map.note || '';

  const nodes = Object.fromEntries(map.nodes.map(n => [n.id, n]));
  const width = map.width || 1120;
  const height = map.height || 560;

  const lanes = (map.lanes || []).map(l => `
    <text class="map-lane" x="${l.x}" y="22">${esc(l.label)}</text>`).join('');

  const edges = (map.edges || []).filter(e => nodes[e.from] && nodes[e.to]).map(e => {
    const { d, mid } = edgePath(nodes[e.from], nodes[e.to]);
    const label = e.label || '';
    const w = label.length * 6.3 + 14;
    return `
      <g class="map-edge">
        <path d="${d}" marker-end="url(#map-arrow)"></path>
        ${label ? `<rect x="${mid.x - w / 2}" y="${mid.y - 11}" width="${w}" height="20" rx="10"></rect>
        <text x="${mid.x}" y="${mid.y + 4}" text-anchor="middle">${esc(label)}</text>` : ''}
      </g>`;
  }).join('');

  const boxes = map.nodes.map(n => {
    const sub = wrapText(n.sub, 31).slice(0, 4);
    const body = `
      <rect class="map-node-box ${esc(n.kind || '')}" x="${n.x}" y="${n.y}" width="${MAP_NODE_W}" height="${MAP_NODE_H}" rx="12"></rect>
      <text class="map-node-title" x="${n.x + 14}" y="${n.y + 26}">${esc(n.label)}</text>
      ${sub.map((line, i) => `<text class="map-node-sub" x="${n.x + 14}" y="${n.y + 46 + i * 15}">${esc(line)}</text>`).join('')}`;
    return n.slug
      ? `<a class="map-node" href="project.html?p=${encodeURIComponent(n.slug)}" aria-label="${esc(n.label)}: open case study">${body}</a>`
      : `<g class="map-node">${body}</g>`;
  }).join('');

  document.getElementById('system-map').innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="system-title" style="min-width: ${Math.round(width * 0.8)}px">
      <defs>
        <marker id="map-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z"></path>
        </marker>
      </defs>
      ${lanes}${edges}${boxes}
    </svg>`;

  document.getElementById('system-edges').innerHTML = (map.edges || [])
    .filter(e => nodes[e.from] && nodes[e.to])
    .map(e => `<li><strong>${esc(nodes[e.from].label)}</strong> → <strong>${esc(nodes[e.to].label)}</strong>${e.label ? `: ${esc(e.label)}` : ''}</li>`)
    .join('');
}

// ---------------------------------------------------------------------------
// Proof of work (stats measured from the repositories + evidence list)
// ---------------------------------------------------------------------------
function compactNumber(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
  return String(n);
}

function formatMonth(ym) {
  const [y, m] = ym.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleString('en', { month: 'short', year: 'numeric' });
}

function renderProof(proof) {
  const s = proof.stats || {};
  const tiles = [
    s.commits ? [s.commits, 'Commits'] : null,
    s.total_code_lines ? [compactNumber(s.total_code_lines), 'Lines of code'] : null,
    s.test_files ? [s.test_files, 'Test files'] : null,
    s.markdown_docs ? [s.markdown_docs, 'Docs & reports'] : null,
  ].filter(Boolean);

  const langs = Object.entries(s.lines_by_language || {}).slice(0, 5);
  const totalLang = langs.reduce((sum, [, n]) => sum + n, 0) || 1;
  const months = Object.entries(s.commits_by_month || {});
  const maxMonth = Math.max(1, ...months.map(([, n]) => n));
  const period = s.first_commit ? `${formatMonth(s.first_commit.slice(0, 7))} – ${formatMonth((s.last_commit || s.first_commit).slice(0, 7))}` : '';

  return `
    <section class="case-section proof">
      <h2>Proof of work</h2>
      ${tiles.length ? `<div class="stat-grid proof-stats">${tiles.map(([v, l]) => `<div class="stat"><div class="stat-value">${esc(v)}</div><div class="stat-label">${esc(l)}</div></div>`).join('')}</div>` : ''}
      ${langs.length ? `
        <div class="lang-bar" role="img" aria-label="Code by language: ${langs.map(([l, n]) => `${l} ${Math.round(n / totalLang * 100)}%`).join(', ')}">
          ${langs.map(([l, n], i) => `<span class="lang-${i}" style="width: ${n / totalLang * 100}%"></span>`).join('')}
        </div>
        <ul class="lang-legend">${langs.map(([l, n], i) => `<li><i class="lang-${i}"></i>${esc(l)} <span>${Math.round(n / totalLang * 100)}%</span></li>`).join('')}</ul>` : ''}
      ${months.length > 1 ? `
        <div class="commit-chart" role="img" aria-label="Commits per month${period ? `, ${period}` : ''}">
          ${months.map(([m, n]) => `<div class="commit-col" title="${esc(formatMonth(m))}: ${n} commits"><span style="height: ${Math.max(4, n / maxMonth * 100)}%"></span><em>${esc(formatMonth(m).split(' ')[0])}</em></div>`).join('')}
        </div>
        <p class="proof-caption">Commits per month${period ? `, ${esc(period)}` : ''}. Counted from the repository's git history.</p>` : ''}
      ${(proof.evidence || []).length ? `<ul class="case-list proof-evidence">${proof.evidence.map(e => `<li>${esc(e)}</li>`).join('')}</ul>` : ''}
      ${proof.measured_on ? `<p class="proof-caption">Code and history measured on ${esc(proof.measured_on)}.</p>` : ''}
    </section>`;
}

function renderDiagram(p) {
  const flow = p.diagram === 'flow';
  return `
    <ol class="diagram ${flow ? 'diagram-flow' : 'diagram-stack'}" aria-label="Architecture of ${esc(p.name)}">
      ${p.architecture.map((a, i) => `
        <li class="diagram-node">
          <span class="diagram-step" aria-hidden="true">${flow ? i + 1 : ''}</span>
          <strong>${esc(a.layer)}</strong>
          <span>${esc(a.detail)}</span>
        </li>`).join('')}
    </ol>`;
}

function initLightbox(gallery) {
  const dialog = document.getElementById('lightbox');
  if (!dialog || !gallery.length) return;
  const img = document.getElementById('lightbox-img');
  const caption = document.getElementById('lightbox-caption');

  document.querySelectorAll('.shot').forEach(btn => {
    btn.addEventListener('click', () => {
      const item = gallery[Number(btn.dataset.index)];
      img.src = item.src;
      img.alt = item.caption || '';
      caption.textContent = item.caption || '';
      dialog.showModal();
    });
  });
  document.getElementById('lightbox-close').addEventListener('click', () => dialog.close());
  // Clicking the dimmed backdrop (the dialog element itself) closes it
  dialog.addEventListener('click', e => { if (e.target === dialog) dialog.close(); });
}

function renderTimeline() {
  const items = cv.experience || [];
  const section = document.getElementById('experience');
  section.hidden = !items.length;
  document.getElementById('timeline').innerHTML = items.map(job => `
    <li class="timeline-item">
      <div class="timeline-period">${esc([job.start, job.end].filter(Boolean).join(' – '))}</div>
      <div class="timeline-role">${esc(job.role)} <span class="timeline-company">· ${esc(job.company)}</span></div>
      ${job.location ? `<div class="timeline-location">${esc(job.location)}</div>` : ''}
      ${(job.highlights || []).length ? `<ul class="timeline-highlights">${job.highlights.map(h => `<li>${esc(h)}</li>`).join('')}</ul>` : ''}
    </li>
  `).join('');
}

function renderEducation() {
  document.getElementById('edu-list').innerHTML = (cv.education || []).map(e => `
    <div class="edu-card">
      <div class="edu-top">
        <h3>${esc(e.institution)}</h3>
        <span class="edu-year">${esc(e.year || '')}</span>
      </div>
      <div class="edu-degree">${esc(e.degree || '')}</div>
      ${e.score ? `<span class="edu-score">${esc(e.score)}</span>` : ''}
      ${e.details ? `<div class="edu-details">${esc(e.details)}</div>` : ''}
    </div>
  `).join('');

  const block = (title, list) => list.length ? `
    <div class="creds-card">
      <h3>${title}</h3>
      <ul class="creds-list">${list.map(i => `<li>${ICONS.check}<span>${esc(i)}</span></li>`).join('')}</ul>
    </div>` : '';
  const p = cv.profile || {};
  const personal = [
    p.date_of_birth ? `Date of birth: ${p.date_of_birth}` : '',
    (cv.interests || []).length ? `Interests: ${cv.interests.join(', ')}` : '',
  ].filter(Boolean);
  document.getElementById('creds').innerHTML =
    block('Certifications', cv.certifications || []) +
    block('Achievements', cv.achievements || []) +
    block('Personal', personal);
}

function renderContact() {
  const p = cv.profile || {};
  const roles = (p.open_to || []).join(', ');
  document.getElementById('contact-card').innerHTML = `
    <div>
      <h2>Let's talk</h2>
      <p>${roles ? `I'm looking for ${esc(roles)} roles. ` : ''}Email is the quickest way to reach me.</p>
    </div>
    <div class="contact-actions">${contactButtons(p, p.links || {}, false)}</div>
  `;
}

function renderFooter() {
  const p = cv.profile || {};
  const updated = cv.generated_at ? ` · Updated ${esc(cv.generated_at.split(' ')[0])}` : '';
  document.getElementById('site-footer').innerHTML = `© ${new Date().getFullYear()} ${esc(p.name)}${updated}`;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function contactButtons(p, links, includeGithub) {
  const external = (url, icon, label) =>
    safeUrl(url) ? `<a class="btn" href="${esc(safeUrl(url))}" target="_blank" rel="noopener">${icon}${label}</a>` : '';
  return [
    p.email ? `<a class="btn btn-primary" href="mailto:${esc(p.email)}">${ICONS.mail}Email me</a>` : '',
    `<a class="btn" href="resume.pdf" download>${ICONS.download}Download CV</a>`,
    includeGithub ? external(links.github, ICONS.github, 'GitHub') : '',
    external(links.linkedin, ICONS.linkedin, 'LinkedIn'),
  ].join('');
}

function hasLevel(skill) {
  return Number.isInteger(skill.level) && skill.level >= 1 && skill.level <= 5;
}

function normalizeSkill(name) {
  return String(name || '').toLowerCase().replace(/\(.*?\)/g, '').replace(/\s+/g, ' ').trim();
}

function sameSkill(a, b) {
  const x = normalizeSkill(a);
  const y = normalizeSkill(b);
  if (!x || !y) return false;
  if (x === y) return true;
  // Whole-word containment so "C++" matches "Modern C++" but "Go" does not match "Django"
  return (` ${x} `).includes(` ${y} `) || (` ${y} `).includes(` ${x} `);
}

function usesSkill(project, skill) {
  return (project.tech || []).some(t => sameSkill(t, skill));
}

function projectsUsing(skill) {
  return (cv.projects || []).filter(p => usesSkill(p, skill));
}

function initials(name) {
  return String(name || '').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
}

function safeUrl(url) {
  if (!url) return '';
  try {
    const u = new URL(url, window.location.href);
    return ['http:', 'https:', 'mailto:'].includes(u.protocol) ? u.href : '';
  } catch (e) {
    return '';
  }
}

function esc(text) {
  if (text === null || text === undefined) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ---------------------------------------------------------------------------
// Theme toggle (follows the OS setting until the visitor picks one)
// ---------------------------------------------------------------------------
function currentTheme() {
  const explicit = document.documentElement.getAttribute('data-theme');
  if (explicit) return explicit;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function initThemeToggle() {
  const btn = document.getElementById('theme-toggle');
  const paint = () => { btn.innerHTML = currentTheme() === 'dark' ? ICONS.sun : ICONS.moon; };
  paint();
  btn.addEventListener('click', () => {
    const next = currentTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('portfolio-theme', next); } catch (e) {}
    paint();
  });
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', paint);
}
