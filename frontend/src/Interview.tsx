import { useEffect, useRef, useState } from 'react';
import { Camera, CheckCircle2, CircleStop, RefreshCw, Sparkles } from 'lucide-react';
import { api } from './api';
import type { Question } from './types';

function Recorder({token,index,attempts,onUploaded}:{token:string;index:number;attempts:number;onUploaded:(attempts:number)=>void}) {
  const [recording,setRecording]=useState(false);
  const [preview,setPreview]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const media=useRef<MediaRecorder | undefined>(undefined);
  const stream=useRef<MediaStream | undefined>(undefined);
  const live=useRef<HTMLVideoElement>(null);

  async function start(){
    setError('');
    try {
      stream.current=await navigator.mediaDevices.getUserMedia({video:true,audio:true});
      if(live.current) live.current.srcObject=stream.current;
      const chunks:BlobPart[]=[];
      const recorder=new MediaRecorder(stream.current,{mimeType:MediaRecorder.isTypeSupported('video/webm')?'video/webm':undefined});
      recorder.ondataavailable=e=>chunks.push(e.data);
      recorder.onstop=async()=>{
        const blob=new Blob(chunks,{type:recorder.mimeType||'video/webm'});
        setPreview(URL.createObjectURL(blob));
        setBusy(true);
        const form=new FormData();form.append('video',blob,'answer.webm');
        try{const result=await api(`/interviews/${token}/answers/${index}/video`,{method:'POST',body:form});onUploaded(result.recording_attempts)}
        catch(e){setError((e as Error).message)}finally{setBusy(false)}
        stream.current?.getTracks().forEach(t=>t.stop());
      };
      media.current=recorder;recorder.start();setRecording(true);
    } catch { setError('Camera and microphone permission is required.'); }
  }
  function stop(){media.current?.stop();setRecording(false)}
  return <div className="recorder">
    <div className="video-frame">{preview?<video src={preview} controls/>:<video ref={live} autoPlay muted playsInline/>}</div>
    <div className="record-controls">
      {recording?<button type="button" className="danger" onClick={stop}><CircleStop/> Stop recording</button>:<button type="button" className="ghost" disabled={busy||attempts>=2} onClick={start}>{attempts?<RefreshCw/>:<Camera/>}{attempts?'Re-record answer':'Record answer'}</button>}
      <span>{busy?'Uploading…':attempts?`${attempts===1?'One re-record available':'Final recording saved'}`:'Not recorded'}</span>
    </div>{error&&<div className="error">{error}</div>}
  </div>
}

export default function Interview({token}:{token:string}){
  const [session,setSession]=useState<{candidate:string;job:string;questions:Question[];recording_attempts:Record<string,number>}>();
  const [answers,setAnswers]=useState<string[]>([]);const [attempts,setAttempts]=useState<number[]>([]);const [done,setDone]=useState(false);const [error,setError]=useState('');
  useEffect(()=>{api('/interviews/'+token).then(s=>{setSession(s);setAnswers(s.questions.map(()=>''));setAttempts(s.questions.map((_:Question,i:number)=>s.recording_attempts[String(i)]||0))}).catch(e=>setError(e.message))},[token]);
  if(error)return <div className="center error">{error}</div>;if(!session)return <div className="center">Loading interview…</div>;
  if(done)return <div className="center success"><Sparkles/><h1>Interview complete</h1><p>Thank you, {session.candidate}. Your responses were submitted securely.</p></div>;
  return <main className="interview"><header><div className="brand"><Sparkles/> RecruitAI</div><span>{session.job}</span></header><section><p className="eyebrow">One-way video interview</p><h1>Hello, {session.candidate}</h1><p>Record each response and add a transcript or written summary. You may re-record each answer once.</p>{session.questions.map((q,i)=><div className="question" key={i}><span>{i+1} · {q.category} · {q.difficulty}</span><strong>{q.text}</strong><Recorder token={token} index={i} attempts={attempts[i]} onUploaded={count=>setAttempts(a=>a.map((x,j)=>j===i?count:x))}/><textarea value={answers[i]} onChange={e=>setAnswers(a=>a.map((x,j)=>j===i?e.target.value:x))} placeholder="Transcript or written summary…"/></div>)}<button disabled={answers.some(a=>!a.trim())||attempts.some(a=>a<1)} onClick={async()=>{await api('/interviews/'+token+'/answers',{method:'POST',body:JSON.stringify({answers:session.questions.map((q,i)=>({question:q.text,answer:answers[i]}))})});setDone(true)}}><CheckCircle2/> Submit interview</button></section></main>
}

