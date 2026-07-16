import { useEffect, useState } from 'react';
import { CheckCircle2, ExternalLink, Radio, Send } from 'lucide-react';
import { api } from './api';
import type { Job } from './types';
import './phase3.css';

type Posting={id:number;board:string;external_id:string;external_url:string;status:string;posted_at:string};
const BOARDS=[{id:'linkedin',label:'LinkedIn',audience:'Professional network'},{id:'indeed',label:'Indeed',audience:'General talent marketplace'},{id:'glassdoor',label:'Glassdoor',audience:'Employer brand and job search'}];

export default function Distribution({job,close}:{job:Job;close:()=>void}){
  const [selected,setSelected]=useState<string[]>([]);const [postings,setPostings]=useState<Posting[]>([]);const [busy,setBusy]=useState(false);const [notice,setNotice]=useState('');
  useEffect(()=>{api(`/jobs/${job.id}/postings`).then(setPostings)},[job.id]);
  const posted=new Set(postings.map(p=>p.board));
  async function distribute(){setBusy(true);setNotice('');try{const result=await api(`/jobs/${job.id}/postings`,{method:'POST',body:JSON.stringify({boards:selected})});setPostings(await api(`/jobs/${job.id}/postings`));setSelected([]);setNotice(`${result.length} board confirmation${result.length===1?'':'s'} received`)}catch(e){setNotice((e as Error).message)}finally{setBusy(false)}}
  return <div className="modal wide"><section className="modal-panel distribution"><div className="modal-title"><div><p className="eyebrow">Job distribution</p><h2>{job.title}</h2></div><button className="ghost" onClick={close}>Close</button></div><p>Select channels for one-click posting. Local adapters return realistic confirmations without external credentials.</p>{job.status!=='open'&&<div className="warning">Publish this job before distributing it to job boards.</div>}<div className="board-grid">{BOARDS.map(board=><label className={posted.has(board.id)?'posted':''} key={board.id}><input type="checkbox" disabled={posted.has(board.id)||job.status!=='open'} checked={selected.includes(board.id)} onChange={e=>setSelected(x=>e.target.checked?[...x,board.id]:x.filter(id=>id!==board.id))}/><div className="board-icon">{posted.has(board.id)?<CheckCircle2/>:<Radio/>}</div><strong>{board.label}</strong><span>{posted.has(board.id)?'Posted and confirmed':board.audience}</span></label>)}</div>{notice&&<div className="notice">{notice}</div>}<div className="modal-actions"><button disabled={!selected.length||busy||job.status!=='open'} onClick={distribute}><Send/> {busy?'Posting…':`Post to ${selected.length||0} board${selected.length===1?'':'s'}`}</button></div>{postings.length>0&&<><h3>Posting confirmations</h3><div className="posting-list">{postings.map(p=><article key={p.id}><CheckCircle2/><div><strong>{p.board}</strong><span>{p.external_id}</span></div><em>{p.status}</em><a href={p.external_url} target="_blank"><ExternalLink/></a></article>)}</div></>}</section></div>
}
