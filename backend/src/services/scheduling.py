"""自然周联合排期：合并多方案冻结成员为候选，每人每周最多入选一次。

优化目标（字典序）：
1. 总入选人数最大化；
2. 在总入选人数不变的前提下，最低目标满足率最大化；
3. 余下并列按方案编号、会员编号确定（确定性结果，可复核）。

只用 Python 标准库。核心是带方案侧容量的二分匹配：把每个方案拆成 target 个
虚拟槽位，退化为普通二分匹配后用 Kuhn 增广路求解；会员侧容量恒为 1。
"""
from datetime import date, datetime, timedelta

PREVIEW_TTL_SECONDS = 600
DUPLICATE = 'duplicate_in_week'
EXCLUDED_OCCUPIED = 'occupied_other_schedule'
TARGET_MET = 'target_met_other_member_priority'
UNSELECTED = 'not_selected'


def monday_of(value):
    """ISO-8601 自然周周一；非周一抛 ValueError。"""
    if isinstance(value, str):
        value = date.fromisoformat(value)
    if value.weekday() != 0:
        raise ValueError('week_start 必须是自然周周一（ISO-8601）')
    return value


class CapacityMatcher:
    """带方案侧容量的二分匹配（会员侧容量恒为 1）。

    把每个方案拆成 capacities[pid] 个虚拟槽位 (pid, k)，退化为标准二分匹配，
    再用 Kuhn 增广路。槽位天然满足容量，会员至多匹配一个槽位，递归改派不会
    让已满方案超额。槽位按 (方案编号, 槽序)、会员按编号排序，结果确定可复核。
    """

    def __init__(self, plan_ids, adjacency, capacities):
        self.plan_ids = plan_ids
        self.adj = adjacency              # pid -> [member 按编号排序]
        self.capacities = capacities
        self.slots = []
        self.slot_plan = {}
        for pid in plan_ids:
            for k in range(capacities.get(pid, 0)):
                slot = (pid, k)
                self.slots.append(slot)
                self.slot_plan[slot] = pid
        self.owner = {}                   # member -> slot

    def _augment(self, slot, seen, banned):
        pid = self.slot_plan[slot]
        for code in self.adj[pid]:
            if code in seen or (pid, code) in banned:
                continue
            seen.add(code)
            holder = self.owner.get(code)
            if holder is None or self._augment(holder, seen, banned):
                self.owner[code] = slot
                return True
        return False

    def run(self, banned=None, fixed=None):
        """fixed/banned 的边以 (pid, code) 表示；fixed 占用各案最前的槽位。

        Kuhn 单轮扫描受槽位顺序影响可能未达最大匹配，故多轮扫描所有"仍空闲"
        的槽位，直到一整轮无任何增广（匹配数不再增长）为止。已被占用的槽位
        不再发起增广，避免重复填充违反容量。返回 (匹配边数, {(pid, code)})。
        """
        banned = banned or set()
        fixed = fixed or set()
        self.owner = {}
        used = {}
        for pid, code in sorted(fixed):
            slot = (pid, used.get(pid, 0))
            used[pid] = used.get(pid, 0) + 1
            self.owner[code] = slot
        progressed = True
        while progressed:
            progressed = False
            occupied_slots = set(self.owner.values())
            for slot in self.slots:
                if slot in occupied_slots:
                    continue
                before = len(self.owner)
                self._augment(slot, set(), banned)
                if len(self.owner) > before:
                    progressed = True
                    occupied_slots = set(self.owner.values())
        edges = {(pid, code) for code, (pid, _k) in self.owner.items()}
        return len(edges), edges

    @property
    def loads(self):
        out = {pid: 0 for pid in self.plan_ids}
        for pid, _k in self.owner.values():
            out[pid] += 1
        return out


def _network(plan_ids, edge_set, capacities, source_caps=None):
    """构造容量匹配器；source_caps 给定时覆盖方案侧容量（用于下界判定）。"""
    caps = dict(capacities) if source_caps is None else dict(source_caps)
    adj = {pid: [] for pid in plan_ids}
    for pid, code in edge_set:
        adj[pid].append(code)
    for pid in adj:
        adj[pid].sort()
    return CapacityMatcher(plan_ids, adj, caps)


def _available_edges(edges, occupied, banned=None, fixed=None):
    """剔除占用/禁用边，并校验 fixed 边合法；返回 (可用边, fixed 会员集合)。"""
    banned = banned or set()
    fixed = fixed or set()
    edge_set = set(edges)
    fixed_members = set()
    for pid, code in fixed:
        if (pid, code) not in edge_set or (pid, code) in banned \
                or code in occupied or code in fixed_members:
            return None
        fixed_members.add(code)
    usable = {(pid, code) for pid, code in edge_set
              if code not in occupied and (pid, code) not in banned}
    return usable, fixed_members


