<template>
  <view class="page">
    <NavBar title="工单审阅" bg-color="#111827" />

    <!-- 分组切换 -->
    <view class="tab-shell">
      <view class="tab-switch">
        <view
          v-for="tab in switchTabs"
          :key="tab.value"
          class="switch-item"
          :class="{ active: activeTab === tab.value }"
          @click="onSwitchTab(tab.value)"
        >
          <text class="switch-label">{{ tab.label }}</text>
          <view v-if="tab.count > 0" class="count-dot">{{ tab.count }}</view>
        </view>
      </view>
    </view>

    <scroll-view scroll-y class="list-area" @scrolltolower="loadMore">
      <view class="section-head">
        <view>
          <text class="section-title">{{ activeTabLabel }}</text>
          <text class="section-note">{{ sectionNote }}</text>
        </view>
      </view>

      <view v-if="activeTab === 'dispatched' && sortedIncidents.length" class="summary-strip">
        <view class="summary-pill">
          <text class="summary-value">{{ dispatchStats.total }}</text>
          <text class="summary-label">已派单</text>
        </view>
        <view class="summary-pill danger">
          <text class="summary-value">{{ dispatchStats.overdue }}</text>
          <text class="summary-label">已超时</text>
        </view>
        <view class="summary-pill warning">
          <text class="summary-value">{{ dispatchStats.warning }}</text>
          <text class="summary-label">临期</text>
        </view>
        <view class="summary-pill active">
          <text class="summary-value">{{ dispatchStats.active }}</text>
          <text class="summary-label">持续异常</text>
        </view>
      </view>

      <view v-if="loading && !incidents.length">
        <view v-for="i in 3" :key="i" class="wo-skeleton" />
      </view>

      <view v-for="incident in sortedIncidents" :key="incident.id" class="wo-wrap">
        <IncidentReviewCard
          :incident="incident"
          mode="operator-review"
          :show-quick-actions="activeTab === 'dispatched'"
          @click="openDetail"
          @action="handleCardAction"
        />

        <!-- 审阅操作（根据状态显示不同按钮） -->
        <view v-if="getActions(incident.workflow_status || '').length" class="action-row">
          <button
            v-for="act in getActions(incident.workflow_status || '')"
            :key="act.action"
            class="action-btn"
            :class="act.style"
            :loading="actionLoading === (incident.current_work_order?.ticket_id || incident.id) + '_' + act.action"
            @click.stop="doAdminAction(incident, act.action, act.confirmTitle)"
          >{{ act.label }}</button>
        </view>
      </view>

      <view v-if="!loading && !incidents.length" class="empty-state">
        <image class="empty-icon" src="/static/icons/tab-workorder.svg" mode="aspectFit" />
        <text>{{ emptyText }}</text>
      </view>

      <view v-if="noMore && incidents.length > 0" class="load-end">没有更多了</view>
    </scroll-view>

    <view v-if="dispatchPanel.visible" class="dispatch-mask" @click="closeDispatchPanel">
      <view class="dispatch-sheet" @click.stop>
        <view class="dispatch-header">
          <view>
            <text class="dispatch-title">{{ dispatchPanel.mode === 'reassign' ? '改派中心' : '派工中心' }}</text>
            <text class="dispatch-subtitle">{{ dispatchPanel.requirement?.summary || '为当前工单选择最合适的维修人员' }}</text>
          </view>
          <text class="dispatch-close" @click="closeDispatchPanel">关闭</text>
        </view>

        <view v-if="dispatchPanel.requirement" class="requirement-strip">
          <view class="req-pill">
            <text class="req-label">楼宇</text>
            <text class="req-value">{{ dispatchPanel.requirement.building_id }}</text>
          </view>
          <view class="req-pill">
            <text class="req-label">优先级</text>
            <text class="req-value">{{ dispatchPanel.requirement.priority }}</text>
          </view>
          <view class="req-pill">
            <text class="req-label">建议班组</text>
            <text class="req-value">{{ dispatchPanel.requirement.preferred_team_name }}</text>
          </view>
        </view>

        <view class="requirement-tags">
          <text
            v-for="skill in dispatchPanel.requirement?.required_skills || []"
            :key="skill"
            class="requirement-tag"
          >{{ requirementSkillText(skill) }}</text>
        </view>

        <scroll-view scroll-y class="dispatch-list">
          <view
            v-for="candidate in dispatchPanel.candidates"
            :key="candidate.user_id"
            class="candidate-card"
          >
            <view class="candidate-top">
              <view>
                <text class="candidate-name">{{ candidate.username }}</text>
                <text class="candidate-meta">{{ candidateMeta(candidate) }}</text>
              </view>
              <view class="score-pill">
                <text class="score-label">推荐分</text>
                <text class="score-value">{{ candidate.score }}</text>
              </view>
            </view>

            <view class="candidate-stats">
              <text class="candidate-stat">值班：{{ shiftText(candidate.shift_status) }}</text>
              <text class="candidate-stat">负载：{{ candidate.current_active_orders }}/{{ candidate.max_active_orders }}</text>
              <text class="candidate-stat">匹配技能：{{ candidate.matched_skill_names?.length || 0 }}</text>
            </view>

            <view class="badge-row">
              <text v-for="badge in candidate.badges" :key="badge" class="badge-chip">{{ badge }}</text>
            </view>

            <view v-if="candidate.skill_names?.length" class="extra-row">
              <text class="extra-label">技能</text>
              <text class="extra-value">{{ candidate.skill_names.join(' / ') }}</text>
            </view>
            <view v-if="candidate.service_buildings?.length" class="extra-row">
              <text class="extra-label">覆盖楼宇</text>
              <text class="extra-value">{{ candidate.service_buildings.join(' / ') }}</text>
            </view>

            <text class="candidate-reason">{{ candidate.recommend_reason }}</text>

            <button
              class="dispatch-submit"
              :loading="dispatchSubmitting === candidate.user_id"
              @click="confirmDispatch(candidate)"
            >{{ dispatchPanel.mode === 'reassign' ? '改派给TA' : '派给TA' }}</button>
          </view>

          <view v-if="!dispatchPanel.candidates.length" class="dispatch-empty">
            暂无可用候选人
          </view>
        </scroll-view>
      </view>
    </view>

    <TabBar :tabs="OPERATOR_TABS" current="workorders" theme="operator" />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import IncidentReviewCard from '../../../components/IncidentReviewCard.vue'
