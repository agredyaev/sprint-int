/* Sprint Intelligence · read-only presentation layer. First paint uses manifest bootstrap; canonical detail comes from Parquet. */
import { loadReleaseManifest, openSprintStore } from './data-store.js';
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const escapeHTML = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const href = x => { try { const u = new URL(x); return u.protocol === 'https:' && /\/browse\/|\/jira\//.test(u.pathname) ? escapeHTML(u.href) : '#'; } catch {return '#';} };
  const STATUS = {
    DELIVERED:['Delivered','delivered'],PROGRESSING:['Progressing','progressing'],BLOCKED:['Blocked','blocked'],
    AT_RISK:['At risk','risk'],NO_PROGRESS:['No progress',''],UNKNOWN:['Unknown','']
  };
  const status = code => {
    const [label,cls] = STATUS[code] || STATUS.UNKNOWN;
    const tone=cls || 'neutral';
    return `<span class="status ${tone}">${label}</span>`;
  };
  const arrow = '<svg class="chevron" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m6 8 4 4 4-4" stroke="currentColor" stroke-width="1.25"/></svg>';
  const externalArrow='<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M4 10h11M11 6l4 4-4 4" stroke="currentColor" stroke-width="1.3"/></svg>';
  let current = null, index=[], store=null, filter='ALL', requestedSection=null, scrollFrame=0, sprintRequest=0;
  const metrics = [
    ['material_outcomes','Material outcomes','Customer or strategic','','up','accent'],
    ['blocked_initiatives','Blocked initiatives','Delivery dependencies','','down','blocked'],
    ['at_risk_initiatives','At-risk initiatives','Milestone exposure','','down','risk'],
    ['verified_time_saved_hours','Verified time saved','Automation per sprint','h','up','delivered'],
    ['active_initiatives','Active initiatives','Current portfolio scope','','neutral','neutral'],
    ['automation_delivered','Automation delivered','Confirmed this sprint','','up','delivered']
  ];
  const numeric = x => x == null ? '—' : (Number.isInteger(Number(x)) ? String(x) : Number(x).toFixed(1));
  const metricAmount = (data,k) => data.metrics?.[k] == null ? null : Number(data.metrics[k]);
  function renderBootstrap(b){
    if(!b)return;
    $('.hero .kicker').textContent=`Reporting · Sprint ${b.sprint_id}${b.is_demo?' · DEMO':''}`;
    $('.hero p').textContent=b.executive_summary;
    $('.hero-side-value').textContent=`${b.period_label} · ${b.team}`;
    $('.hero-side-meta').innerHTML=`<span>${numeric(b.active_initiatives)} active initiatives</span><span>${b.reviewed_issues} Jira items reviewed</span>${b.is_demo?'<span>Illustrative data</span>':''}`;
    $('.pulse-main p').textContent=b.pulse;
    $('.attention p').textContent=b.attention || 'No management decision requested this sprint.';
    $('.attention-meta').textContent=b.attention_owner;
    $('.sync').setAttribute('title','Updated '+b.published_at);
    $('.sync').setAttribute('aria-label','Updated '+b.published_at);
  }
  const historyFor = (key, id) => {
    const pos=index.findIndex(x=>x.id===id);
    return index.slice(pos, pos+4).reverse().map(row => ({id:row.id, value: row.metrics?.[key] == null ? null : Number(row.metrics[key])}));
  };
  const smooth = pts => {
    if(pts.length===1) return `M ${pts[0][0]} ${pts[0][1]} L 240 ${pts[0][1]}`;
    return pts.reduce((p,[x,y],i)=> {
      if(!i) return `M ${x.toFixed(1)} ${y.toFixed(1)}`;
      const prev=pts[i-1], before=pts[i-2]||prev, next=pts[i+1]||[x,y];
      const a=prev[0]+(x-before[0])/6, b=prev[1]+(y-before[1])/6;
      const c=x-(next[0]-prev[0])/6, d=y-(next[1]-prev[1])/6;
      return p+` C ${a.toFixed(1)} ${b.toFixed(1)} ${c.toFixed(1)} ${d.toFixed(1)} ${x.toFixed(1)} ${y.toFixed(1)}`;
    },'');
  };
  function plot(values, id) {
    if(values.length<2 || values.some(x=>x.value == null || !Number.isFinite(x.value))) return '';
    const v=values.map(x=>x.value), min=Math.min(...v), max=Math.max(...v);
    const span=Math.max(max-min,1), pts=v.map((y,i)=>[5+(230*i/(v.length-1)), 20+(max-y)/span*75]);
    const curve=smooth(pts), gid='fill-'+id;
    return `<svg viewBox="0 0 240 130" preserveAspectRatio="none" role="img" aria-label="Four-sprint trend: ${v.join(', ')}"><defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="var(--accent-line)" stop-opacity=".11"/><stop offset="1" stop-color="var(--accent-line)" stop-opacity="0"/></linearGradient></defs><path fill="url(#${gid})" d="${curve} L 235 130 L 5 130 Z"/><path d="${curve}" fill="none" stroke="var(--accent-line)" stroke-width="1.35" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>`;
  }
  const arrowFor = diff => diff>0?'↗':diff<0?'↘':'–';
  function renderMetric(data){
    $('.metrics').innerHTML=metrics.map(([key,label,note,unit,better,tone],i)=>{
      const series=historyFor(key,data.sprint.sprint_id), previous=series.length>1?series[series.length-2].value:null;
      const val=metricAmount(data,key), diff=(previous===null || val===null)?null:val-previous;
      const delta=diff===null?(val===null?'Not measured':'No comparable prior value'):diff===0?'No change from previous sprint':`${diff>0?'+':'−'}${numeric(Math.abs(diff))}${unit} from previous sprint`;
      const trend=diff===null||diff===0||better==='neutral'?'neutral':((diff>0)===(better==='up')?'positive':'negative');
      return `<div class="metric metric-tone-${tone}"><div class="metric-content"><span class="metric-label">${label}</span><span class="metric-note">${note}</span><div class="metric-value">${numeric(val)}${unit&&val!==null?`<span class="unit">${unit}</span>`:''}</div><div class="metric-trend trend-${trend}"><span class="metric-trend-icon" aria-hidden="true">${diff===null?'–':arrowFor(diff)}</span><span>${delta}</span></div></div><div class="spark-area">${plot(series,`m${i}`)}</div></div>`;
    }).join('');
  }
  function tasksHTML(epic) {
    if(!epic.tasks?.length)return '';
    return `<div class="tasks-head"><strong>Key Reporting work items · ${epic.tasks.length}</strong><a class="jira-link" href="${href(epic.jira_url)}" target="_blank" rel="noopener noreferrer">Open epic in Jira ↗</a></div><div class="tasks">${epic.tasks.map(t=>`<details class="task"><summary class="task-summary"><div><div class="task-title">${escapeHTML(t.title)}</div><div class="task-key">${escapeHTML(t.jira_key)}</div></div>${status(t.status)}<div class="task-outcome">${escapeHTML(t.outcome)}</div>${arrow}</summary><div class="task-body"><p>${escapeHTML(t.outcome)}</p><a class="jira-link" target="_blank" rel="noopener noreferrer" href="${href(t.jira_url)}">Jira ↗</a></div></details>`).join('')}</div>`;
  }
  function epicHTML(e){
    const risk=e.risk?`<div class="detail-block"><div class="detail-label">Risk / dependency</div><div class="detail-value">${escapeHTML(e.risk)}</div></div>`:'';
    return `<details class="epic" data-key="${escapeHTML(e.jira_key)}" data-status="${escapeHTML(e.status)}" data-category="${escapeHTML(e.category)}"><summary class="epic-summary"><div><div class="project-title">${escapeHTML(e.title)}</div><div class="project-sub">${escapeHTML(e.jira_key)} · ${escapeHTML(e.domain)}</div></div>${status(e.status)}<div class="cell-copy">${escapeHTML(e.delivered)}</div><div class="cell-copy muted">${escapeHTML(e.planned_next)}</div>${arrow}</summary><div class="epic-detail"><div class="detail-grid"><div class="detail-block"><div class="detail-label">Objective</div><div class="detail-value">${escapeHTML(e.objective)}</div></div><div class="detail-block"><div class="detail-label">Verified outcome</div><div class="detail-value">${escapeHTML(e.delivered)}${e.impact?` ${escapeHTML(e.impact)}`:''}</div></div><div class="detail-block"><div class="detail-label">Next</div><div class="detail-value">${escapeHTML(e.planned_next)}</div></div>${risk}</div>${tasksHTML(e)}</div></details>`;
  }
  function renderPortfolio(data){
    const domains=new Map();
    for(const e of data.epics){if(!domains.has(e.domain))domains.set(e.domain,[]);domains.get(e.domain).push(e);}
    const target=$('#portfolioGroups');
    target.innerHTML=[...domains].map(([domain,es])=>`<div class="group" data-domain="${escapeHTML(domain)}"><div class="group-title">${escapeHTML(domain)} <span>${String(es.length).padStart(2,'0')}</span></div>${es.map(epicHTML).join('')}</div>`).join('');
    applyPortfolioFilter();
  }
  function applyPortfolioFilter(){
    const search=$('#search')?.value?.trim().toLowerCase()||'';
    let count=0;
    $$('.group').forEach(g=>{
      let inGroup=0;
      $$('.epic',g).forEach(e=>{
        const code=e.dataset.status;
        const match=(filter==='ALL'||(filter==='ATTENTION'&&['BLOCKED','AT_RISK'].includes(code))||(filter==='DELIVERED'&&code==='DELIVERED'))&&(!search||e.textContent.toLowerCase().includes(search));
        e.classList.toggle('hidden',!match);
        if(match){count++;inGroup++;}
      });
      g.classList.toggle('hidden',!inGroup);
    });
    $('#noResults').classList.toggle('hidden',count>0);
  }
  function renderHighlights(data){
    const es=data.epics.filter(e=>e.highlight_rank!==null&&e.highlight_rank!==undefined).sort((a,b)=>a.highlight_rank-b.highlight_rank);
    $('.highlight-grid').innerHTML=es.length?es.map(e=>`<button type="button" class="highlight" data-open="${escapeHTML(e.jira_key)}"><div class="hl-head"><span class="hl-index">${String(e.highlight_rank).padStart(2,'0')}</span><span class="hl-status ${STATUS[e.status]?.[1]||'neutral'}">${STATUS[e.status]?.[0]||'Unknown'}</span></div><h3>${escapeHTML(e.title)}</h3><p>${escapeHTML(e.delivered)}</p><div class="hl-foot"><span>${escapeHTML(e.domain)}</span>${externalArrow}</div></button>`).join(''):'<p class="section-empty">No material outcomes verified for this sprint.</p>';
    $$('.highlight[data-open]').forEach(b=>b.addEventListener('click',()=>{
      const epic=$$('.epic').find(e=>e.dataset.key===b.dataset.open);
      if(!epic)return;
      $('#search').value='';filter='ALL';$$('.filter').forEach(x=>x.classList.toggle('active',x.dataset.filter==='ALL'));applyPortfolioFilter();
      epic.open=true;requestedSection='#portfolio';syncNav();
      epic.scrollIntoView({block:'center',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
    }));
  }
  function renderDependencies(data){
    $('.dependency-list').innerHTML=data.dependencies.length?data.dependencies.map(d=>`<div class="dep-row"><div><div class="row-title"><a class="jira-link" href="${href(d.jira_url)}" rel="noopener noreferrer" target="_blank">${escapeHTML(d.title)}</a></div><div class="row-sub">${escapeHTML(d.jira_key)} · ${escapeHTML(d.team)}</div></div>${status(d.status)}<div class="row-copy">${escapeHTML(d.impact)}</div><div class="row-copy"><strong>Next:</strong> ${escapeHTML(d.planned_next)}</div></div>`).join(''):'<p class="section-empty">No cross-team dependencies reported.</p>';
  }
  function renderEfficiency(data){
    const values=[
      ['manual_operations','Manual operations','Recurring operational work tracked outside highlights.'],
      ['automation_candidates','Automation candidates','Repeatable opportunities under evaluation.'],
      ['automation_delivered','Automation delivered','Confirmed automation introduced.'],
      ['verified_time_saved_hours','Verified time saved','Observed hours per sprint.']
    ];
    $('.efficiency').innerHTML=values.map(([k,t,sub])=>`<div class="eff"><div class="eff-number">${numeric(metricAmount(data,k))}${k==='verified_time_saved_hours'&&metricAmount(data,k)!==null?'h':''}</div><div class="eff-title">${t}</div><div class="eff-note">${sub}</div></div>`).join('');
  }
  function renderAudit(data){
    const isDemo=!!data.sprint.is_demo;
    $('.audit-state span:last-child').textContent=isDemo?'Sample validation · synthetic data': 'Analysis verified · 5 gates · Sharpwriter complete';
    const gates=[['classification','Classification'],['scope','Reporting / DWH ownership'],['evidence','Jira evidence'],['sharpwriter','Sharpwriter'],['publication','Publication']];
    $('.audit-list').innerHTML=gates.map(([k,label])=>`<div class="audit-row"><span class="audit-icon">✓</span><span class="audit-name">${label}</span><span class="audit-copy">${isDemo?'Example metadata · not a live validation':'Passed · attested by upstream pipeline'}</span></div>`).join('');
    $('.dialog-foot').textContent=isDemo?'Synthetic demonstration data · not a real audit':`Published ${data.sprint.published_at}`;
  }
  function renderPage(data){
    current=data;
    const s=data.sprint;
    $('.hero .kicker').textContent=`Reporting · Sprint ${s.sprint_id}${s.is_demo?' · DEMO':''}`;
    $('.hero p').textContent=s.executive_summary;
    $('.hero-side-value').textContent=`${s.period_label} · ${s.team}`;
    $('.hero-side-meta').innerHTML=`<span>${numeric(metricAmount(data,'active_initiatives'))} active initiatives</span><span>${s.reviewed_issues} Jira items reviewed</span>${s.is_demo?'<span>Illustrative data</span>':''}`;
    $('.pulse-main p').textContent=s.pulse;
    $('.attention p').textContent=s.attention || 'No management decision requested this sprint.';
    $('.attention-meta').textContent=s.attention_owner;
    $('.sync').setAttribute('title','Updated '+s.published_at);
    $('.sync').setAttribute('aria-label','Updated '+s.published_at);
    $('#sprintSelect').value=s.sprint_id;
    renderMetric(data);renderHighlights(data);renderPortfolio(data);renderDependencies(data);renderEfficiency(data);renderAudit(data);
    $('footer').textContent=(s.is_demo?'Synthetic demo data · ':'')+'Jira remains the source of truth · No raw Jira descriptions stored';
    document.body.classList.remove('data-loading');
  }
  async function selectSprint(id){
    const request=++sprintRequest;
    const previous=current?.sprint.sprint_id;
    try {
      const payload=await store.getSprint(id);
      if(request!==sprintRequest)return;
      renderPage(payload);
      const u=new URL(window.location.href);u.searchParams.set('sprint',id);
      history.replaceState(null,'',u);
      $('#loadError').hidden=true;
    } catch(err) {
      if(request!==sprintRequest)return;
      $('#sprintSelect').value=previous||'';
      console.error(err);
      $('#loadError').hidden=false;
      $('#loadError').textContent=`Unable to load sprint ${id}. ${err.message}`;
    }
  }
  async function boot(){
    try {
      const release=await loadReleaseManifest();
      const wanted=new URL(window.location.href).searchParams.get('sprint');
      if(!wanted && release.manifest.bootstrap) renderBootstrap(release.manifest.bootstrap);
      store=await openSprintStore(release);
      index=store.rows;
      const selector=$('#sprintSelect');
      selector.innerHTML=index.map(x=>`<option value="${escapeHTML(x.id)}">${escapeHTML(x.label)}</option>`).join('');
      selector.addEventListener('change',e=>selectSprint(e.target.value));
      await selectSprint(index.some(x=>x.id===wanted)?wanted:index[0].id);
    } catch(err) {
      console.error(err);$('#loadError').hidden=false;
      $('#loadError').textContent='Unable to initialize DuckDB-Wasm or load Parquet. Use HTTP(S) and allow the pinned CDN assets. '+err.message;
      document.body.classList.remove('data-loading');
    }
  }
  $('#search').addEventListener('input',applyPortfolioFilter);
  $$('.filter').forEach(b=>b.addEventListener('click',()=>{
    filter=b.dataset.filter;$$('.filter').forEach(x=>x.classList.toggle('active',x===b));applyPortfolioFilter();
  }));
  const nav=$$('.nav a'),sections=nav.map(a=>$(a.getAttribute('href'))).filter(Boolean);
  function syncNav(){
    const offset=$('.chrome').getBoundingClientRect().height+Math.max(90,Math.min(155,innerHeight*.17));
    let active=sections[0];for(const section of sections){if(section.getBoundingClientRect().top<=offset)active=section;else break;}
    const currentAnchor=requestedSection||`#${active.id}`;
    nav.forEach(a=>{const sel=a.getAttribute('href')===currentAnchor;a.classList.toggle('active',sel);if(sel)a.setAttribute('aria-current','location');else a.removeAttribute('aria-current')});
  }
  function scheduleNav(){if(scrollFrame)return;scrollFrame=requestAnimationFrame(()=>{scrollFrame=0;syncNav()});}
  nav.forEach(a=>a.addEventListener('click',()=>{requestedSection=a.getAttribute('href');syncNav()}));
  ['wheel','touchstart'].forEach(evt=>window.addEventListener(evt,()=>{requestedSection=null;scheduleNav()},{passive:true}));
  window.addEventListener('scroll',scheduleNav,{passive:true});window.addEventListener('resize',scheduleNav,{passive:true});
  window.addEventListener('keydown',e=>{if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(e.key)){requestedSection=null;scheduleNav()}});
  const dlg=$('#auditDialog');
  function dialog(open){dlg.classList.toggle('open',open);dlg.setAttribute('aria-hidden',String(!open));if(open)$('#auditClose').focus()}
  $('#auditOpen').addEventListener('click',()=>dialog(true));$('#auditClose').addEventListener('click',()=>dialog(false));dlg.addEventListener('click',e=>{if(e.target===dlg)dialog(false)});document.addEventListener('keydown',e=>{if(e.key==='Escape')dialog(false)});
  // Supplied Linear reference: explicit Light / Dark / System preference.
  const appearanceToggle=$('#appearance-toggle'),appearanceMenu=$('#appearance-menu');
  let themePreference=document.documentElement.dataset.themePreference||'system';
  const systemAppearance=window.matchMedia('(prefers-color-scheme: dark)');
  const appearanceOptions=$$('[data-appearance]',appearanceMenu);
  function setTheme(p,save=true){
    if(!['light','dark','system'].includes(p))return;
    themePreference=p;const actual=p==='system'?(systemAppearance.matches?'dark':'light'):p;
    document.documentElement.dataset.theme=actual;document.documentElement.dataset.themePreference=p;
    document.querySelector('meta[name="theme-color"]').content=actual==='dark'?'#08090a':'#ffffff';
    appearanceToggle.title='Appearance · '+p;
    appearanceOptions.forEach(x=>x.setAttribute('aria-checked',String(x.dataset.appearance===p)));
    if(save)try{localStorage.setItem('sprint-intelligence-theme',p)}catch{}
  }
  function closeTheme(returnFocus=false){appearanceMenu.hidden=true;appearanceToggle.setAttribute('aria-expanded','false');if(returnFocus)appearanceToggle.focus()}
  function openTheme(){appearanceMenu.hidden=false;appearanceToggle.setAttribute('aria-expanded','true');(appearanceOptions.find(x=>x.dataset.appearance===themePreference)||appearanceOptions[0]).focus()}
  appearanceToggle.addEventListener('click',()=>appearanceMenu.hidden?openTheme():closeTheme(true));
  appearanceOptions.forEach(x=>x.addEventListener('click',()=>{setTheme(x.dataset.appearance);closeTheme(true)}));
  appearanceMenu.addEventListener('keydown',e=>{
    const i=appearanceOptions.indexOf(document.activeElement);
    if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();appearanceOptions[(i+(e.key==='ArrowDown'?1:appearanceOptions.length-1))%appearanceOptions.length].focus()}
    if(e.key==='Escape'){e.preventDefault();closeTheme(true)}
  });
  document.addEventListener('pointerdown',e=>{if(!appearanceMenu.hidden&&!e.target.closest('.appearance-control'))closeTheme()});
  systemAppearance.addEventListener?.('change',()=>{if(themePreference==='system')setTheme('system',false)});
  setTheme(themePreference,false);
  syncNav();boot();
  // Pages deploys a tiny version marker; never poll or download Parquet again.
  let loadedVersion = null;
  const versionURL = './data/version.txt';
  fetch(versionURL, {cache:'no-store'})
    .then(r => r.ok ? r.text() : null)
    .then(v => { loadedVersion = v; })
    .catch(() => {});
  setInterval(async () => {
    if (!loadedVersion || document.hidden) return;
    try {
      const response = await fetch(versionURL, {cache:'no-store'});
      if (response.ok && (await response.text()) !== loadedVersion) window.location.reload();
    } catch { /* Offline browser: do not reload */ }
  }, 60000);
})();