def max_matching(plan_ids, edges, capacities, occupied):
    """阶段一：最大 b 部容量匹配，返回 (最大匹配数, 匹配边集合)。"""
    usable = {(pid, code) for pid, code in edges if code not in occupied}
    if not usable or not plan_ids:
        return 0, set()
    matcher = _network(plan_ids, usable, capacities)
    return matcher.run()


def feasible(plan_ids, edges, capacities, lower, occupied,
             fixed=None, banned=None):
    """固定 fixed、禁用 banned 后，是否存在每方案至少 lower[pid] 的可行分配。"""
    fixed = fixed or set()
    banned = banned or set()
    avail = _available_edges(edges, occupied, banned, fixed)
    if avail is None:
        return False
    usable, fixed_members = avail
    fixed_load = {pid: 0 for pid in plan_ids}
    for pid, _c in fixed:
        fixed_load[pid] += 1
    remaining_lower, need = {}, 0
    for pid in plan_ids:
        rl = lower[pid] - fixed_load[pid]
        if rl < 0 or fixed_load[pid] > capacities[pid]:
            return False
        remaining_lower[pid] = rl
        need += rl
    if need == 0:
        return True
    # 方案侧容量收紧为剩余下界：能全部满足即存在达下界的分配
    remaining_edges = {e for e in usable if e[1] not in fixed_members}
    matcher = _network(plan_ids, remaining_edges, capacities,
                       source_caps=remaining_lower)
    total, _ = matcher.run()
    return total == need


def completion_exists(plan_ids, edges, capacities, lower, occupied,
                      fixed, banned, required_total):
    """固定 fixed、禁用 banned 后，是否存在总人数=required_total 且每方案≥lower。

    两步判定：
    1. 下界可行性：把方案侧容量收紧为"剩余下界"，若能全部满足则下界可达；
    2. 总量可行性：在完整剩余容量上求最大匹配，须达到 required_total-fixed。
    两者独立成立即可组合出既达下界又达总量的分配（先填满下界，再补余量）。
    """
    avail = _available_edges(edges, occupied, banned, fixed)
    if avail is None:
        return False
    usable, fixed_members = avail
    fixed_load = {pid: 0 for pid in plan_ids}
    for pid, _c in fixed:
        fixed_load[pid] += 1
    remaining_caps, remaining_lower = {}, {}
    for pid in plan_ids:
        if fixed_load[pid] > capacities[pid]:
            return False
        remaining_caps[pid] = capacities[pid] - fixed_load[pid]
        remaining_lower[pid] = max(0, lower[pid] - fixed_load[pid])
    need_flow = required_total - len(fixed)
    if need_flow < 0 or need_flow > sum(remaining_caps.values()):
        return False
    remaining_edges = {e for e in usable if e[1] not in fixed_members}
    # 第一步：下界必须可达
    lower_matcher = _network(plan_ids, remaining_edges, capacities,
                             source_caps=remaining_lower)
    lower_flow, _ = lower_matcher.run()
    if lower_flow != sum(remaining_lower.values()):
        return False
    # 第二步：总量必须可达（完整剩余容量下的最大匹配足够大）
    full_matcher = _network(plan_ids, remaining_edges, capacities,
                            source_caps=remaining_caps)
    full_flow, _ = full_matcher.run()
    return full_flow >= need_flow