import { useRouteGuard } from '../../../utils/route-guard'
import { OPERATOR_TABS } from '../../../constants/tabs'
import { OPERATOR_ROLES } from '../../../constants/roles'
import type { AdminAction } from '../../../constants/status'
import { workOrderApi, type DispatchCandidate, type DispatchRequirement } from '../../../api/workorder'
import { incidentApi, type Incident } from '../../../api/incident'
import { getCache, setCache } from '../../../utils/cache'
import { getDispatchSortScore, getDispatchSummaryStats } from '../../../utils/incident-card'

useRouteGuard(OPERATOR_ROLES)

type OperatorAction = AdminAction | 'dispatch' | 'reassign'
interface ActionDef { action: OperatorAction; label: string; style: string; confirmTitle: string }
interface DispatchPanelState {
  visible: boolean
  ticketId: string | null
  incidentId: string | null
  dispatchId: string | null
  mode: 'dispatch' | 'reassign'
  requirement: DispatchRequirement | null
  candidates: DispatchCandidate[]
}

// 对齐后端 admin-review 的 action 枚举
function getActions(status: string): ActionDef[] {
  switch (status) {
    case 'pending_dispatch':
    case 'auto_approved':
      return [{ action: 'dispatch', label: '立即派工', style: 'approve', confirmTitle: '选择维修人员并完成派工' }]
    case 'dispatched':
      return [{ action: 'reassign', label: '改派', style: 'neutral', confirmTitle: '为当前工单选择新的维修人员' }]
    case 'auto_rejected':
      return [{ action: 'override_approve', label: '转待派工', style: 'approve', confirmTitle: '确认覆盖AI决策，将工单转入待派工？' }]
    case 'completed':
    case 'false_alarm':
      return [{ action: 'confirm', label: '确认关闭', style: 'neutral', confirmTitle: '确认关闭此工单？' }]
    case 'escalated':
      return [{ action: 'close_escalated', label: '关闭升级', style: 'neutral', confirmTitle: '确认关闭此升级工单？' }]
    default:
      return []
  }
}

