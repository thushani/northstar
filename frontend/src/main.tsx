import React, { FormEvent, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
const JOB_MATCH_THRESHOLD = 50;
type Resume = { id: number; filename: string; data: { skills: string[] } };
type Job = { id: number; title: string; company: string; location: string; data: { skills: string[]; rawText: string } };
type Qualification = { qualification: string; matched: boolean; evidence?: string | null };
type Analysis = { matchScore: number; fit: string; analysisMode?: 'hybrid' | 'deterministic'; llmStatus?: string; semanticEvidence?: unknown[]; keyStrengths: string[]; skillMatch: { percentage: number; matchedSkills: string[] }; qualificationMatch?: { requiredMatched: number; requiredTotal: number; preferredMatched: number; preferredTotal: number; required: Qualification[]; preferred: Qualification[] }; skillGaps: { totalGaps: number; gaps: string[] }; experienceAlignment: { score: number; detail: string }; insights: { title: string; description: string }[]; interviewQuestions: { question: string; hint: string }[]; nextSteps: { action: string; detail: string; timeline: string }[] };
type ChatMessage = { role: 'user' | 'assistant'; text: string; evidence?: unknown[] };

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || 'Something went wrong. Please try again.');
  }
  return response.json();
}

function roleInitial(job: Job): string {
  return (job.company.trim() || job.title.trim() || 'R').charAt(0).toUpperCase();
}

function roleCompany(job: Job): string {
  return job.company.trim() || 'Company not specified';
}

