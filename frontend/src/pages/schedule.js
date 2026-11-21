import {state} from '../stores/session.js';
import {esc} from '../utils/html.js';
import {badge} from '../components/common/status.js';
import {SCHEDULE_REASON} from '../constants/enums.js';

function mondayISO(d=new Date()){
 const x=new Date(d);
 const diff=(x.getDay()+6)%7; // 周一为0
 x.setDate(x.getDate()-diff);
 return x.toISOString().slice(0,10);
}

function planRows(){
 // 表单内动态方案行
 if(!state.outreaches.length)return '<p class="eyebrow">尚无触达方案，请先在“触达方案”页起草并冻结成员。</p>';
 return state.outreaches.map(o=>`
  <div class="plan-row" data-plan-row="${o.id}">
   <span class="plan-name">#${o.id} ${esc(o.title)}（冻结 ${o.members.length} 人）</span>
   <input type="number" min="1" max="10000" data-target="${o.id}" placeholder="目标人数" value="${Math.min(10,o.members.length)}">
   <button type="button" data-remove-plan="${o.id}" class="mini">移除</button>
  </div>`).join('');
}

export function render(){
 const canEdit=state.user.role!=='viewer';
 return `<div class="split">
  <section class="panel">
   <h2>自然周联合排期</h2>
   <p class="notice">合并各触达方案的冻结成员为候选，同一会员每周最多入选一次。先最大化总入选人数，再最大化最低目标满足率，并列时按方案与会员编号确定。预览不占名额，确认后才冻结并参与后续分配。</p>
   <div id="schedule-result"></div>
   <h3 style="margin-top:26px">历史批次</h3>
   ${state.schedules.length?state.schedules.map(batchCard).join(''):'<p>尚无排期批次。</p>'}
  </section>
  <aside class="side">
   <h2>发起联合排期</h2>
   <form id="schedule-preview">
    <label>自然周周一（ISO-8601）<input name="week_start" type="date" value="${mondayISO()}" required></label>
    <label>参与方案与目标人数</label>
    <div id="plan-rows">${planRows()}</div>
    ${canEdit?'<button class="primary">生成预览（不占名额）</button>':'<button disabled>观察员只读</button>'}
   </form>
   <p class="eyebrow" style="margin-top:14px">预览 10 分钟内有效；过期需重新计算。导出仅含该周已确认名单。</p>
  </aside>
 </div>`;
}

function batchCard(b){
 const r=b.result;
 const expired=b.expired?`<span class="tag" style="border-color:var(--accent);color:var(--accent)">已过期</span>`:'';
 return `<article class="rec" data-batch="${b.batch_id}">
  <h3>周 ${esc(b.week_start)} ${badge(b.status)} ${expired}</h3>
  <p>总入选 <strong>${r.total_selected}</strong> 人 · 最低目标满足率 <strong>${r.min_satisfaction_rate}%</strong>
   ${b.confirmed_at?`· 确认于 ${esc(b.confirmed_at)}`:b.preview_expires_at?`· 预览截止 ${esc(b.preview_expires_at)}`:''}</p>
  ${r.cross_candidates.length?`<p class="member-line">交叉候选：${r.cross_candidates.map(c=>`${esc(c.code)}（方案${c.outreach_ids.join('/')}）`).join('；')}</p>`:'<p>无交叉候选。</p>'}
  <div class="scroll"><table>
   <thead><tr><th>方案</th><th>目标</th><th>入选</th><th>满足率</th><th>缺口</th></tr></thead>
   <tbody>${r.plans.map(p=>`<tr><td>#${p.outreach_id} ${esc(p.title)}</td><td>${p.target}</td><td>${p.selected_count}</td><td>${p.satisfaction_rate}%</td><td>${p.gap}</td></tr>`).join('')}</tbody>
  </table></div>
  <div class="batch-actions">
   ${b.status==='preview'&&!b.expired?`<button data-confirm="${esc(b.preview_token)}">确认并冻结名单</button>`:''}
   ${b.status==='scheduled'?`<button data-schedule-export="${esc(b.week_start)}">导出该周确认名单</button>`:''}
   <button type="button" data-detail="${b.batch_id}">查看每案入选/落选原因</button>
  </div>
  <div class="detail" data-detail-panel="${b.batch_id}" hidden>${detailTables(r)}</div>
 </article>`;
}

function detailTables(r){
 return r.plans.map(p=>`<h4 style="margin:14px 0 6px">#${p.outreach_id} ${esc(p.title)}</h4>
  <div class="scroll"><table>
   <thead><tr><th>会员编号</th><th>结果</th><th>原因</th></tr></thead>
   <tbody>${p.candidates.map(c=>`<tr><td>${esc(c.code)}</td><td>${c.selected?'<strong>入选</strong>':'落选'}</td><td>${esc(SCHEDULE_REASON[c.reason]||c.reason)}${c.detail?` <span class="eyebrow">${esc(c.detail)}</span>`:''}</td></tr>`).join('')}</tbody>
  </table></div>`).join('');
}

export function renderPreviewResult(b){
 const el=document.querySelector('#schedule-result');
 if(!el)return;
 el.innerHTML=`<article class="rec" style="border-left:4px solid var(--accent);padding-left:14px">
  <h3>预览结果（未占名额）</h3>
  <p>周 ${esc(b.week_start)} · 总入选 <strong>${b.result.total_selected}</strong> 人 · 最低满足率 <strong>${b.result.min_satisfaction_rate}%</strong></p>
  <div class="scroll"><table>
   <thead><tr><th>方案</th><th>目标</th><th>入选</th><th>满足率</th><th>缺口</th></tr></thead>
   <tbody>${b.result.plans.map(p=>`<tr><td>#${p.outreach_id} ${esc(p.title)}</td><td>${p.target}</td><td>${p.selected_count}</td><td>${p.satisfaction_rate}%</td><td>${p.gap}</td></tr>`).join('')}</tbody>
  </table></div>
  <p class="member-line">入选名单：${b.result.plans.map(p=>`#${p.outreach_id}: ${p.selected_members.map(esc).join('、')||'无'}`).join(' ｜ ')}</p>
  <button class="primary" data-confirm="${esc(b.preview_token)}">确认并冻结名单</button>
 </article>`;
}