const switchTabs = ref([
  { label: '待审阅',     value: 'pending_review', count: 0 },
  { label: '待派工',     value: 'pending_dispatch', count: 0 },
  { label: 'AI已驳回',   value: 'auto_rejected',  count: 0 },
  { label: '已派单',     value: 'dispatched',     count: 0 },
  { label: '待关闭',     value: 'completed,false_alarm,escalated', count: 0 },
])

const activeTab = ref('pending_dispatch')
const incidents = ref<Incident[]>([])
const loading = ref(false)
const noMore = ref(false)
const actionLoading = ref<string | null>(null)
const dispatchSubmitting = ref<string | null>(null)
const page = ref(1)
const PAGE_SIZE = 15
const dispatchPanel = ref<DispatchPanelState>({
  visible: false,
  ticketId: null,
  incidentId: null,
  dispatchId: null,
  mode: 'dispatch',
  requirement: null,
  candidates: [],
})

const emptyText = computed(() => {
  const map: Record<string, string> = {
    pending_review: '暂无待审阅事件',
    pending_dispatch: '暂无待派工工单',
    auto_rejected: '暂无AI已驳回工单',
    dispatched: '暂无已派单工单',
  }
  return map[activeTab.value] ?? '暂无工单'
})

const activeTabLabel = computed(() => {
  return switchTabs.value.find(tab => tab.value === activeTab.value)?.label || '事件列表'
})

const currentTabCount = computed(() => {
  return switchTabs.value.find(tab => tab.value === activeTab.value)?.count || incidents.value.length
})

const sortedIncidents = computed(() => {
  if (activeTab.value !== 'dispatched') return incidents.value
  return [...incidents.value].sort((a, b) => getDispatchSortScore(b) - getDispatchSortScore(a))
})

const dispatchStats = computed(() => getDispatchSummaryStats(sortedIncidents.value))

const sectionNote = computed(() => {
  if (activeTab.value === 'dispatched') {
    return `共 ${currentTabCount.value} 条事件，按超时风险与处理优先级排序`
  }
  return `共 ${currentTabCount.value} 条事件，按最近异常时间倒序展示`
})

async function loadData() {
  const cacheKey = `workorders_${activeTab.value}`
  const cached = getCache<Incident[]>(cacheKey)
  if (cached) incidents.value = cached
  loading.value = !cached
  page.value = 1
  noMore.value = false
  try {
    const res = await incidentApi.list({
      workflow_status: activeTab.value,
      page: 1,
      page_size: PAGE_SIZE,
    })
    incidents.value = res.incidents
    setCache(cacheKey, res.incidents)
    if (res.incidents.length < PAGE_SIZE) noMore.value = true
    await loadCounts()
  } catch { /* handled */ }
  finally { loading.value = false }
}

async function loadCounts() {
  const statuses = ['pending_review', 'pending_dispatch', 'auto_rejected', 'dispatched', 'completed,false_alarm,escalated']
  await Promise.allSettled(
    statuses.map(async (s, i) => {
      const res = await incidentApi.list({ workflow_status: s, page: 1, page_size: 1 })
      switchTabs.value[i].count = res.total
    })
  )
}

async function loadMore() {
  if (loading.value || noMore.value) return
  page.value++
  try {
    const res = await incidentApi.list({ workflow_status: activeTab.value, page: page.value, page_size: PAGE_SIZE })
    incidents.value.push(...res.incidents)
    if (res.incidents.length < PAGE_SIZE) noMore.value = true
  } catch { page.value-- }
}

function onSwitchTab(val: string) { activeTab.value = val; loadData() }

function shiftText(status?: string) {
  const map: Record<string, string> = {
    on_duty: '值班中',
    standby: '待命',
    off_duty: '离岗',
  }
  return map[status || ''] || '值班中'
}

function requirementSkillText(skill: string) {
  const map: Record<string, string> = {
    hvac: '暖通空调',
    electrical: '电气配电',
    plumbing: '给排水',
    controls: '楼宇自控',
    inspection: '现场巡检',
  }
  return map[skill] || skill
}

function candidateMeta(candidate: DispatchCandidate) {
  return [candidate.team_name || '综合运维班', candidate.job_title || '维修工程师'].join(' · ')
}