function App() {
  const [resume, setResume] = useState<Resume | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [analyses, setAnalyses] = useState<Record<string, Analysis>>({});
  const [tab, setTab] = useState<'Overview' | 'Jobs' | 'Insights' | 'Preparation'>('Overview');
  const [activeNav, setActiveNav] = useState<'Overview' | 'Job matches'>('Overview');
  const [showJobForm, setShowJobForm] = useState(false);
  const [editingJob, setEditingJob] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([{ role: 'assistant', text: 'Ask me about your fit, missing skills, or interview preparation.' }]);
  const selectedJob = jobs.find(job => job.id === selectedId) || null;
  const analysis = selectedId ? analyses[String(selectedId)] || null : null;
  const jobMatchCount = Object.values(analyses).filter(item => item.matchScore > JOB_MATCH_THRESHOLD).length;
  const matchedJobs = jobs.filter(job => analyses[String(job.id)]?.matchScore > JOB_MATCH_THRESHOLD);

  function navigate(item: 'Overview' | 'Job matches') {
    setActiveNav(item);
    setTab(item === 'Job matches' ? 'Jobs' : 'Overview');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  useEffect(() => {
    api<{ resume: Resume | null; jobs: Job[]; analyses: Record<string, Analysis> }>('/workspace').then(data => {
      const firstId = data.jobs[0]?.id ?? null;
      setResume(data.resume); setJobs(data.jobs); setSelectedId(firstId); setAnalyses(data.analyses);
    }).catch(() => setError('API unavailable. Start PostgreSQL and the FastAPI server using the README instructions.'));
  }, []);

  async function uploadResume(file?: File) {
    if (!file) return;
    const form = new FormData(); form.append('resume', file);
    setBusy(true); setError('');
    try { setResume(await api<Resume>('/resumes', { method: 'POST', body: form })); setAnalyses({}); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function addJob(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    setBusy(true); setError('');
    try {
      const job = await api<Job>('/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(form)) });
      setJobs(current => [job, ...current]); setSelectedId(job.id); setShowJobForm(false);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function editJob(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedJob) return;
    const form = new FormData(event.currentTarget);
    setBusy(true); setError('');
    try {
      const updated = await api<Job>(`/jobs/${selectedJob.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(form)) });
      setJobs(current => current.map(job => job.id === updated.id ? updated : job));
      setAnalyses(current => { const next = { ...current }; delete next[String(updated.id)]; return next; });
      setEditingJob(false);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function deleteJob() {
    if (!selectedJob) return;
    setBusy(true); setError('');
    try {
      await api<{ deleted: boolean }>(`/jobs/${selectedJob.id}`, { method: 'DELETE' });
      const remaining = jobs.filter(job => job.id !== selectedJob.id);
      setJobs(remaining);
      setAnalyses(current => { const next = { ...current }; delete next[String(selectedJob.id)]; return next; });
      setSelectedId(remaining[0]?.id ?? null);
      setEditingJob(false); setConfirmingDelete(false);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function runAnalysis() {
    if (!resume || !selectedJob) { setError('Upload a resume and add a job description first.'); return; }
    setBusy(true); setError('');
    try { const data = await api<{ analysis: Analysis }>('/analyses', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ resume_id: resume.id, job_id: selectedJob.id }) }); setAnalyses(current => ({ ...current, [String(selectedJob.id)]: data.analysis })); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function runAllAnalyses() {
    if (!resume || !jobs.length) { setError('Upload a resume and add at least one job description first.'); return; }
    setBusy(true); setError('');
    try {
      const data = await api<{ analyses: Record<string, Analysis>; count: number }>('/analyses/batch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ resume_id: resume.id }) });
      setAnalyses(data.analyses);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function ask(event: FormEvent) {
    event.preventDefault(); if (!question.trim() || !resume || !selectedJob) return;
    const text = question.trim(); setQuestion(''); setMessages(current => [...current, { role: 'user', text }]); setBusy(true);
    try {
      const result = await api<{ answer: string; evidence: unknown[] }>('/questions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ resume_id: resume.id, job_id: selectedJob.id, question: text }) });
      setMessages(current => [...current, { role: 'assistant', text: result.answer, evidence: result.evidence }]);
    } catch (e) { setMessages(current => [...current, { role: 'assistant', text: (e as Error).message }]); } finally { setBusy(false); }
  }

  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-mark">N</span><span>northstar</span></div><p className="nav-label">CAREER WORKSPACE</p><nav aria-label="Career workspace">{(['Overview', 'Job matches'] as const).map((item, i) => <button key={item} className={`nav-item ${activeNav === item ? 'active' : ''}`} aria-current={activeNav === item ? 'page' : undefined} onClick={() => navigate(item)}><span>{['⌂', '◎'][i]}</span>{item}{item === 'Job matches' && <b title={`${jobMatchCount} roles with a match score above ${JOB_MATCH_THRESHOLD}%`}>{jobMatchCount}</b>}</button>)}</nav><div className="privacy">Your documents stay in your own database.<br /><strong>Evidence-led analysis</strong></div></aside>
    <main><div className="page"><section className="hero"><div><p className="eyebrow">CAREER INTELLIGENCE</p><h1>Make your next move<br />with clearer evidence.</h1><p>Compare your real experience with the roles you want.</p></div><button className="primary" onClick={runAnalysis} disabled={busy}>{busy ? 'Working…' : 'Analyze selected role →'}</button></section>
      {error && <div className="error" role="alert">{error}</div>}
      {tab !== 'Jobs' && <div className="tabs">{(['Overview', 'Insights', 'Preparation'] as const).map(name => <button className={tab === name ? 'active' : ''} disabled={name === 'Preparation' && !selectedJob} title={name === 'Preparation' && !selectedJob ? 'Select a role to open interview preparation' : undefined} onClick={() => { setTab(name); setActiveNav('Overview'); }} key={name}>{name}</button>)}</div>}
      {tab === 'Overview' && <div className="grid"><section>
        <div className="section-title"><div><h2>Your source material</h2><p>Upload once, compare against many roles.</p></div><label className="link">↑ {resume ? 'Replace resume' : 'Upload resume'}<input type="file" hidden accept=".pdf,.docx,.txt" onChange={e => uploadResume(e.target.files?.[0])} /></label></div>
        <article className="document"><span className="file-icon">CV</span><div><strong>{resume?.filename || 'No resume uploaded'}</strong><small>{resume ? `${resume.data.skills.length} skills found` : 'PDF, DOCX or TXT · max 8 MB'}</small></div><span className={resume ? 'ready' : 'waiting'}>{resume ? '● Ready' : '○ Waiting'}</span></article>
        <div className="section-title roles" id="role-matches"><div><h2>Role matches</h2><p>Select a job to analyze.</p></div><div className="section-actions"><button className="link" onClick={runAllAnalyses} disabled={busy || !resume || !jobs.length}>{busy ? 'Analyzing…' : '✦ Analyze all'}</button><button className="link" onClick={() => setShowJobForm(!showJobForm)}>+ Add role</button></div></div>
        {showJobForm && <form className="job-form" onSubmit={addJob}><div><input name="title" required placeholder="Role title" /><input name="company" placeholder="Company" /></div><input name="location" placeholder="Location / remote" /><textarea name="description" required minLength={30} rows={7} placeholder="Paste the complete job description…" /><div className="form-actions"><button type="button" onClick={() => setShowJobForm(false)}>Cancel</button><button className="primary" disabled={busy}>Save role</button></div></form>}
        <div className="job-list">{jobs.map((job, index) => <button className={`job-card ${job.id === selectedId ? 'selected' : ''}`} onClick={() => { setSelectedId(job.id); setEditingJob(false); setConfirmingDelete(false); }} key={job.id}><span className={`company c${index % 3}`}>{roleInitial(job)}</span><span><strong>{job.title}</strong><small>{roleCompany(job)} · {job.location || 'Not specified'}</small></span><b>{analyses[String(job.id)] ? `${analyses[String(job.id)].matchScore}%` : '—'}</b></button>)}{!jobs.length && <button className="empty" onClick={() => setShowJobForm(true)}>Add your first job description</button>}</div>
      </section><section className="right">
          <article className="score-card">{editingJob && selectedJob ? <form className="job-form edit-form" onSubmit={editJob}><p className="eyebrow">EDIT SELECTED ROLE</p><div><input name="title" required defaultValue={selectedJob.title} /><input name="company" defaultValue={selectedJob.company} /></div><input name="location" defaultValue={selectedJob.location} /><textarea name="description" required minLength={30} rows={9} defaultValue={selectedJob.data.rawText} /><div className="form-actions"><button type="button" onClick={() => setEditingJob(false)}>Cancel</button><button className="primary" disabled={busy}>{busy ? 'Saving…' : 'Save changes'}</button></div></form> : <><div className="selected-job-title"><p className="eyebrow">SELECTED ROLE</p>{selectedJob && <div className="role-actions"><button className="link" onClick={() => { setEditingJob(true); setConfirmingDelete(false); }}>Edit role</button><button className="link danger-link" onClick={() => setConfirmingDelete(true)}>Delete</button></div>}</div><h2>{selectedJob?.title || 'Choose a role'}</h2><p>{selectedJob ? `${roleCompany(selectedJob)} · ${selectedJob.location || 'Not specified'}` : 'Add a job description to begin'}</p>{confirmingDelete && selectedJob && <div className="delete-confirm" role="alert"><span>Delete this role and its analysis?</span><div><button onClick={() => setConfirmingDelete(false)}>Cancel</button><button className="danger" onClick={deleteJob} disabled={busy}>{busy ? 'Deleting…' : 'Yes, delete'}</button></div></div>}<div className="score-body"><div className="score" style={{ '--score': `${analysis?.matchScore || 0}%` } as React.CSSProperties}><div><strong>{analysis?.matchScore ?? '—'}{analysis && '%'}</strong><span>match score</span></div></div><div><strong>{analysis ? `${analysis.fit} fit` : 'Ready when you are'}</strong><p>{analysis ? `${analysis.skillMatch.percentage}% skill alignment based on the supplied resume and role.` : 'Analysis uses explicit skills and experience evidence.'}</p>{analysis && <span className={`analysis-mode ${analysis.analysisMode === 'hybrid' ? 'hybrid' : ''}`}>{analysis.analysisMode === 'hybrid' ? '✦ Hybrid AI + evidence' : 'Evidence analysis'}</span>}</div></div></>}</article>
          <article className="insight"><p className="eyebrow">TOP INSIGHT</p><h3>{analysis?.insights[0]?.title || 'Evidence before assumptions'}</h3><p>{analysis?.insights[0]?.description || 'Upload your resume and add a complete job description for a grounded comparison.'}</p></article>
          <article className="metrics"><div><span>Required</span><strong>{analysis?.qualificationMatch?.requiredTotal ? `${analysis.qualificationMatch.requiredMatched}/${analysis.qualificationMatch.requiredTotal}` : '—'}</strong></div><div><span>Additional</span><strong>{analysis?.qualificationMatch?.preferredTotal ? `${analysis.qualificationMatch.preferredMatched}/${analysis.qualificationMatch.preferredTotal}` : '—'}</strong></div><div><span>Experience</span><strong>{analysis ? `${analysis.experienceAlignment.score}%` : '—'}</strong></div></article>
        </section></div>}
      {tab === 'Jobs' && <section className="jobs-page">
        <div className="jobs-page-head"><div><p className="eyebrow">ROLE LIBRARY</p><h2>Job matches</h2><p>Add and select roles to compare with {resume?.filename || 'your resume'}.</p></div><div className="section-actions"><button className="link analyze-all" onClick={runAllAnalyses} disabled={busy || !resume || !jobs.length}>{busy ? 'Analyzing all…' : '✦ Analyze all roles'}</button><button className="primary" onClick={() => setShowJobForm(!showJobForm)}>+ Add job description</button></div></div>
        {showJobForm && <form className="job-form" onSubmit={addJob}><div><input name="title" required placeholder="Role title" /><input name="company" placeholder="Company" /></div><input name="location" placeholder="Location / remote" /><textarea name="description" required minLength={30} rows={7} placeholder="Paste the complete job description…" /><div className="form-actions"><button type="button" onClick={() => setShowJobForm(false)}>Cancel</button><button className="primary" disabled={busy}>Save role</button></div></form>}
        <div className="jobs-layout"><div className="job-list">{matchedJobs.map((job, index) => <button className={`job-card ${job.id === selectedId ? 'selected' : ''}`} onClick={() => { setSelectedId(job.id); setEditingJob(false); setConfirmingDelete(false); }} key={job.id}><span className={`company c${index % 3}`}>{roleInitial(job)}</span><span><strong>{job.title}</strong><small>{roleCompany(job)} · {job.location || 'Not specified'}</small></span><b>{analyses[String(job.id)] ? `${analyses[String(job.id)].matchScore}%` : 'Not analyzed'}</b></button>)}{!matchedJobs.length && <button className="empty" onClick={() => navigate('Overview')}>No matching jobs yet. Analyze roles in Overview.</button>}</div><article className="selected-job">{editingJob && selectedJob ? <form className="job-form edit-form" onSubmit={editJob}><p className="eyebrow">EDIT ROLE</p><div><input name="title" required defaultValue={selectedJob.title} /><input name="company" defaultValue={selectedJob.company} /></div><input name="location" defaultValue={selectedJob.location} /><textarea name="description" required minLength={30} rows={9} defaultValue={selectedJob.data.rawText} /><div className="form-actions"><button type="button" onClick={() => setEditingJob(false)}>Cancel</button><button className="primary" disabled={busy}>{busy ? 'Saving…' : 'Save changes'}</button></div></form> : <><div className="selected-job-title"><p className="eyebrow">SELECTED ROLE</p>{selectedJob && <div className="role-actions"><button className="link" onClick={() => { setEditingJob(true); setConfirmingDelete(false); }}>Edit role</button><button className="link danger-link" onClick={() => setConfirmingDelete(true)}>Delete</button></div>}</div><h2>{selectedJob?.title || 'No role selected'}</h2><p>{selectedJob ? `${roleCompany(selectedJob)} · ${selectedJob.location || 'Not specified'}` : 'Choose a role from the list.'}</p>{confirmingDelete && selectedJob && <div className="delete-confirm" role="alert"><span>Delete this role and its analysis?</span><div><button onClick={() => setConfirmingDelete(false)}>Cancel</button><button className="danger" onClick={deleteJob} disabled={busy}>{busy ? 'Deleting…' : 'Yes, delete'}</button></div></div>}<div className="chips">{selectedJob?.data.skills.slice(0, 8).map(skill => <span key={skill}>{skill}</span>)}</div><button className="primary" onClick={runAnalysis} disabled={busy || !resume || !selectedJob}>{busy ? 'Analyzing…' : analysis ? 'Analyze again →' : 'Analyze this role →'}</button></>}</article></div>
      </section>}
      {tab === 'Insights' && <section className="detail-grid"><div className="role-context"><div><span>Insights for</span><strong>{selectedJob?.title}</strong><small>{selectedJob ? `${roleCompany(selectedJob)} · ${selectedJob.location || 'Not specified'}` : ''}</small></div>{analysis && <b>{analysis.matchScore}% match</b>}</div>{analysis ? <><article><p className="eyebrow">STRENGTHS</p><h2>What already aligns</h2><div className="chips">{analysis.keyStrengths.map(s => <span key={s}>✓ {s}</span>)}</div></article><article><p className="eyebrow">GAPS</p><h2>What to develop</h2><div className="chips gaps">{analysis.skillGaps.gaps.map(s => <span key={s}>↗ {s}</span>)}</div></article>{analysis.qualificationMatch?.requiredTotal ? <article><p className="eyebrow">REQUIRED QUALIFICATIONS</p><h2>Matches {analysis.qualificationMatch.requiredMatched} of {analysis.qualificationMatch.requiredTotal}</h2><div className="chips">{analysis.qualificationMatch.required.map(item => <span key={item.qualification}>{item.matched ? '✓' : '?'} {item.qualification}</span>)}</div></article> : null}{analysis.qualificationMatch?.preferredTotal ? <article><p className="eyebrow">ADDITIONAL QUALIFICATIONS</p><h2>Matches {analysis.qualificationMatch.preferredMatched} of {analysis.qualificationMatch.preferredTotal}</h2><div className="chips">{analysis.qualificationMatch.preferred.map(item => <span key={item.qualification}>{item.matched ? '✓' : '?'} {item.qualification}</span>)}</div></article> : null}{analysis.nextSteps.map(step => <article key={step.action}><small>{step.timeline}</small><h3>{step.action}</h3><p>{step.detail}</p></article>)}</> : <div className="empty-state">Run an analysis to see evidence-backed strengths, gaps, and next steps.</div>}</section>}
      {tab === 'Preparation' && <div className="prep-grid"><div className="role-context"><div><span>Preparing for</span><strong>{selectedJob?.title}</strong><small>{selectedJob ? `${roleCompany(selectedJob)} · ${selectedJob.location || 'Not specified'}` : ''}</small></div>{analysis && <b>{analysis.matchScore}% match</b>}</div><section className="questions"><p className="eyebrow">INTERVIEW PLAN</p><h2>Questions worth rehearsing</h2>{analysis ? analysis.interviewQuestions.map((item, i) => <article key={item.question}><b>0{i + 1}</b><div><strong>{item.question}</strong><p>{item.hint}</p></div></article>) : <p className="muted">Analyze a role to generate tailored questions.</p>}</section><section className="chat"><p className="eyebrow">ASK NORTHSTAR</p><h2>Explore your fit</h2><div className="messages">{messages.map((m, i) => <div className={m.role} key={i}>{m.text}{m.evidence && m.evidence.length > 0 && <small>Based on {m.evidence.length} document evidence item(s)</small>}</div>)}</div><form onSubmit={ask}><input value={question} onChange={e => setQuestion(e.target.value)} placeholder="What skills am I missing?" disabled={!resume || !selectedJob} /><button disabled={busy || !question.trim()}>↑</button></form></section></div>}
    </div></main>
  </div>;
}

createRoot(document.getElementById('app')!).render(<App />);
