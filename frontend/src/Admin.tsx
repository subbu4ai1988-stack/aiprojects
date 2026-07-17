import { FormEvent, useEffect, useState } from 'react';
import { Plus, ShieldCheck, UserCog } from 'lucide-react';
import { api } from './api';
import type { Job } from './types';

type User={id:number;email:string;role:string};

export default function Admin({job,close}:{job?:Job;close:()=>void}){
  const [users,setUsers]=useState<User[]>([]);const [assigned,setAssigned]=useState<number[]>([]);const [notice,setNotice]=useState('');const [error,setError]=useState('');
  const load=async()=>{try{setUsers(await api('/admin/users'));if(job)setAssigned((await api(`/admin/jobs/${job.id}/assignments`)).user_ids)}catch(e){setError((e as Error).message)}};
  useEffect(()=>{load()},[job?.id]);
  async function create(e:FormEvent<HTMLFormElement>){e.preventDefault();const payload=Object.fromEntries(new FormData(e.currentTarget));try{await api('/admin/users',{method:'POST',body:JSON.stringify(payload)});e.currentTarget.reset();setNotice('User created');await load()}catch(err){setError((err as Error).message)}}
  async function saveAssignments(){if(!job)return;await api(`/admin/jobs/${job.id}/assignments`,{method:'PUT',body:JSON.stringify({user_ids:assigned})});setNotice(`Assignments saved for ${job.title}`)}
  return <div className="modal wide"><section className="modal-panel admin-console"><div className="modal-title"><div><p className="eyebrow">Administration</p><h2>User and access management</h2></div><button className="ghost" onClick={close}>Close</button></div>{error?<div className="error access-error"><ShieldCheck/>{error}<small>Sign in as admin@recruitai.local to manage users and assignments.</small></div>:<><div className="admin-grid"><section><h3>Create user</h3><form onSubmit={create}><label>Email<input name="email" type="email" required/></label><label>Temporary password<input name="password" type="password" minLength={8} required/></label><label>Role<select name="role"><option value="recruiter">Recruiter</option><option value="hiring_manager">Hiring manager</option><option value="admin">Administrator</option></select></label><button><Plus/> Create user</button></form></section><section><h3>Active users</h3><div className="user-list">{users.map(user=><article key={user.id}><UserCog/><div><strong>{user.email}</strong><span>{user.role.replace('_',' ')}</span></div></article>)}</div></section></div>{job&&<section className="assignments"><h3>Assign “{job.title}”</h3><p>Assigned recruiters and hiring managers can access this role. Administrators always retain access.</p>{users.filter(u=>u.role!=='admin').map(user=><label key={user.id}><input type="checkbox" checked={assigned.includes(user.id)} onChange={e=>setAssigned(ids=>e.target.checked?[...ids,user.id]:ids.filter(id=>id!==user.id))}/><span>{user.email}</span><em>{user.role.replace('_',' ')}</em></label>)}<button onClick={saveAssignments}>Save assignments</button></section>}{notice&&<div className="notice">{notice}</div>}</>}</section></div>
}

