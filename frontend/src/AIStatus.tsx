import { Cpu, RefreshCw, Sparkles } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from './api';
import './phase5.css';

type Status = {
  requested_provider: string;
  active_provider: 'openai' | 'local';
  configured: boolean;
  model: string;
  embedding_model: string;
  automatic_fallback: boolean;
};

export default function AIStatus() {
  const [status, setStatus] = useState<Status>();
  const [open, setOpen] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = () => {
    setFailed(false);
    api('/ai/status').then(setStatus).catch(() => setFailed(true));
  };

  useEffect(load, []);

  return <div className="ai-status">
    <button className={`ai-status-trigger ${status?.active_provider || 'loading'}`} onClick={() => setOpen(!open)} aria-expanded={open}>
      {status?.active_provider === 'openai' ? <Sparkles/> : <Cpu/>}
      <span>{failed ? 'AI status unavailable' : status ? (status.active_provider === 'openai' ? `OpenAI · ${status.model}` : 'Local AI') : 'Checking AI'}</span>
    </button>
    {open && <section className="ai-status-card">
      <div><span className={`ai-dot ${status?.active_provider}`}/><strong>{status?.active_provider === 'openai' ? 'Production AI active' : 'Local fallback active'}</strong></div>
      {failed ? <p>The backend status endpoint could not be reached.</p> : status && <>
        <p>{status.active_provider === 'openai' ? 'Structured outputs and semantic embeddings are enabled.' : status.requested_provider === 'openai' ? 'OpenAI was requested but no API key is configured.' : 'Set AI_PROVIDER=openai and add an API key to enable production AI.'}</p>
        <dl><dt>Reasoning model</dt><dd>{status.model}</dd><dt>Embeddings</dt><dd>{status.embedding_model}</dd><dt>Fallback</dt><dd>{status.automatic_fallback ? 'Automatic' : 'Disabled'}</dd></dl>
      </>}
      <button className="ai-refresh" onClick={load}><RefreshCw/> Refresh</button>
    </section>}
  </div>;
}
