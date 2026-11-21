"""联合排期的持久化与并发控制。

规则：
- 预览不占名额，10 分钟过期；过期预览不可确认，需重新计算。
- 确认在单事务内完成：行锁锁定本周已排期会员，重算校验后写入，整批成功或整批拒绝。
- 并发确认若名额被占（唯一约束或锁内重算冲突），整批回滚并要求重算，重试不重复占用。
- 已排期名额参与后续同周分配；跨周的 schedule_items 互不影响。
"""
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from src.models.entities import Outreach, ScheduleBatch, ScheduleItem
from src.services.scheduling import (
    solve, monday_of, preview_expires_at, is_preview_expired,
)


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _load_plans(s, plan_inputs):
    """加载方案并冻结其成员副本；方案不存在或成员为空则 422。"""
    plans = []
    for item in plan_inputs:
        outreach = s.get(Outreach, item.outreach_id)
        if not outreach:
            raise HTTPException(404, f'触达方案#{item.outreach_id}不存在')
        members = list(outreach.members or [])
        if not members:
            raise HTTPException(422, f'方案#{item.outreach_id}没有冻结成员，无法排期')
        plans.append({
            'outreach_id': outreach.id,
            'title': outreach.title,
            'target': item.target,
            'members': members,
        })
    return plans


def _occupied_codes(s, week_start):
    """本周已排期（已确认）占用的会员编号。"""
    rows = s.query(ScheduleItem.member_code).filter_by(week_start=week_start).all()
    return {r[0] for r in rows}


def create_preview(s, data):
    """生成预览；不写入任何 schedule_item，不占名额。"""
    week_start = monday_of(data.week_start).isoformat()
    plans = _load_plans(s, data.plans)
    occupied = _occupied_codes(s, week_start)
    result = solve(plans, occupied)
    token = secrets.token_urlsafe(32)
    batch = ScheduleBatch(
        week_start=week_start,
        status='preview',
        result=result,
        preview_token=token,
        preview_expires_at=preview_expires_at(),
    )
    s.add(batch)
    s.commit()
    return _preview_payload(batch)


def _preview_payload(batch):
    return {
        'batch_id': batch.id,
        'week_start': batch.week_start,
        'status': batch.status,
        'preview_token': batch.preview_token,
        'preview_expires_at': batch.preview_expires_at,
        'result': batch.result,
    }


def get_preview(s, token):
    batch = s.query(ScheduleBatch).filter_by(preview_token=token).first()
    if not batch:
        raise HTTPException(404, '预览不存在或已失效，请重新排期')
    if batch.status == 'scheduled':
        raise HTTPException(409, '该预览已确认，请勿重复提交')
    if is_preview_expired(batch):
        raise HTTPException(410, '预览已过期，请重新计算后再确认')
    return batch


def confirm_preview(s, token, current_user, audit):
    """确认预览：事务内加锁、重算、整批写入。

    并发下依赖 SELECT 行锁与 (week_start, member_code) 唯一约束双重保护：
    任一会员名额被其他事务占用即 IntegrityError，整批回滚并返回 409 要求重算。
    """
    batch = get_preview(s, token)
    week_start = batch.week_start
    try:
        # 锁定本周已有排期项，串行化同周并发确认
        existing = s.query(ScheduleItem).filter_by(
            week_start=week_start).with_for_update().all()
        locked_codes = {item.member_code for item in existing}

        # 用当前最新冻结名单与已占名额重算，确保预览后数据变化可被发现
        plan_ids = [p['outreach_id'] for p in batch.result['plans']]
        target_by = {p['outreach_id']: p['target']
                     for p in batch.result['plans']}
        plan_inputs = [_PlanRef(oid, target_by[oid]) for oid in plan_ids]
        plans = _load_plans(s, plan_inputs)
        fresh = solve(plans, locked_codes)

        if not _same_selection(fresh, batch.result):
            s.rollback()
            raise HTTPException(409, '排期前提已变化（名单或名额变动），请重新预览后再确认')

        items = []
        for plan in fresh['plans']:
            for code in plan['selected_members']:
                items.append(ScheduleItem(
                    batch_id=batch.id,
                    week_start=week_start,
                    outreach_id=plan['outreach_id'],
                    member_code=code,
                ))
        s.add_all(items)
        batch.status = 'scheduled'
        batch.confirmed_at = _now_iso()
        # 确认后结果以最新重算为准，保留落选原因与缺口展示
        batch.result = fresh
        s.flush()
        s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, '确认时名额已被其他批次占用，整批未写入，请重新计算后重试')
    audit(s, current_user, f'确认联合排期批次#{batch.id}（周{week_start}）')
    return _scheduled_payload(batch)


class _PlanRef:
    def __init__(self, outreach_id, target):
        self.outreach_id = outreach_id
        self.target = target


def _same_selection(fresh, stored):
    """重算结果与预览的入选边集合必须一致，否则视为前提变化。"""
    def edges(result):
        return sorted((p['outreach_id'], code)
                      for p in result['plans']
                      for code in p['selected_members'])
    return edges(fresh) == edges(stored)


def _scheduled_payload(batch):
    return {
        'batch_id': batch.id,
        'week_start': batch.week_start,
        'status': batch.status,
        'confirmed_at': batch.confirmed_at,
        'result': batch.result,
    }


def list_batches(s):
    rows = s.query(ScheduleBatch).order_by(
        ScheduleBatch.week_start.desc(), ScheduleBatch.id.desc()).all()
    out = []
    for b in rows:
        expired = b.status == 'preview' and is_preview_expired(b)
        payload = _preview_payload(b) if b.status == 'preview' \
            else _scheduled_payload(b)
        payload['expired'] = expired
        out.append(payload)
    return out


def week_export(s, week_start):
    """导出只含该周已确认名单；未确认或无数据则 409/404。"""
    monday_of(week_start)
    batch = s.query(ScheduleBatch).filter_by(
        week_start=week_start, status='scheduled').first()
    if not batch:
        raise HTTPException(404, '该自然周尚无已确认排期，无法导出')
    items = s.query(ScheduleItem).filter_by(week_start=week_start).all()
    by_plan = {}
    for item in items:
        by_plan.setdefault(item.outreach_id, []).append(item.member_code)
    return {
        'week_start': week_start,
        'batch_id': batch.id,
        'confirmed_at': batch.confirmed_at,
        'total_members': len(items),
        'plans': [
            {
                'outreach_id': pid,
                'members': sorted(codes),
                'member_count': len(codes),
            }
            for pid, codes in sorted(by_plan.items())
        ],
    }
