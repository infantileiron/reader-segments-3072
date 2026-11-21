/** @typedef {{id:number,code:string,weekly_reading:number,completion:number,night_share:number,note:string}} Reader */
/** @typedef {{id:number,name:string,k:number,features:string[],state:string,result:object}} Segment */
/** @typedef {{id:number,segment_id:number,cluster_id:number,title:string,note:string,members:string[],status:string}} Outreach */
/** @typedef {{outreach_id:number,target:number,selected_count:number,satisfaction_rate:number,gap:number,selected_members:string[],candidates:{code:string,selected:boolean,reason:string,detail:string}[]}} SchedulePlanResult */
/** @typedef {{batch_id:number,week_start:string,status:string,preview_token?:string,preview_expires_at?:string,confirmed_at?:string,expired?:boolean,result:{total_selected:number,min_satisfaction_rate:number,cross_candidates:{code:string,outreach_ids:number[]}[],plans:SchedulePlanResult[]}}} ScheduleBatch */
