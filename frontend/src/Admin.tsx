import { FormEvent, useCallback, useEffect, useState } from 'react';
import { Activity, Database, Download, Gauge, LockKeyhole, Plus, ShieldCheck, Trash2, UserCog } from 'lucide-react';
import { api } from './api';
import type { Job } from './types';
import './phase6.css';

type User={id:number;email:string;role:string};
type Runtime={environment:string;database:string;max_upload_mb:number;ai_calls_per_minute:number;ai_monthly_token_budget:number;candidate_retention_days:number;privacy_auto_delete:boolean;storage_provider:string;storage_signed_url_seconds:number;email_provider:string;transcription_provider:string};
type Usage={requests:number;successful:number;fallbacks:number;total_tokens:number;average_duration_ms:number};
type IntegrationActivity={total:number;successful:number;failed:number;by_integration:Record<string,number>};
type PrivacySummary={retention_days:number;automatic_deletion:boolean;total_candidates:number;consented:number;legal_holds:number;overdue:number;expiring_soon:number};
type PrivacyCandidate={candidate_id:number;name:string;email:string;consent_status:string;legal_basis:string;legal_hold:boolean;consent_at:string|null;retention_expires_at:string;days_remaining:number};
type AuditEntry={id:number;actor_email:string;action:string;subject_ref:string;details:Record<string,unknown>;created_at:string};