function closeDispatchPanel() {
  if (dispatchSubmitting.value) return
  dispatchPanel.value = {
    visible: false,
    ticketId: null,
    incidentId: null,
    dispatchId: null,
    mode: 'dispatch',
    requirement: null,
    candidates: [],
  }
}

async function openDispatchPanel(incident: Incident, ticketId: string, mode: 'dispatch' | 'reassign' = 'dispatch') {
  const result = await workOrderApi.dispatchCandidates(ticketId)
  dispatchPanel.value = {
    visible: true,
    ticketId,
    incidentId: incident.id,
    dispatchId: incident.current_dispatch?.id || null,
    mode,
    requirement: result.requirement,
    candidates: result.candidates,
  }
}

async function confirmDispatch(candidate: DispatchCandidate) {
  if (!dispatchPanel.value.ticketId) return
  dispatchSubmitting.value = candidate.user_id
  try {
    if (dispatchPanel.value.mode === 'reassign' && dispatchPanel.value.dispatchId) {
      await workOrderApi.reassignDispatchTask(
        dispatchPanel.value.dispatchId,
        candidate.user_id,
        `调度改派：${candidate.recommend_reason}`,
      )
      uni.showToast({ title: `已改派给${candidate.username}`, icon: 'success' })
    } else {
      await workOrderApi.dispatch(
        dispatchPanel.value.ticketId,
        candidate.user_id,
        candidate.recommend_reason,
      )
      uni.showToast({ title: `已派给${candidate.username}`, icon: 'success' })
    }
    incidents.value = incidents.value.filter(item => item.id !== dispatchPanel.value.incidentId)
    dispatchSubmitting.value = null
    closeDispatchPanel()
    await loadCounts()
  } catch {
    uni.showToast({ title: '派工失败', icon: 'none' })
  } finally {
    dispatchSubmitting.value = null
  }
}

function openDetail(incident: Incident) {
  const ticketId = incident.current_work_order?.ticket_id
  if (!ticketId) return
  uni.navigateTo({ url: `/pages/worker/workorder-detail/index?incident_id=${incident.incident_id}&ticket_id=${ticketId}&readonly=1` })
}

function handleCardAction(payload: { type: 'trend' | 'contact' | 'nudge' | 'detail'; incident: Incident }) {
  const { type, incident } = payload
  if (type === 'trend' || type === 'detail') {
    openDetail(incident)
    return
  }

  if (type === 'contact') {
    const phone = incident.current_work_order?.assigned_phone
    if (!phone) {
      uni.showToast({ title: '暂无责任人联系方式', icon: 'none' })
      return
    }
    uni.makePhoneCall({ phoneNumber: phone })
    return
  }

  if (type === 'nudge') {
    const assignee = incident.current_work_order?.assigned_to_name || '责任人'
    uni.showToast({ title: `已催办${assignee}`, icon: 'none' })
  }
}

async function doAdminAction(incident: Incident, action: OperatorAction, confirmTitle: string) {
  const ticketId = incident.current_work_order?.ticket_id
  if (!ticketId) return
  const key = ticketId + '_' + action
  actionLoading.value = key

  if (action === 'dispatch') {
    try {
      await openDispatchPanel(incident, ticketId, 'dispatch')
      if (!dispatchPanel.value.candidates.length) {
        uni.showToast({ title: '暂无可派工维修人员', icon: 'none' })
        closeDispatchPanel()
        return
      }
      actionLoading.value = null
      return
    } catch {
      uni.showToast({ title: '候选人加载失败', icon: 'none' })
      actionLoading.value = null
      return
    }
  }

  if (action === 'reassign') {
    try {
      await openDispatchPanel(incident, ticketId, 'reassign')
      if (!dispatchPanel.value.candidates.length) {
        uni.showToast({ title: '暂无可派工维修人员', icon: 'none' })
        closeDispatchPanel()
        return
      }
      actionLoading.value = null
      return
    } catch {
      uni.showToast({ title: '候选人加载失败', icon: 'none' })
      actionLoading.value = null
      return
    }
  }

  uni.showModal({
    title: '操作确认',
    content: confirmTitle,
    confirmColor: action.includes('reject') ? '#ff4d4f' : '#3b6cf4',
    async success(res) {
      if (!res.confirm) { actionLoading.value = null; return }
      try {
        await workOrderApi.adminReview(ticketId, action)
        uni.showToast({ title: '操作成功', icon: 'success' })
        incidents.value = incidents.value.filter(item => item.id !== incident.id)
        await loadCounts()
      } catch { /* handled */ }
      finally { actionLoading.value = null }
    },
    fail() { actionLoading.value = null },
  })
}

