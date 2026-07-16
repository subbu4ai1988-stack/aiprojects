import { FormEvent, useState } from 'react';
import { ChevronRight, Sparkles } from 'lucide-react';
import { api } from './api';
import Interview from './Interview';
import Recruiter from './Recruiter';
import './phase2.css';

function Login({done}:{done:()=>void}){
  const [error,setError]=useState('');
  async function submit(e:FormEvent<HTMLFormElement>){
    e.preventDefault();
    const data=new FormData(e.currentTarget);
    try{
      const result=await api('/auth/login',{method:'POST',body:JSON.stringify(Object.fromEntries(data))});
      localStorage.setItem('token',result.access_token);done();
    }catch(err){setError((err as Error).message)}
  }
  return <main className="login"><section><div className="brand"><Sparkles/> RecruitAI</div><h1>Hire with signal,<br/>not noise.</h1><p>One intelligent workspace for jobs, candidate matching, interviews, and decisions.</p></section><form onSubmit={submit} className="login-card"><h2>Welcome back</h2><p>Sign in to your recruiting workspace</p><label>Email<input name="email" type="email" defaultValue="recruiter@recruitai.local"/></label><label>Password<input name="password" type="password" defaultValue="recruitai"/></label>{error&&<div className="error">{error}</div>}<button>Sign in <ChevronRight size={17}/></button><small>Local demo credentials are pre-filled.</small></form></main>
}

export default function Phase2App(){
  const interviewToken=location.pathname.startsWith('/interview/')?location.pathname.split('/').pop():null;
  const [logged,setLogged]=useState(!!localStorage.getItem('token'));
  if(interviewToken)return <Interview token={interviewToken}/>;
  if(!logged)return <Login done={()=>setLogged(true)}/>;
  return <Recruiter logout={()=>{localStorage.clear();setLogged(false)}}/>;
}