export default function Admin({job,close}:{job?:Job;close:()=>void}){
  const [users,setUsers]=useState<User[]>([]);
  const [assigned,setAssigned]=useState<number[]>([]);
  const [notice,setNotice]=useState('');
  const [error,setError]=useState('');
  const [runtime,setRuntime]=useState<Runtime>();
  const [usage,setUsage]=useState<Usage>();
  const [integrations,setIntegrations]=useState<IntegrationActivity>();
  const [privacy,setPrivacy]=useState<PrivacySummary>();
  const [privacyCandidates,setPrivacyCandidates]=useState<PrivacyCandidate[]>([]);
  const [audit,setAudit]=useState<AuditEntry[]>([]);

  const load=useCallback(async()=>{
    try{
      setError('');
      const [loadedUsers,loadedRuntime,loadedUsage,loadedIntegrations,loadedPrivacy,loadedCandidates,loadedAudit]=await Promise.all([
        api('/admin/users'),api('/admin/runtime'),api('/admin/ai/usage'),api('/admin/integrations'),api('/admin/privacy/summary'),api('/admin/privacy/candidates'),api('/admin/privacy/audit?limit=12')
      ]);
      setUsers(loadedUsers);setRuntime(loadedRuntime);setUsage(loadedUsage);setIntegrations(loadedIntegrations);setPrivacy(loadedPrivacy);setPrivacyCandidates(loadedCandidates);setAudit(loadedAudit);
      if(job)setAssigned((await api('/admin/jobs/'+job.id+'/assignments')).user_ids);
    }catch(e){setError((e as Error).message)}
  },[job]);
  useEffect(()=>{load()},[load]);

  async function create(e:FormEvent<HTMLFormElement>){
    e.preventDefault();const payload=Object.fromEntries(new FormData(e.currentTarget));
    try{await api('/admin/users',{method:'POST',body:JSON.stringify(payload)});e.currentTarget.reset();setNotice('User created');await load()}catch(err){setError((err as Error).message)}
  }
  async function saveAssignments(){if(!job)return;await api(`/admin/jobs/${job.id}/assignments`,{method:'PUT',body:JSON.stringify({user_ids:assigned})});setNotice(`Assignments saved for ${job.title}`)}
  async function downloadCandidate(candidate:PrivacyCandidate){
    const data=await api(`/admin/privacy/candidates/${candidate.candidate_id}/export`,{method:'POST'});
    const href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=href;link.download=`candidate-${candidate.candidate_id}-export.json`;link.click();URL.revokeObjectURL(href);
    setNotice(`Privacy export created for ${candidate.name}`);await load();
  }
  async function toggleHold(candidate:PrivacyCandidate){
    await api(`/admin/privacy/candidates/${candidate.candidate_id}`,{method:'PUT',body:JSON.stringify({legal_hold:!candidate.legal_hold})});
    setNotice(candidate.legal_hold?'Legal hold removed':'Legal hold applied');await load();
  }
  async function deleteCandidate(candidate:PrivacyCandidate){
    const reason=window.prompt(`Reason for permanently deleting ${candidate.name}?`,'Candidate data deletion request');
    if(!reason)return;
    await api(`/admin/privacy/candidates/${candidate.candidate_id}`,{method:'DELETE',body:JSON.stringify({reason})});
    setNotice(`${candidate.name}'s candidate data was deleted`);await load();
  }
  async function runRetention(dryRun:boolean){
    if(!dryRun&&!window.confirm('Permanently delete every overdue candidate not protected by a legal hold?'))return;
    const result=await api('/admin/privacy/retention/run',{method:'POST',body:JSON.stringify({dry_run:dryRun})});
    setNotice(dryRun?`${result.eligible} candidate(s) eligible for retention deletion`:`${result.deleted} overdue candidate(s) deleted`);await load();
  }

  return <div className="modal wide"><section className="modal-panel admin-console"><div className="modal-title"><div><p className="eyebrow">Administration</p><h2>Access, operations, and privacy</h2></div><button className="ghost" onClick={close}>Close</button></div>
    {runtime&&usage&&<><div className="ops-grid"><article><Database/><span>Database</span><strong>{runtime.database}</strong><small>{runtime.environment}</small></article><article><Activity/><span>AI requests</span><strong>{usage.requests}</strong><small>{usage.successful} successful · {usage.fallbacks} fallback</small></article><article><Gauge/><span>AI tokens</span><strong>{usage.total_tokens.toLocaleString()}</strong><small>{usage.average_duration_ms} ms average</small></article><article><ShieldCheck/><span>Application limit</span><strong>{runtime.ai_calls_per_minute}/min</strong><small>{runtime.ai_monthly_token_budget||'No'} token budget</small></article></div><p className="ops-note">Storage {runtime.storage_provider} · email {runtime.email_provider} · transcription {runtime.transcription_provider} · signed links expire in {runtime.storage_signed_url_seconds}s. {integrations&&<>Recent integration events: {integrations.successful} successful · {integrations.failed} failed.</>}</p></>}
    {error?<div className="error access-error"><ShieldCheck/>{error}<small>Administrator access is required for user and privacy controls.</small></div>:<>
      <div className="admin-grid"><section><h3>Create user</h3><form onSubmit={create}><label>Email<input name="email" type="email" required/></label><label>Temporary password<input name="password" type="password" minLength={8} required/></label><label>Role<select name="role"><option value="recruiter">Recruiter</option><option value="hiring_manager">Hiring manager</option><option value="admin">Administrator</option></select></label><button><Plus/> Create user</button></form></section><section><h3>Active users</h3><div className="user-list">{users.map(user=><article key={user.id}><UserCog/><div><strong>{user.email}</strong><span>{user.role.replace('_',' ')}</span></div></article>)}</div></section></div>
      {job&&<section className="assignments"><h3>Assign “{job.title}”</h3><p>Assigned recruiters and hiring managers can access this role. Administrators always retain access.</p>{users.filter(u=>u.role!=='admin').map(user=><label key={user.id}><input type="checkbox" checked={assigned.includes(user.id)} onChange={e=>setAssigned(ids=>e.target.checked?[...ids,user.id]:ids.filter(id=>id!==user.id))}/><span>{user.email}</span><em>{user.role.replace('_',' ')}</em></label>)}<button onClick={saveAssignments}>Save assignments</button></section>}
      {privacy&&<section className="privacy-section"><div className="privacy-heading"><div><p className="eyebrow">Phase 7</p><h3>Candidate privacy and retention</h3><p>{privacy.retention_days}-day policy · automatic deletion {privacy.automatic_deletion?'enabled':'disabled'}</p></div><div><button className="ghost" onClick={()=>runRetention(true)}>Preview retention</button><button className="danger" disabled={!privacy.overdue} onClick={()=>runRetention(false)}><Trash2/> Delete overdue</button></div></div><div className="privacy-metrics"><article><span>Candidates</span><strong>{privacy.total_candidates}</strong></article><article><span>Consented</span><strong>{privacy.consented}</strong></article><article><span>Expiring in 30 days</span><strong>{privacy.expiring_soon}</strong></article><article><span>Overdue</span><strong>{privacy.overdue}</strong></article><article><span>Legal holds</span><strong>{privacy.legal_holds}</strong></article></div><div className="privacy-table"><div className="privacy-row privacy-labels"><span>Candidate</span><span>Consent</span><span>Retention</span><span>Controls</span></div>{privacyCandidates.map(candidate=><div className="privacy-row" key={candidate.candidate_id}><span><strong>{candidate.name}</strong><small>{candidate.email}</small></span><span><b className={`consent ${candidate.consent_status}`}>{candidate.consent_status}</b><small>{candidate.legal_basis}</small></span><span><strong>{new Date(candidate.retention_expires_at).toLocaleDateString()}</strong><small>{candidate.days_remaining<0?`${Math.abs(candidate.days_remaining)} days overdue`:`${candidate.days_remaining} days remaining`}</small></span><span className="privacy-actions"><button className="icon" title="Export data" onClick={()=>downloadCandidate(candidate)}><Download/></button><button className={`icon ${candidate.legal_hold?'held':''}`} title="Toggle legal hold" onClick={()=>toggleHold(candidate)}><LockKeyhole/></button><button className="icon delete" title="Delete candidate" disabled={candidate.legal_hold} onClick={()=>deleteCandidate(candidate)}><Trash2/></button></span></div>)}{!privacyCandidates.length&&<div className="empty">No candidate personal data is currently stored.</div>}</div><div className="audit-list"><h4>Recent privacy activity</h4>{audit.map(entry=><article key={entry.id}><span>{entry.action.replaceAll('_',' ')}</span><strong>{entry.actor_email}</strong><small>{entry.subject_ref} · {new Date(entry.created_at).toLocaleString()}</small></article>)}{!audit.length&&<p>No privacy actions recorded yet.</p>}</div></section>}
      {notice&&<div className="notice">{notice}</div>}
    </>}
  </section></div>;
}