def _ceil_rate(target, rate):
    if target <= 0:
        return 0
    return -(-target * rate // 100)  # ceil(target*rate/100)


def solve(plans, occupied):
    """三阶段求解，返回完整排期结果字典。

    plans: [{'outreach_id','title','target','members':[code...]}]
    occupied: 本周已被已排期记录占用的会员编号集合
    """
    plan_ids = [p['outreach_id'] for p in plans]
    member_set, edge_set = set(), set()
    target_by, title_by, members_by_plan = {}, {}, {}
    for p in plans:
        pid = p['outreach_id']
        target_by[pid] = p['target']
        title_by[pid] = p['title']
        codes = sorted(set(p['members']))
        members_by_plan[pid] = codes
        for code in codes:
            member_set.add(code)
            edge_set.add((pid, code))
    edges = sorted(edge_set)
    capacities = dict(target_by)
    occupied = set(occupied)

    # 阶段一：总入选人数最大化
    total_max, _ = max_matching(plan_ids, edges, capacities, occupied)

    # 阶段二：固定总入选人数，最大化最低目标满足率（整数阈值，0-100 二分）
    def can_keep_total_with_lower(rate):
        lower = {pid: _ceil_rate(target_by[pid], rate) for pid in plan_ids}
        if sum(lower.values()) > total_max:
            return False
        return feasible(plan_ids, edges, capacities, lower, occupied)

    lo, hi, best_rate = 0, 100, 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if can_keep_total_with_lower(mid):
            best_rate = mid
            lo = mid + 1
        else:
            hi = mid - 1
    lower = {pid: _ceil_rate(target_by[pid], best_rate) for pid in plan_ids}

    # 阶段三：字典序（方案编号升序、案内会员编号升序）贪心构造确定解
    ordered_plans = sorted(plan_ids)
    ordered_edges = [(pid, code) for pid in ordered_plans
                     for code in sorted({c for p, c in edges if p == pid})]
    selected, banned = set(), set()
    loads = {pid: 0 for pid in plan_ids}
    owner = {}
    for pid, code in ordered_edges:
        if code in occupied:
            banned.add((pid, code))
            continue
        if code in owner:
            banned.add((pid, code))            # 每人每周最多一次
            continue
        if loads[pid] >= capacities[pid]:
            banned.add((pid, code))            # 方案目标已满
            continue
        trial = selected | {(pid, code)}
        if not completion_exists(plan_ids, edges, capacities, lower, occupied,
                                 trial, banned, total_max):
            banned.add((pid, code))
            continue
        selected.add((pid, code))
        owner[code] = pid
        loads[pid] += 1

    assert len(selected) == total_max, '阶段三必须保持阶段一的最优总人数'
    assert all(loads[pid] >= lower[pid] for pid in plan_ids), \
        '阶段三必须保持阶段二满足率'

    achieved_rates = [
        round(loads[pid] * 100 / target_by[pid], 2) if target_by[pid] else 100.0
        for pid in plan_ids
    ]
    achieved_min = min(achieved_rates) if achieved_rates else 0.0

    return _assemble(plans, plan_ids, edges, selected, capacities,
                     best_rate, achieved_min, total_max, occupied,
                     title_by, target_by, members_by_plan)


def _assemble(plans, plan_ids, edges, selected, capacities,
              best_rate, achieved_min, total_max, occupied, title_by,
              target_by, members_by_plan):
    selected_by_plan = {pid: [] for pid in plan_ids}
    for pid, code in sorted(selected):
        selected_by_plan[pid].append(code)
    owner = {code: pid for pid, code in selected}
    plan_full = {pid: len(selected_by_plan[pid]) >= capacities[pid]
                 for pid in plan_ids}

    plan_results = []
    for p in plans:
        pid = p['outreach_id']
        chosen = selected_by_plan[pid]
        target = target_by[pid]
        rate = round(len(chosen) * 100 / target, 2) if target else 100.0
        gap = max(0, target - len(chosen))
        rows = []
        for code in members_by_plan[pid]:
            if code in occupied:
                reason, detail = EXCLUDED_OCCUPIED, '本周已在其他已排期记录中冻结'
            elif (pid, code) in selected:
                reason, detail = 'selected', ''
            elif code in owner:
                reason = DUPLICATE
                detail = f"本周名额已给方案#{owner[code]}（每人每周最多入选一次）"
            elif plan_full[pid]:
                reason = TARGET_MET
                detail = '本方案目标人数已由编号更靠前的会员填满'
            else:
                reason, detail = UNSELECTED, '总入选人数最优解下未入选'
            rows.append({'code': code, 'selected': reason == 'selected',
                         'reason': reason, 'detail': detail})
        plan_results.append({
            'outreach_id': pid, 'title': title_by[pid], 'target': target,
            'selected_count': len(chosen), 'satisfaction_rate': rate,
            'gap': gap, 'selected_members': chosen, 'candidates': rows,
        })

    # 交叉候选：出现在多个方案冻结名单中的会员
    code_plans = {}
    for pid, code in edges:
        code_plans.setdefault(code, []).append(pid)
    cross = [{'code': code, 'outreach_ids': sorted(pids)}
             for code, pids in sorted(code_plans.items()) if len(pids) > 1]

    return {
        'total_selected': total_max,
        'min_satisfaction_rate': achieved_min,
        'min_satisfaction_rate_floor': best_rate,
        'cross_candidates': cross,
        'plans': plan_results,
    }


def preview_expires_at(now=None, ttl=PREVIEW_TTL_SECONDS):
    now = now or datetime.now()
    return (now + timedelta(seconds=ttl)).isoformat(timespec='seconds')


def is_preview_expired(record, now=None):
    now = now or datetime.now()
    if record.status != 'preview':
        return False
    return datetime.fromisoformat(record.preview_expires_at) <= now
