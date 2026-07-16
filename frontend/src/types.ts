export type Job = {id:number;title:string;department:string;location:string;description:string;status:string;ranking_params:Record<string,unknown>};
export type Candidate = {application_id:number;name:string;email:string;status:string;interview_status:string|null;match_score:number;summary:string;skills:string[]};
export type Question = {text:string;category:string;difficulty:string};
export type InterviewSetup = {token:string;url:string;questions:Question[];status:string};
export type Feedback = {report:string;recommendation:string;confidence_score:number;answers:Array<{question:string;answer:string;video_url?:string}>};

