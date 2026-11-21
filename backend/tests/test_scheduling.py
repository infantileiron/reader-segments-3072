"""联合排期算法对拍：小规模暴力枚举校验三阶段字典序最优与确定性。

运行：python3 -m tests.test_scheduling
"""
import itertools
import unittest

from src.services.scheduling import solve, monday_of, DUPLICATE, EXCLUDED_OCCUPIED


def brute_force(plans, occupied):
    """枚举所有可行分配，按 (总人数, 最低满足率, 字典序边集合) 取最优。"""
    best = None
    plan_ids = [p['outreach_id'] for p in plans]
    target = {p['outreach_id']: p['target'] for p in plans}
    edges = sorted({(p['outreach_id'], c) for p in plans for c in p['members']
                    if c not in occupied})
    by_member = {}
    for pid, code in edges:
        by_member.setdefault(code, []).append((pid, code))

    def rate(alloc):
        rates = []
        for pid in plan_ids:
            n = sum(1 for p, _ in alloc if p == pid)
            rates.append(n * 100 / target[pid] if target[pid] else 100.0)
        return min(rates)

    # 每个会员：不选 或 选其中一条候选边
    choices = [[None] + opts for opts in by_member.values()]
    for combo in itertools.product(*choices):
        alloc = {e for e in combo if e}
        loads = {pid: 0 for pid in plan_ids}
        for pid, _ in alloc:
            loads[pid] += 1
        if any(loads[pid] > target[pid] for pid in plan_ids):
            continue
        # 并列定序按方案编号（非输入顺序）、会员编号
        key = (len(alloc), rate(alloc),
               tuple(sorted(alloc, key=lambda e: (e[0], e[1]))))
        if best is None or (key[0], key[1]) > (best[0], best[1]) or \
           ((key[0], key[1]) == (best[0], best[1]) and key[2] < tuple(best[2])):
            best = (key[0], key[1], sorted(alloc))
    return best


def make_plans(spec):
    return [{'outreach_id': pid, 'title': f'方案{pid}', 'target': t,
             'members': list(ms)} for pid, t, ms in spec]


