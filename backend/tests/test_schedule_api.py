"""联合排期端到端测试：用 SQLite 内存库跑 FastAPI，覆盖需求的四类验证场景。

运行：PYTHONPATH=. python3 -m tests.test_schedule_api
"""
import os
import unittest
from datetime import date, timedelta

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('JWT_SECRET', 'test-secret-3107')
os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/0')

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.config.database as db_module
from src.config.database import Base
from src.models import entities
from src.models.entities import User, Reader, Outreach, ScheduleBatch, ScheduleItem
from src.utils.security import hash_password, token
from src.routes.api import router
from fastapi import FastAPI


class _FixedEngine:
    def __init__(self, engine):
        self.engine = engine
        self.Session = sessionmaker(bind=engine, expire_on_commit=False)

    def create_all(self):
        Base.metadata.create_all(self.engine)


engine = create_engine(
    'sqlite://',
    connect_args={'check_same_thread': False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=engine, expire_on_commit=False)
Base.metadata.create_all(engine)


def override_db():
    s = TestSession()
    try:
        yield s
    finally:
        s.close()


app = FastAPI()
app.include_router(router)
app.dependency_overrides[db_module.db] = override_db
client = TestClient(app)


def auth_header(user):
    return {'Authorization': f'Bearer {token(user)}'}


class ScheduleApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with TestSession() as s:
            cls.admin = User(email='admin@t.local', role='admin',
                             password=hash_password('x'))
            cls.analyst = User(email='analyst@t.local', role='analyst',
                               password=hash_password('x'))
            cls.viewer = User(email='viewer@t.local', role='viewer',
                              password=hash_password('x'))
            s.add_all([cls.admin, cls.analyst, cls.viewer])
            s.commit()
            for uid in ('cls.admin',):
                pass
            cls.admin_id, cls.analyst_id, cls.viewer_id = \
                cls.admin.id, cls.analyst.id, cls.viewer.id
            # 两个方案，成员有交叉
            cls.o1 = Outreach(segment_id=None, cluster_id=0, title='方案甲',
                              note='x' * 10, members=['SL-001', 'SL-002', 'SL-003'],
                              status='approved')
            cls.o2 = Outreach(segment_id=None, cluster_id=1, title='方案乙',
                              note='y' * 10, members=['SL-002', 'SL-004', 'SL-005'],
                              status='approved')
            s.add_all([cls.o1, cls.o2])
            s.commit()
            cls.o1_id, cls.o2_id = cls.o1.id, cls.o2.id
        # 本周一
        cls.monday = (date.today() - timedelta(days=date.today().weekday())).isoformat()
        cls.next_monday = (date.fromisoformat(cls.monday) + timedelta(days=7)).isoformat()

    def setUp(self):
        with TestSession() as s:
            s.query(ScheduleItem).delete()
            s.query(ScheduleBatch).delete()
            s.commit()

    def _preview(self, plans, week_start=None, user=None):
        user = user or self.analyst
        payload = {'week_start': week_start or self.monday, 'plans': plans}
        return client.post('/schedules/preview', json=payload,
                           headers=auth_header(user))

    def test_preview_does_not_occupy_quota(self):
        r = self._preview([
            {'outreach_id': self.o1_id, 'target': 2},
            {'outreach_id': self.o2_id, 'target': 2},
        ])
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body['status'], 'preview')
        self.assertIn('preview_token', body)
        with TestSession() as s:
            self.assertEqual(s.query(ScheduleItem).count(), 0)
        # 再预览一次，结果应一致（无已占名额）
        r2 = self._preview([
            {'outreach_id': self.o1_id, 'target': 2},
            {'outreach_id': self.o2_id, 'target': 2},
        ])
        self.assertEqual(
            [c for p in r.json()['result']['plans'] for c in p['selected_members']],
            [c for p in r2.json()['result']['plans'] for c in p['selected_members']])

    def test_cross_candidate_and_reasons(self):
        r = self._preview([
            {'outreach_id': self.o1_id, 'target': 3},
            {'outreach_id': self.o2_id, 'target': 3},
        ])
        result = r.json()['result']
        # 交叉候选 SL-002 被识别
        cross = {x['code'] for x in result['cross_candidates']}
        self.assertIn('SL-002', cross)
        # 每人每周最多一次
        all_selected = [c for p in result['plans'] for c in p['selected_members']]
        self.assertEqual(len(all_selected), len(set(all_selected)))
        # 落选原因存在且合理
        reasons = {row['code']: row['reason']
                   for p in result['plans'] for row in p['candidates']}
        self.assertIn('duplicate_in_week', set(reasons.values()))
        # 缺口字段
        for p in result['plans']:
            self.assertEqual(p['gap'], max(0, p['target'] - p['selected_count']))

    def test_cannot_meet_target_shows_gap(self):
        # 方案乙只有3名候选，目标设 5，必然有缺口
        r = self._preview([
            {'outreach_id': self.o2_id, 'target': 5},
        ])
        p = r.json()['result']['plans'][0]
        self.assertEqual(p['selected_count'], 3)
        self.assertEqual(p['gap'], 2)
        self.assertEqual(p['satisfaction_rate'], 60.0)

    def test_confirm_transitions_and_freezes(self):
        prev = self._preview([
            {'outreach_id': self.o1_id, 'target': 2},
            {'outreach_id': self.o2_id, 'target': 2},
        ]).json()
        token_value = prev['preview_token']
        r = client.post('/schedules/confirm', json={'preview_token': token_value},
                        headers=auth_header(self.analyst))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['status'], 'scheduled')
        with TestSession() as s:
            self.assertEqual(
                s.query(ScheduleBatch).filter_by(status='scheduled').count(), 1)
            self.assertGreater(s.query(ScheduleItem).count(), 0)
        # 重复确认被拒
        r2 = client.post('/schedules/confirm', json={'preview_token': token_value},
                         headers=auth_header(self.analyst))
        self.assertEqual(r2.status_code, 409)

    def test_confirmed_quota_participates_in_later_allocation(self):
        # 第一批：方案甲占 2 人
        first = self._preview([
            {'outreach_id': self.o1_id, 'target': 2},
        ]).json()
        client.post('/schedules/confirm',
                    json={'preview_token': first['preview_token']},
                    headers=auth_header(self.analyst))
        first_codes = set(first['result']['plans'][0]['selected_members'])
        # 第二批同周：方案甲已占会员应被排除，方案乙可用
        second = self._preview([
            {'outreach_id': self.o1_id, 'target': 3},
            {'outreach_id': self.o2_id, 'target': 3},
        ]).json()
        with TestSession() as s:
            occupied = {x[0] for x in s.query(ScheduleItem.member_code).all()}
        self.assertEqual(occupied, first_codes)
        for plan in second['result']['plans']:
            for row in plan['candidates']:
                if row['code'] in occupied:
                    self.assertEqual(row['reason'], 'occupied_other_schedule')
            self.assertTrue(
                set(plan['selected_members']).isdisjoint(occupied))

    def test_expired_preview_rejected(self):
        prev = self._preview([
            {'outreach_id': self.o1_id, 'target': 1},
        ]).json()
        # 手动把过期时间改到过去
        with TestSession() as s:
            batch = s.get(ScheduleBatch, prev['batch_id'])
            batch.preview_expires_at = '2000-01-01T00:00:00'
            s.commit()
        r = client.post('/schedules/confirm',
                        json={'preview_token': prev['preview_token']},
                        headers=auth_header(self.analyst))
        self.assertEqual(r.status_code, 410)
        # 没有产生任何排期项
        with TestSession() as s:
            self.assertEqual(s.query(ScheduleItem).count(), 0)

    def test_cross_week_isolation(self):
        # 本周确认一批
        prev = self._preview(
            [{'outreach_id': self.o1_id, 'target': 2}],
            week_start=self.monday).json()
        client.post('/schedules/confirm',
                    json={'preview_token': prev['preview_token']},
                    headers=auth_header(self.analyst))
        # 下周排期不受本周占用影响，相同会员可再次入选
        nxt = self._preview(
            [{'outreach_id': self.o1_id, 'target': 2}],
            week_start=self.next_monday).json()
        self.assertEqual(nxt['result']['plans'][0]['selected_count'], 2)
        r = client.post('/schedules/confirm',
                        json={'preview_token': nxt['preview_token']},
                        headers=auth_header(self.analyst))
        self.assertEqual(r.status_code, 200)
        with TestSession() as s:
            weeks = {w for (w,) in s.query(ScheduleItem.week_start).distinct()}
            self.assertEqual(weeks, {self.monday, self.next_monday})
        # 两周导出各自只含本周名单，互不串数据
        this_week = client.get(f"/schedules/export/{self.monday}",
                               headers=auth_header(self.viewer)).json()
        next_week = client.get(f"/schedules/export/{self.next_monday}",
                               headers=auth_header(self.viewer)).json()
        this_codes = {c for p in this_week['plans'] for c in p['members']}
        next_codes = {c for p in next_week['plans'] for c in p['members']}
        self.assertTrue(this_codes)
        self.assertTrue(next_codes)
        self.assertEqual(this_week['week_start'], self.monday)
        self.assertEqual(next_week['week_start'], self.next_monday)
        # 同一会员可在不同周重复出现（跨周不互斥）
        self.assertTrue(this_codes & next_codes)

    def test_export_only_contains_confirmed_week(self):
        prev = self._preview(
            [{'outreach_id': self.o1_id, 'target': 2}]).json()
        # 未确认时导出 404
        r = client.get(f"/schedules/export/{self.monday}",
                       headers=auth_header(self.viewer))
        self.assertEqual(r.status_code, 404)
        client.post('/schedules/confirm',
                    json={'preview_token': prev['preview_token']},
                    headers=auth_header(self.analyst))
        r = client.get(f"/schedules/export/{self.monday}",
                       headers=auth_header(self.viewer))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['week_start'], self.monday)
        self.assertEqual(data['total_members'], 2)
        self.assertTrue(all('members' in p for p in data['plans']))

    def test_viewer_cannot_preview(self):
        r = self._preview(
            [{'outreach_id': self.o1_id, 'target': 1}], user=self.viewer)
        self.assertEqual(r.status_code, 403)

    def test_invalid_week_start_rejected(self):
        # 周二不是周一
        tuesday = (date.fromisoformat(self.monday) + timedelta(days=1)).isoformat()
        r = self._preview(
            [{'outreach_id': self.o1_id, 'target': 1}], week_start=tuesday)
        self.assertEqual(r.status_code, 422)

    def test_unknown_outreach_rejected(self):
        r = self._preview([{'outreach_id': 99999, 'target': 1}])
        self.assertEqual(r.status_code, 404)

    def test_concurrent_confirm_whole_batch_rejected_and_retry_succeeds(self):
        # 第一次预览并确认，占用方案甲的会员
        first = self._preview([
            {'outreach_id': self.o1_id, 'target': 2},
        ]).json()
        client.post('/schedules/confirm',
                    json={'preview_token': first['preview_token']},
                    headers=auth_header(self.analyst))
        # 另一个预览基于"占用前"的旧状态构造，确认时检测到前提变化应整批拒绝
        stale = self._preview([
            {'outreach_id': self.o1_id, 'target': 2},
        ]).json()
        # 手动制造陈旧预览：其结果假设会员未被占用
        with TestSession() as s:
            batch = s.get(ScheduleBatch, stale['batch_id'])
            batch.result = first['result']  # 与已占用名单重叠
            s.commit()
        conflict = client.post('/schedules/confirm',
                               json={'preview_token': stale['preview_token']},
                               headers=auth_header(self.analyst))
        self.assertEqual(conflict.status_code, 409)
        # 整批拒绝：排期项数量不变，没有重复占用
        with TestSession() as s:
            items = s.query(ScheduleItem).filter_by(
                week_start=self.monday).all()
            codes = [i.member_code for i in items]
            self.assertEqual(len(codes), len(set(codes)))
            self.assertEqual(len(codes), 2)
        # 重新预览（已把已占名额计入）后确认，可成功且不冲突
        fresh = self._preview([
            {'outreach_id': self.o2_id, 'target': 2},
        ]).json()
        ok = client.post('/schedules/confirm',
                         json={'preview_token': fresh['preview_token']},
                         headers=auth_header(self.analyst))
        self.assertEqual(ok.status_code, 200, ok.text)
        with TestSession() as s:
            codes = [i[0] for i in s.query(ScheduleItem.member_code).all()]
            self.assertEqual(len(codes), len(set(codes)))


if __name__ == '__main__':
    unittest.main()
