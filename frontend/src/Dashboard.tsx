import { useEffect, useState } from 'react';
import { BriefcaseBusiness, CheckCircle2, Clock3, Target, Users } from 'lucide-react';
import { api } from './api';
import './phase4.css';

type Metrics={jobs:{total:number;open:number;draft:number};applications:{total:number;stages:Record<string,number>;average_match_score:number};interviews:{total:number;completed:number;in_progress:number};offer_rate:number};

export default function Dashboard({close}:{close:()=>void}){
  const [data,setData]=useState<Metrics>();
  useEffect(()=>{api('/dashboard/metrics').then(setData)},[]);
  if(!data)return <div className="modal wide"><section className="modal-panel">Loading analytics…</section></div>;
  const stages=['applied','screening','interview','offer','rejected'];const max=Math.max(1,...Object.values(data.applications.stages));
  return <div className="modal wide"><section className="modal-panel analytics"><div className="modal-title"><div><p className="eyebrow">Hiring intelligence</p><h2>Recruiting dashboard</h2></div><button className="ghost" onClick={close}>Close</button></div><div className="kpi-grid"><article><BriefcaseBusiness/><span>Open jobs</span><strong>{data.jobs.open}</strong><small>{data.jobs.draft} drafts</small></article><article><Users/><span>Applications</span><strong>{data.applications.total}</strong><small>Across accessible jobs</small></article><article><Target/><span>Average match</span><strong>{data.applications.average_match_score}%</strong><small>Candidate-to-job score</small></article><article><CheckCircle2/><span>Offer rate</span><strong>{data.offer_rate}%</strong><small>Current pipeline</small></article></div><div className="analytics-grid"><section><h3>Hiring funnel</h3><div className="funnel">{stages.map(stage=><div key={stage}><label><span>{stage}</span><b>{data.applications.stages[stage]||0}</b></label><i style={{width:`${Math.max(4,100*(data.applications.stages[stage]||0)/max)}%`}}/></div>)}</div></section><section><h3>Interview activity</h3><div className="interview-stats"><div><Clock3/><strong>{data.interviews.in_progress}</strong><span>In progress</span></div><div><CheckCircle2/><strong>{data.interviews.completed}</strong><span>Completed</span></div><div><Users/><strong>{data.interviews.total}</strong><span>Total interviews</span></div></div></section></div></section></div>
}