class SchedulingTests(unittest.TestCase):
    def test_cross_candidate_one_per_week(self):
        # 两个方案共享会员 b：交叉候选只能入选其一；两案目标各 2，总槽位 4
        plans = make_plans([
            (1, 2, ['a', 'b', 'c']),
            (2, 2, ['b', 'd', 'e']),
        ])
        r = solve(plans, set())
        self.assertEqual(r['total_selected'], 4)
        codes = [m for pl in r['plans'] for m in pl['selected_members']]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue(all(pl['selected_count'] <= pl['target']
                            for pl in r['plans']))
        cross = {x['code']: x['outreach_ids'] for x in r['cross_candidates']}
        self.assertEqual(cross, {'b': [1, 2]})
        # 字典序：方案1优先拿到编号靠前且共享的 b
        self.assertIn('b', r['plans'][0]['selected_members'])
        reasons = {row['code']: row['reason']
                   for row in r['plans'][1]['candidates']}
        self.assertEqual(reasons['b'], DUPLICATE)
        # 目标全满足，缺口为 0
        self.assertTrue(all(pl['gap'] == 0 for pl in r['plans']))

    def test_total_max_uses_all_capacity(self):
        # 容量充足时总入选达到总槽位，共享会员不重复
        plans = make_plans([
            (1, 3, ['a', 'b', 'c']),
            (2, 3, ['b', 'd', 'e', 'f']),
        ])
        r = solve(plans, set())
        self.assertEqual(r['total_selected'], 6)
        codes = [m for pl in r['plans'] for m in pl['selected_members']]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(r['plans'][0]['selected_count'], 3)
        self.assertEqual(r['plans'][1]['selected_count'], 3)

    def test_cannot_meet_target(self):
        # 方案2目标5但候选只有2人：明确缺口，整体仍最大化
        plans = make_plans([
            (1, 3, ['a', 'b', 'c', 'd']),
            (2, 5, ['d', 'e']),
        ])
        r = solve(plans, set())
        self.assertEqual(r['total_selected'], 5)
        p2 = next(p for p in r['plans'] if p['outreach_id'] == 2)
        self.assertEqual(p2['selected_count'], 2)
        self.assertEqual(p2['gap'], 3)
        self.assertEqual(p2['satisfaction_rate'], 40.0)
        self.assertEqual(r['min_satisfaction_rate'], 40.0)
        self.assertEqual(r['min_satisfaction_rate_floor'], 40)

    def test_occupied_members_excluded(self):
        plans = make_plans([
            (7, 3, ['a', 'b', 'c']),
        ])
        r = solve(plans, {'a'})
        self.assertEqual(r['total_selected'], 2)
        row = next(x for x in r['plans'][0]['candidates'] if x['code'] == 'a')
        self.assertEqual(row['reason'], EXCLUDED_OCCUPIED)

    def test_deterministic_tie_break(self):
        # 对称候选：两次结果完全一致，且按方案/会员编号定序
        plans = make_plans([
            (3, 1, ['x', 'y']),
            (4, 1, ['x', 'y']),
        ])
        r1 = solve(plans, set())
        r2 = solve(plans, set())
        self.assertEqual(
            [m for pl in r1['plans'] for m in pl['selected_members']],
            [m for pl in r2['plans'] for m in pl['selected_members']])
        # 方案3编号更靠前，拿到排序第一的 x
        self.assertEqual(r1['plans'][0]['selected_members'], ['x'])
        self.assertEqual(r1['plans'][1]['selected_members'], ['y'])

    def test_brute_force_small_cases(self):
        cases = [
            ([(1, 1, ['a', 'b']), (2, 1, ['b', 'c'])], set()),
            ([(1, 2, ['a', 'b']), (2, 2, ['a', 'b'])], set()),
            ([(1, 3, ['a', 'b']), (2, 1, ['b', 'c', 'd'])], set()),
            ([(1, 1, ['a']), (2, 1, ['a']), (3, 1, ['a', 'b'])], set()),
            ([(5, 2, ['a', 'b', 'c']), (6, 2, ['b', 'c', 'd'])], {'c'}),
            ([(1, 4, ['a', 'b', 'c']), (2, 2, ['c'])], set()),
            ([(2, 1, ['a', 'b']), (1, 1, ['a', 'c'])], set()),  # 乱序方案编号
        ]
        for spec, occupied in cases:
            plans = make_plans(spec)
            r = solve(plans, occupied)
            best = brute_force(plans, occupied)
            self.assertEqual(r['total_selected'], best[0], spec)
            self.assertAlmostEqual(r['min_satisfaction_rate'],
                                   round(best[1], 2), delta=0.01, msg=spec)
            got = sorted((pl['outreach_id'], m)
                         for pl in r['plans'] for m in pl['selected_members'])
            self.assertEqual(got, best[2], spec)

    def test_brute_force_randomized(self):
        import random
        rng = random.Random(3107)
        pool = [f'm{i}' for i in range(8)]
        for _ in range(200):
            n_plans = rng.randint(1, 4)
            spec = []
            for pid in range(1, n_plans + 1):
                ms = rng.sample(pool, rng.randint(1, 5))
                spec.append((pid, rng.randint(1, 5), ms))
            occupied = set(rng.sample(pool, rng.randint(0, 3)))
            plans = make_plans(spec)
            r = solve(plans, occupied)
            best = brute_force(plans, occupied)
            self.assertEqual(r['total_selected'], best[0], spec)
            self.assertAlmostEqual(r['min_satisfaction_rate'],
                                   round(best[1], 2), delta=0.01, msg=spec)
            got = sorted((pl['outreach_id'], m)
                         for pl in r['plans'] for m in pl['selected_members'])
            self.assertEqual(got, best[2], spec)
            # 容量与每周一次不变量
            seen_codes = set()
            for pl in r['plans']:
                self.assertLessEqual(pl['selected_count'], pl['target'])
                for code in pl['selected_members']:
                    self.assertNotIn(code, seen_codes)
                    seen_codes.add(code)

    def test_monday_validation(self):
        from datetime import date
        self.assertEqual(monday_of('2026-11-16'), date(2026, 11, 16))
        with self.assertRaises(ValueError):
            monday_of('2026-11-17')

    def test_realistic_scale_performance(self):
        import time
        # 模拟试点规模：5 个方案、每方案数十名冻结成员、存在交叉
        rng = __import__('random').Random(7)
        pool = [f'SL-{i:03}' for i in range(1, 241)]
        plans = []
        for pid in range(1, 6):
            ms = rng.sample(pool, rng.randint(30, 80))
            plans.append({'outreach_id': pid, 'title': f'p{pid}',
                          'target': rng.randint(20, 60), 'members': ms})
        start = time.time()
        r = solve(plans, set(rng.sample(pool, 20)))
        elapsed = time.time() - start
        self.assertLess(elapsed, 3.0, f'求解耗时 {elapsed:.2f}s 超出预期')
        # 不变量
        seen = set()
        for pl in r['plans']:
            self.assertLessEqual(pl['selected_count'], pl['target'])
            for code in pl['selected_members']:
                self.assertNotIn(code, seen)
                seen.add(code)
        self.assertEqual(r['total_selected'], len(seen))


if __name__ == '__main__':
    unittest.main()