onMounted(loadData)
</script>

<style lang="scss" scoped>
.page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background:
    radial-gradient(circle at top right, rgba(74, 222, 128, 0.1), transparent 24%),
    #eef2f8;
}

.tab-shell {
  margin: 20rpx 24rpx 6rpx;
  position: relative;
  z-index: 1;
}

.tab-switch {
  display: flex;
  background: #fff;
  border: 1rpx solid rgba(225,231,240,0.9);
  border-radius: 24rpx;
  padding: 8rpx;
  box-shadow: 0 10rpx 30rpx rgba(20, 32, 58, 0.08);
}

.switch-item {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  height: 76rpx;
  color: #7d8797;
  position: relative;
  border-radius: 18rpx;
  &.active {
    color: #1d4ed8;
    font-weight: 700;
    background: linear-gradient(135deg, #eef4ff, #ffffff);
    box-shadow: inset 0 0 0 1rpx rgba(97, 139, 255, 0.18);
  }
}

.switch-label {
  font-size: 24rpx;
}

.count-dot {
  background: linear-gradient(135deg, #ff5d73, #ff7a5c);
  color: #fff;
  border-radius: 999rpx;
  font-size: 18rpx;
  padding: 3rpx 10rpx;
  min-width: 34rpx;
  text-align: center;
  box-shadow: 0 6rpx 16rpx rgba(255, 93, 115, 0.28);
}

.list-area {
  flex: 1;
  min-height: 0;
  height: auto;
  box-sizing: border-box;
  padding: 22rpx 24rpx calc(env(safe-area-inset-bottom, 0px) + 140rpx);
}

.section-head {
  padding: 10rpx 6rpx 18rpx;
}

.section-title {
  display: block;
  font-size: 28rpx;
  font-weight: 800;
  color: #1b2433;
  margin-bottom: 6rpx;
}

.section-note {
  display: block;
  font-size: 22rpx;
  color: #7d8797;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12rpx;
  margin: 0 0 18rpx;
}

.summary-pill {
  background: #ffffff;
  border: 1rpx solid rgba(226, 232, 240, 0.95);
  border-radius: 20rpx;
  padding: 18rpx 14rpx;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
  box-shadow: 0 10rpx 24rpx rgba(15, 23, 42, 0.05);

  &.danger {
    background: #fff4f3;
    border-color: #ffd8d3;
  }

  &.warning {
    background: #fff7e8;
    border-color: #ffe0b2;
  }

  &.active {
    background: #eefcf7;
    border-color: #d6f2e6;
  }
}

.summary-value {
  font-size: 30rpx;
  line-height: 1;
  font-weight: 800;
  color: #1f2937;
}

.summary-label {
  font-size: 20rpx;
  color: #6b7280;
}

.wo-wrap { margin-bottom: 8rpx; }

.action-row {
  display: flex;
  gap: 16rpx;
  margin-top: -4rpx;
  padding: 0 6rpx 16rpx;
}

.action-btn {
  flex: 1;
  height: 72rpx;
  border-radius: 16rpx;
  font-size: 24rpx;
  font-weight: 700;
  border: none;
  box-shadow: 0 10rpx 22rpx rgba(16, 24, 40, 0.06);
  &.approve { background: linear-gradient(135deg, #12b76a, #16c47f); color: #fff; }
  &.danger  { background: #fff2f0; color: #ff4d4f; }
  &.neutral { background: #eef4ff; color: #2f6df6; }
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 140rpx 0;
  gap: 16rpx;
  color: #97a2b4;
  font-size: 28rpx;
  .empty-icon { width: 88rpx; height: 88rpx; opacity: 0.42; }
}

.load-end { text-align: center; font-size: 24rpx; color: #a5afbf; padding: 20rpx; }

.wo-skeleton {
  height: 252rpx;
  background: linear-gradient(90deg, #f6f8fb, #eef2f7, #f6f8fb);
  border-radius: 28rpx;
  margin-bottom: 20rpx;
}

.dispatch-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.34);
  display: flex;
  align-items: flex-end;
  z-index: 30;
}

.dispatch-sheet {
  width: 100%;
  max-height: 78vh;
  border-radius: 36rpx 36rpx 0 0;
  background:
    radial-gradient(circle at top right, rgba(59, 130, 246, 0.08), transparent 22%),
    #fff;
  padding: 26rpx 24rpx calc(env(safe-area-inset-bottom, 0px) + 24rpx);
  box-sizing: border-box;
  box-shadow: 0 -18rpx 40rpx rgba(15, 23, 42, 0.14);
}

.dispatch-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18rpx;
}

.dispatch-title {
  display: block;
  font-size: 32rpx;
  font-weight: 800;
  color: #162033;
}

.dispatch-subtitle {
  display: block;
  margin-top: 8rpx;
  font-size: 22rpx;
  line-height: 1.6;
  color: #6b7280;
}

.dispatch-close {
  padding: 10rpx 0 10rpx 18rpx;
  font-size: 24rpx;
  color: #2563eb;
}

.requirement-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12rpx;
  margin-top: 20rpx;
}

.req-pill {
  border-radius: 20rpx;
  background: #f8fbff;
  border: 1rpx solid rgba(59, 130, 246, 0.12);
  padding: 16rpx 14rpx;
}

.req-label {
  display: block;
  font-size: 20rpx;
  color: #7d8797;
}

.req-value {
  display: block;
  margin-top: 6rpx;
  font-size: 24rpx;
  font-weight: 700;
  color: #1f2937;
}

.requirement-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
  margin-top: 14rpx;
}

.requirement-tag {
  padding: 8rpx 14rpx;
  border-radius: 999rpx;
  background: #eef4ff;
  color: #2563eb;
  font-size: 20rpx;
}

.dispatch-list {
  max-height: 50vh;
  margin-top: 18rpx;
}

.candidate-card {
  border-radius: 26rpx;
  border: 1rpx solid rgba(226, 232, 240, 0.95);
  padding: 20rpx;
  margin-bottom: 16rpx;
  background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
}

.candidate-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16rpx;
}

.candidate-name {
  display: block;
  font-size: 30rpx;
  font-weight: 800;
  color: #182235;
}

.candidate-meta {
  display: block;
  margin-top: 6rpx;
  font-size: 22rpx;
  color: #7b8797;
}

.score-pill {
  min-width: 108rpx;
  border-radius: 18rpx;
  padding: 12rpx 14rpx;
  background: #eff7ff;
  text-align: center;
}

.score-label {
  display: block;
  font-size: 18rpx;
  color: #6b7280;
}

.score-value {
  display: block;
  margin-top: 4rpx;
  font-size: 30rpx;
  font-weight: 800;
  color: #2563eb;
}

.candidate-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx 18rpx;
  margin-top: 16rpx;
}

.candidate-stat {
  font-size: 22rpx;
  color: #5b6576;
}

.badge-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
  margin-top: 16rpx;
}

.badge-chip {
  padding: 8rpx 14rpx;
  border-radius: 999rpx;
  background: #f5f7fb;
  color: #5a6475;
  font-size: 20rpx;
}

.extra-row {
  display: flex;
  gap: 12rpx;
  margin-top: 14rpx;
}

.extra-label {
  flex-shrink: 0;
  font-size: 22rpx;
  color: #7b8797;
}

.extra-value {
  flex: 1;
  font-size: 22rpx;
  color: #2a3445;
  line-height: 1.6;
}

.candidate-reason {
  display: block;
  margin-top: 14rpx;
  font-size: 22rpx;
  line-height: 1.7;
  color: #4b5563;
}

.dispatch-submit {
  margin-top: 18rpx;
  height: 74rpx;
  border-radius: 18rpx;
  border: none;
  background: linear-gradient(135deg, #2563eb, #3b82f6);
  color: #fff;
  font-size: 24rpx;
  font-weight: 700;
}

.dispatch-empty {
  text-align: center;
  padding: 90rpx 0 70rpx;
  color: #94a3b8;
  font-size: 24rpx;
}

@media (max-width: 430px) {
  .summary-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .requirement-strip {
    grid-template-columns: 1fr;
  }
}
</style>
