<template>
  <view class="page">
    <NavBar title="工单审阅" bg-color="#111827" />

    <!-- 分组切换 -->
    <view class="tab-shell">
      <view class="tab-shell-head">
        <text class="tab-shell-title">状态筛选</text>
        <text class="tab-shell-hint">左右滑动切换</text>
      </view>
      <scroll-view
        scroll-x
        class="tab-switch-scroll"
        :show-scrollbar="false"
        :scroll-into-view="activeTabScrollId"
        :scroll-with-animation="true"
      >
        <view class="tab-switch">
          <view
            v-for="(tab, index) in switchTabs"
            :id="`operator-tab-${index}`"
            :key="tab.value"
            class="switch-item"
            :class="{ active: activeTab === tab.value }"
            @click="onSwitchTab(tab.value)"
          >
            <text class="switch-label">{{ tab.label }}</text>
            <view v-if="tab.count > 0" class="count-dot">{{ formatTabCount(tab.count) }}</view>
          </view>
        </view>
      </scroll-view>
    </view>

    <scroll-view scroll-y class="list-area" @scrolltolower="loadMore">
      <view class="section-head">
        <view>
          <text class="section-title">{{ activeTabLabel }}</text>
          <text class="section-note">{{ sectionNote }}</text>
        </view>
        <button
          v-if="activeTab === 'pending_dispatch'"
          class="section-action-btn"
          :loading="batchPreviewLoading"
          @click="openBatchDispatchPanel"
        >批量推荐</button>
      </view>

      <view v-if="activeTab === 'pending_dispatch' && currentTabCount" class="pending-batch-strip">
        <view class="summary-pill">
          <text class="summary-value">{{ currentTabCount }}</text>
          <text class="summary-label">待派工</text>
        </view>
        <view class="summary-pill warning">
          <text class="summary-value">{{ pendingHighPriorityCount }}</text>
          <text class="summary-label">高优先</text>
        </view>
        <view class="summary-pill active">
          <text class="summary-value">{{ pendingBuildingCount }}</text>
          <text class="summary-label">涉及楼宇</text>
        </view>
      </view>

      <view v-if="activeTab === 'pending_dispatch' && incidents.length" class="track-filter-row">
        <view
          v-for="item in pendingPriorityFilters"
          :key="item.value"
          class="track-filter-chip"
          :class="{ active: pendingPriorityFilter === item.value }"
          @click="pendingPriorityFilter = item.value"
        >
          <text class="track-filter-label">{{ item.label }}</text>
          <text v-if="item.count > 0" class="track-filter-count">{{ item.count }}</text>
        </view>
      </view>

      <view
        v-if="activeTab === 'pending_dispatch' && pendingBuildingFilters.length > 1"
        class="track-filter-row track-filter-row--secondary"
      >
        <view
          v-for="item in pendingBuildingFilters"
          :key="item.value"
          class="track-filter-chip track-filter-chip--building"
          :class="{ active: pendingBuildingFilter === item.value }"
          @click="pendingBuildingFilter = item.value"
        >
          <text class="track-filter-label">{{ item.label }}</text>
          <text v-if="item.count > 0" class="track-filter-count">{{ item.count }}</text>
        </view>
      </view>

      <view v-if="activeTab === 'dispatched' && visibleIncidents.length" class="summary-strip">
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

      <view v-if="activeTab === 'dispatched' && incidents.length" class="track-filter-row">
        <view
          v-for="item in dispatchExecutionFilters"
          :key="item.value"
          class="track-filter-chip"
          :class="{ active: dispatchExecutionFilter === item.value }"
          @click="dispatchExecutionFilter = item.value"
        >
          <text class="track-filter-label">{{ item.label }}</text>
          <text v-if="item.count > 0" class="track-filter-count">{{ item.count }}</text>
        </view>
      </view>

      <view v-if="activeTab === 'shared_hall' && hallEntries.length" class="summary-strip hall-summary-strip">
        <view class="summary-pill">
          <text class="summary-value">{{ hallEntryCount }}</text>
          <text class="summary-label">共享事项</text>
        </view>
        <view class="summary-pill active">
          <text class="summary-value">{{ hallSupportCount }}</text>
          <text class="summary-label">协同事项</text>
        </view>
        <view class="summary-pill warning">
          <text class="summary-value">{{ hallTakeoverCount }}</text>
          <text class="summary-label">待接管</text>
        </view>
        <view class="summary-pill danger">
          <text class="summary-value">{{ hallPendingApplicationCount }}</text>
          <text class="summary-label">待处理申请</text>
        </view>
      </view>

      <view v-if="loading && showEmptySkeleton">
        <view v-for="i in 3" :key="i" class="wo-skeleton" />
      </view>

      <view v-if="activeTab === 'shared_hall'">
        <view v-for="entry in hallEntries" :key="entry.id" class="hall-wrap">
          <view class="hall-card">
            <view class="hall-card-head">
              <view class="hall-badge-row">
                <text class="hall-type-badge" :class="entry.entry_type === 'support_request' ? 'support' : 'takeover'">
                  {{ hallEntryTypeLabel(entry) }}
                </text>
                <text class="hall-priority-badge">{{ priorityText(entry.work_order?.priority) }}</text>
              </view>
              <text class="hall-time">{{ formatDateTime(entry.created_at) }}</text>
            </view>

            <text class="hall-title">{{ hallEntryTitle(entry) }}</text>
            <text class="hall-location">{{ hallEntryBuilding(entry) }} / {{ hallEntryLocation(entry) }}</text>

            <view class="hall-detail-panel">
              <view class="hall-detail-line">
                <text class="hall-detail-label">工单编号</text>
                <text class="hall-detail-value">{{ entry.work_order?.ticket_id || '--' }}</text>
              </view>
              <view class="hall-detail-line">
                <text class="hall-detail-label">主责任人</text>
                <text class="hall-detail-value">{{ hallEntryOwner(entry) }}</text>
              </view>
              <view class="hall-detail-line">
                <text class="hall-detail-label">进入原因</text>
                <text class="hall-detail-value multiline">{{ hallEntryReason(entry) }}</text>
              </view>
            </view>

            <view class="hall-section-head">
              <text class="hall-section-title">待处理申请</text>
              <text class="hall-section-note">{{ hallPendingApplications(entry).length }} 条</text>
            </view>

            <view v-if="hallPendingApplications(entry).length" class="hall-application-list">
              <view
                v-for="application in hallPendingApplications(entry)"
                :key="application.id"
                class="hall-application-card"
              >
                <view class="hall-application-top">
                  <view>
                    <text class="hall-application-name">{{ application.applicant_username || '维修人员' }}</text>
                    <text class="hall-application-meta">{{ applicationTypeLabel(application) }} · {{ formatDateTime(application.created_at) }}</text>
                  </view>
                  <text class="hall-application-status">待处理</text>
                </view>
                <text v-if="application.note" class="hall-application-note">{{ application.note }}</text>
                <view class="hall-application-actions">
                  <button
                    class="hall-mini-btn approve"
                    :loading="actionLoading === buildHallActionKey(entry.id, application.id, 'approve')"
                    @click.stop="approveHallApplication(entry, application)"
                  >同意</button>
                  <button
                    class="hall-mini-btn danger"
                    :loading="actionLoading === buildHallActionKey(entry.id, application.id, 'reject')"
                    @click.stop="rejectHallApplication(entry, application)"
                  >驳回</button>
                </view>
              </view>
            </view>

            <view v-else class="hall-application-empty">
              <text>{{ hallEmptyHint(entry) }}</text>
            </view>

            <view class="hall-bottom-actions">
              <button class="hall-secondary-btn" @click.stop="openHallDetail(entry)">查看详情</button>
              <button
                v-if="canSuggestHallTakeover(entry)"
                class="hall-secondary-btn"
                :loading="actionLoading === buildHallActionKey(entry.id, '', 'suggest')"
                @click.stop="openHallReassignSuggestion(entry)"
              >改派建议</button>
              <button
                v-if="canNudgeHallOwner(entry)"
                class="hall-secondary-btn"
                :loading="actionLoading === buildHallActionKey(entry.id, '', 'nudge')"
                @click.stop="nudgeHallOwner(entry)"
              >催办责任人</button>
              <button
                class="hall-secondary-btn danger"
                :loading="actionLoading === buildHallActionKey(entry.id, '', 'close')"
                @click.stop="closeHallEntry(entry)"
              >关闭共享事项</button>
            </view>
          </view>
        </view>
      </view>

      <view v-else v-for="incident in visibleIncidents" :key="incident.id" class="wo-wrap">
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

      <view v-if="!loading && showEmptyState" class="empty-state">
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

    <view v-if="batchDispatchPanel.visible" class="dispatch-mask" @click="closeBatchDispatchPanel">
      <view class="dispatch-sheet batch-sheet" @click.stop>
        <view class="dispatch-header">
          <view>
            <text class="dispatch-title">批量派工建议</text>
            <text class="dispatch-subtitle">
              {{ batchDispatchPanel.preview?.selected_count ? `已筛出 ${batchDispatchPanel.preview.selected_count} 张高置信工单` : '按优先级与推荐分生成批量派工建议' }}
            </text>
          </view>
          <text class="dispatch-close" @click="closeBatchDispatchPanel">关闭</text>
        </view>

        <view class="batch-config-box">
          <text class="section-title section-title--small">分批策略</text>

          <view class="batch-config-group">
            <text class="batch-config-label">本批次张数</text>
            <view class="batch-config-row">
              <view
                v-for="size in batchSampleOptions"
                :key="size"
                class="batch-config-chip"
                :class="{ active: batchDispatchOptions.sampleSize === size }"
                @click="selectBatchSampleSize(size)"
              >{{ size }} 张</view>
            </view>
          </view>

          <view class="batch-config-group">
            <text class="batch-config-label">优先级范围</text>
            <view class="batch-config-row">
              <view
                v-for="item in batchPriorityOptions"
                :key="item.value"
                class="batch-config-chip"
                :class="{ active: batchDispatchOptions.priority === item.value }"
                @click="selectBatchPriority(item.value)"
              >{{ item.label }}</view>
            </view>
          </view>

          <view class="batch-config-group">
            <text class="batch-config-label">单人批次上限</text>
            <view class="batch-config-row">
              <view
                v-for="count in batchWorkerCapOptions"
                :key="count"
                class="batch-config-chip"
                :class="{ active: batchDispatchOptions.maxPerWorker === count }"
                @click="selectBatchWorkerCap(count)"
              >{{ count }} 张</view>
            </view>
          </view>

          <button class="batch-refresh-btn" :loading="batchPreviewLoading" @click="refreshBatchDispatchPreview">刷新推荐</button>
        </view>

        <view v-if="batchDispatchPanel.preview" class="requirement-strip">
          <view class="req-pill">
            <text class="req-label">待派工总量</text>
            <text class="req-value">{{ batchDispatchPanel.preview.pending_dispatch_total }}</text>
          </view>
          <view class="req-pill">
            <text class="req-label">本次扫描</text>
            <text class="req-value">{{ batchDispatchPanel.preview.scanned_count }}</text>
          </view>
          <view class="req-pill">
            <text class="req-label">已选推荐</text>
            <text class="req-value">{{ batchDispatchPanel.preview.selected_count }}</text>
          </view>
          <view class="req-pill">
            <text class="req-label">单人上限</text>
            <text class="req-value">{{ batchDispatchPanel.preview.selection_rules.max_per_worker || '--' }}</text>
          </view>
        </view>

        <view
          v-if="batchDispatchPanel.preview?.planned_assignments?.length"
          class="batch-planned-strip"
        >
          <view
            v-for="item in batchDispatchPanel.preview?.planned_assignments || []"
            :key="item.user_id"
            class="batch-planned-pill"
          >
            <text class="batch-planned-name">{{ item.username }}</text>
            <text class="batch-planned-count">+{{ item.count }}</text>
          </view>
        </view>

        <view
          v-if="batchWorkerLoads.length"
          class="batch-load-box"
        >
          <text class="section-title section-title--small">当前负载与本批次分配</text>
          <view
            v-for="item in batchWorkerLoads"
            :key="item.user_id"
            class="batch-load-row"
          >
            <view>
              <text class="batch-load-name">{{ item.username }}</text>
              <text class="batch-load-meta">{{ item.team_name || '综合运维班' }} · {{ shiftText(item.shift_status || undefined) }}</text>
            </view>
            <view class="batch-load-values">
              <text class="batch-load-stat">当前 {{ item.current_active_orders }}/{{ item.max_active_orders }}</text>
              <text v-if="item.planned_count > 0" class="batch-load-stat accent">本批 +{{ item.planned_count }}</text>
              <text class="batch-load-stat">余量 {{ item.capacity_left_after_batch }}</text>
            </view>
          </view>
        </view>

        <view
          v-if="batchDispatchPanel.result"
          class="batch-result-box"
        >
          <view class="batch-result-head">
            <view>
              <text class="section-title section-title--small">本轮批量派工结果</text>
              <text class="batch-result-note">
                请求 {{ batchDispatchPanel.result.requested_count }} 张，成功 {{ batchDispatchPanel.result.dispatched_count }} 张，失败 {{ batchDispatchPanel.result.failed_count }} 张
              </text>
            </view>
            <button
              v-if="retryableBatchFailures.length"
              class="batch-result-retry"
              :loading="batchDispatchApplying"
              @click="retryBatchFailedItems"
            >重试 {{ retryableBatchFailures.length }} 张</button>
          </view>

          <view
            v-for="item in batchDispatchPanel.result.failed"
            :key="`${item.ticket_id}_${item.reason_code}`"
            class="batch-result-row"
          >
            <view class="batch-result-top">
              <view>
                <text class="batch-skip-ticket">{{ item.ticket_id }}</text>
                <text class="batch-skip-meta">
                  {{ item.current_status ? `当前状态 ${item.current_status}` : '状态未知' }}
                  <text v-if="item.assigned_to_name"> · 原推荐 {{ item.assigned_to_name }}</text>
                </text>
              </view>
              <text class="batch-result-reason">{{ item.reason }}</text>
            </view>
            <view class="batch-result-actions">
              <button
                v-if="item.retryable"
                class="batch-mini-btn"
                :loading="batchDispatchApplying"
                @click="retryBatchFailedItems(item.ticket_id)"
              >重试</button>
              <button
                v-if="item.manual_review_recommended"
                class="batch-mini-btn accent"
                @click="reviewBatchFailedItem(item.ticket_id)"
              >人工复核</button>
            </view>
          </view>
        </view>

        <scroll-view scroll-y class="dispatch-list">
          <view v-if="batchPreviewLoading" class="dispatch-empty">
            正在生成推荐，请稍候...
          </view>

          <template v-else>
            <view
              v-for="item in batchDispatchPanel.preview?.recommendations || []"
              :key="item.ticket_id"
              class="candidate-card batch-card"
            >
              <view class="candidate-top">
                <view>
                  <text class="candidate-name">{{ item.ticket_id }}</text>
                  <text class="candidate-meta">{{ item.building_id }} · {{ item.priority === 'high' ? '高优先' : item.priority }}</text>
                </view>
                <view class="score-pill">
                  <text class="score-label">差值</text>
                  <text class="score-value">{{ item.score_gap ?? '--' }}</text>
                </view>
              </view>

              <view class="extra-row">
                <text class="extra-label">推荐人员</text>
                <text class="extra-value">
                  {{ item.chosen_candidate?.username || '暂无' }}
                  <text v-if="item.chosen_candidate?.team_name"> · {{ item.chosen_candidate?.team_name }}</text>
                </text>
              </view>
              <view class="extra-row">
                <text class="extra-label">需求技能</text>
                <text class="extra-value">
                  {{ (item.requirement?.required_skills || []).map(requirementSkillText).join(' / ') || '基础巡检' }}
                </text>
              </view>
              <view class="extra-row" v-if="item.chosen_candidate">
                <text class="extra-label">推荐分</text>
                <text class="extra-value">
                  {{ item.chosen_candidate.score }}
                  <text class="muted-text"> · 负载 {{ item.chosen_candidate.current_active_orders }}/{{ item.chosen_candidate.max_active_orders }}</text>
                </text>
              </view>
              <text class="candidate-reason">{{ item.selection_reason }}</text>
            </view>

            <view
              v-if="!batchDispatchPanel.preview?.recommendations?.length && batchDispatchPanel.preview"
              class="dispatch-empty"
            >
              当前规则下没有可直接批量派工的工单
            </view>

            <view
              v-if="batchDispatchPanel.preview?.skipped_summary?.length"
              class="batch-skipped-box"
            >
              <text class="section-title section-title--small">未纳入批量派工的原因</text>
              <view
                v-for="item in batchDispatchPanel.preview?.skipped_summary || []"
                :key="item.reason"
                class="batch-skipped-row"
              >
                <text class="batch-skipped-label">{{ item.label }}</text>
                <text class="batch-skipped-count">{{ item.count }}</text>
              </view>
            </view>

            <view
              v-if="batchDispatchPanel.preview?.skipped_examples?.length"
              class="batch-skipped-box batch-skipped-example-box"
            >
              <text class="section-title section-title--small">暂未纳入示例</text>
              <view
                v-for="item in batchDispatchPanel.preview?.skipped_examples || []"
                :key="`${item.ticket_id}_${item.reason}`"
                class="batch-skip-example-row"
              >
                <view class="batch-skip-example-top">
                  <view>
                    <text class="batch-skip-ticket">{{ item.ticket_id }}</text>
                    <text class="batch-skip-meta">{{ item.building_id }} · {{ priorityText(item.priority) }}</text>
                  </view>
                  <text class="batch-skip-reason">{{ item.label }}</text>
                </view>
                <text class="batch-skip-detail">
                  {{ item.top_candidate ? `第一候选 ${item.top_candidate.username} · ${item.top_candidate.score} 分 · 负载 ${item.top_candidate.current_active_orders}/${item.top_candidate.max_active_orders}` : '暂无可用候选人' }}
                </text>
              </view>
            </view>
          </template>
        </scroll-view>

        <button
          class="dispatch-submit batch-submit"
          :disabled="!batchDispatchPanel.preview?.recommendations?.length"
          :loading="batchDispatchApplying"
          @click="confirmBatchDispatch"
        >一键派工 {{ batchDispatchPanel.preview?.recommendations?.length || 0 }} 张</button>
      </view>
    </view>

    <TabBar :tabs="OPERATOR_TABS" current="workorders" theme="operator" />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import IncidentReviewCard from '../../../components/IncidentReviewCard.vue'
import { useRouteGuard } from '../../../utils/route-guard'
import { OPERATOR_TABS } from '../../../constants/tabs'
import { OPERATOR_ROLES } from '../../../constants/roles'
import type { AdminAction } from '../../../constants/status'
import {
  workOrderApi,
  type BatchDispatchApplyResponse,
  type BatchDispatchPreviewResponse,
  type DispatchCandidate,
  type DispatchHallApplication,
  type DispatchHallEntry,
  type DispatchRequirement,
} from '../../../api/workorder'
import { incidentApi, type Incident } from '../../../api/incident'
import { getCache, setCache } from '../../../utils/cache'
import { getDispatchSortScore, getDispatchSummaryStats, resolveExecutionStatus } from '../../../utils/incident-card'
import { formatDateTime } from '../../../utils/format'
import { formatBuildingLabel, formatDeviceLabel, sanitizeDisplayText } from '../../../utils/display'

useRouteGuard(OPERATOR_ROLES)

type OperatorAction = AdminAction | 'dispatch' | 'reassign'
type IncidentCardAction = 'trend' | 'contact' | 'nudge' | 'detail' | 'suggest_reassign'
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
interface BatchDispatchPanelState {
  visible: boolean
  preview: BatchDispatchPreviewResponse | null
  result: BatchDispatchApplyResponse | null
}
type DispatchExecutionFilter = 'all' | 'pending_accept' | 'accepted' | 'processing' | 'waiting_support' | 'overdue'
type PendingPriorityFilter = 'all' | 'high' | 'medium' | 'low'
interface BatchDispatchOptionsState {
  sampleSize: number
  priority: PendingPriorityFilter
  maxPerWorker: number
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
  { label: '工单大厅',   value: 'shared_hall', count: 0 },
])

const activeTab = ref('pending_dispatch')
const incidents = ref<Incident[]>([])
const hallEntries = ref<DispatchHallEntry[]>([])
const loading = ref(false)
const noMore = ref(false)
const dispatchExecutionFilter = ref<DispatchExecutionFilter>('all')
const pendingPriorityFilter = ref<PendingPriorityFilter>('all')
const pendingBuildingFilter = ref('all')
const actionLoading = ref<string | null>(null)
const dispatchSubmitting = ref<string | null>(null)
const batchPreviewLoading = ref(false)
const batchDispatchApplying = ref(false)
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
const hallEntryFocusId = ref('')
const batchDispatchPanel = ref<BatchDispatchPanelState>({
  visible: false,
  preview: null,
  result: null,
})
const pendingFocus = ref<{ ticketId: string; action: 'dispatch' | 'reassign' } | null>(null)
const batchDispatchOptions = ref<BatchDispatchOptionsState>({
  sampleSize: 10,
  priority: 'all',
  maxPerWorker: 2,
})
const batchSampleOptions = [5, 10, 15]
const batchWorkerCapOptions = [1, 2, 3]
const batchPriorityOptions: Array<{ label: string; value: PendingPriorityFilter }> = [
  { label: '全部', value: 'all' },
  { label: '高优先', value: 'high' },
  { label: '中优先', value: 'medium' },
  { label: '低优先', value: 'low' },
]

function priorityText(priority?: string) {
  const map: Record<string, string> = {
    high: '高优先',
    medium: '中优先',
    low: '低优先',
  }
  return map[priority || ''] || '中优先'
}

const emptyText = computed(() => {
  if (activeTab.value === 'shared_hall') {
    return '暂无待处理工单大厅事项'
  }
  if (activeTab.value === 'dispatched' && dispatchExecutionFilter.value !== 'all') {
    return '当前执行跟踪筛选下暂无工单'
  }
  if (
    activeTab.value === 'pending_dispatch'
    && (pendingPriorityFilter.value !== 'all' || pendingBuildingFilter.value !== 'all')
  ) {
    return '当前筛选下暂无待派工工单'
  }
  const map: Record<string, string> = {
    pending_review: '暂无待审阅事件',
    pending_dispatch: '暂无待派工工单',
    auto_rejected: '暂无AI已驳回工单',
    dispatched: '暂无已派单工单',
  }
  return map[activeTab.value] ?? '暂无工单'
})
const activeTabScrollId = computed(() => {
  const index = switchTabs.value.findIndex(tab => tab.value === activeTab.value)
  return index >= 0 ? `operator-tab-${index}` : ''
})

const activeTabLabel = computed(() => {
  return switchTabs.value.find(tab => tab.value === activeTab.value)?.label || '事件列表'
})

const currentTabCount = computed(() => {
  return switchTabs.value.find(tab => tab.value === activeTab.value)?.count || (activeTab.value === 'shared_hall' ? hallEntries.value.length : incidents.value.length)
})
const showEmptySkeleton = computed(() => activeTab.value === 'shared_hall' ? hallEntries.value.length === 0 : incidents.value.length === 0)
const showEmptyState = computed(() => activeTab.value === 'shared_hall' ? hallEntries.value.length === 0 : visibleIncidents.value.length === 0)
const pendingHighPriorityCount = computed(() => incidents.value.filter(item => item.priority === 'high').length)
const pendingBuildingCount = computed(() => new Set(incidents.value.map(item => item.building_id).filter(Boolean)).size)
const pendingPriorityFilters = computed(() => {
  const defs: Array<{ label: string; value: PendingPriorityFilter }> = [
    { label: '全部优先级', value: 'all' },
    { label: '高优先', value: 'high' },
    { label: '中优先', value: 'medium' },
    { label: '低优先', value: 'low' },
  ]
  return defs.map(item => ({
    ...item,
    count: item.value === 'all'
      ? incidents.value.length
      : incidents.value.filter(incident => (incident.priority || 'medium') === item.value).length,
  }))
})
const pendingBuildingFilters = computed(() => {
  const counts = new Map<string, number>()
  incidents.value.forEach((incident) => {
    const key = (incident.building_id || '').trim()
    if (!key) return
    counts.set(key, (counts.get(key) || 0) + 1)
  })
  const rows = Array.from(counts.entries())
    .sort((a, b) => (b[1] - a[1]) || a[0].localeCompare(b[0]))
    .slice(0, 6)
    .map(([value, count]) => ({
      value,
      count,
      label: value.length > 14 ? `${value.slice(0, 14)}...` : value,
    }))
  return [{ value: 'all', count: incidents.value.length, label: '全部楼宇' }, ...rows]
})
const batchWorkerLoads = computed(() => {
  return (batchDispatchPanel.value.preview?.worker_loads || [])
    .filter(item => item.planned_count > 0 || item.current_active_orders > 0)
    .slice(0, 8)
})
const retryableBatchFailures = computed(() => {
  return (batchDispatchPanel.value.result?.failed || []).filter(item => item.retryable)
})
const hallPendingApplicationCount = computed(() => hallEntries.value.reduce((sum, entry) => sum + hallPendingApplications(entry).length, 0))
const hallEntryCount = computed(() => hallEntries.value.length)
const hallSupportCount = computed(() => hallEntries.value.filter(item => item.entry_type === 'support_request').length)
const hallTakeoverCount = computed(() => hallEntries.value.filter(item => item.entry_type === 'takeover_candidate').length)

function matchesDispatchExecutionFilter(incident: Incident, filter: DispatchExecutionFilter) {
  if (filter === 'all') return true
  const status = resolveExecutionStatus(incident)
  if (filter === 'accepted') return status === 'accepted' || status === 'arrived'
  return status === filter
}

function matchesPendingFilters(incident: Incident) {
  if (pendingPriorityFilter.value !== 'all' && (incident.priority || 'medium') !== pendingPriorityFilter.value) {
    return false
  }
  if (pendingBuildingFilter.value !== 'all' && incident.building_id !== pendingBuildingFilter.value) {
    return false
  }
  return true
}

const dispatchExecutionFilters = computed(() => {
  const defs: Array<{ label: string; value: DispatchExecutionFilter }> = [
    { label: '全部', value: 'all' },
    { label: '已派未接', value: 'pending_accept' },
    { label: '已接/到场', value: 'accepted' },
    { label: '处理中', value: 'processing' },
    { label: '待协同', value: 'waiting_support' },
    { label: '超时', value: 'overdue' },
  ]
  return defs.map(item => ({
    ...item,
    count: item.value === 'all'
      ? incidents.value.length
      : incidents.value.filter(incident => matchesDispatchExecutionFilter(incident, item.value)).length,
  }))
})

const visibleIncidents = computed(() => {
  if (activeTab.value === 'dispatched') {
    return incidents.value
      .filter(incident => matchesDispatchExecutionFilter(incident, dispatchExecutionFilter.value))
      .sort((a, b) => getDispatchSortScore(b) - getDispatchSortScore(a))
  }
  if (activeTab.value === 'pending_dispatch') {
    return incidents.value.filter(matchesPendingFilters)
  }
  return incidents.value
})

const dispatchStats = computed(() => getDispatchSummaryStats(visibleIncidents.value))

const sectionNote = computed(() => {
  if (activeTab.value === 'shared_hall') {
    return `当前共有 ${hallEntryCount.value} 条共享事项，待处理申请 ${hallPendingApplicationCount.value} 条`
  }
  if (activeTab.value === 'dispatched') {
    if (dispatchExecutionFilter.value !== 'all') {
      return `共 ${currentTabCount.value} 条事件，当前筛选显示 ${visibleIncidents.value.length} 条，按超时风险与处理优先级排序`
    }
    return `共 ${currentTabCount.value} 条事件，按超时风险与处理优先级排序`
  }
  if (activeTab.value === 'pending_dispatch' && (pendingPriorityFilter.value !== 'all' || pendingBuildingFilter.value !== 'all')) {
    return `共 ${currentTabCount.value} 条待派工工单，当前筛选显示 ${visibleIncidents.value.length} 条`
  }
  return `共 ${currentTabCount.value} 条事件，按最近异常时间倒序展示`
})

async function loadData() {
  const cacheKey = `workorders_${activeTab.value}`
  if (activeTab.value === 'shared_hall') {
    const cached = getCache<DispatchHallEntry[]>(cacheKey)
    if (cached) hallEntries.value = cached
    loading.value = !cached
    page.value = 1
    noMore.value = true
    try {
      const res = await workOrderApi.listDispatchHallEntries({
        status: 'open',
        entry_type: 'support_request,takeover_candidate',
        include_applications: true,
        page: 1,
        page_size: 50,
      })
      hallEntries.value = res.hall_entries
        .sort((a, b) => {
          if (hallEntryFocusId.value) {
            if (a.id === hallEntryFocusId.value) return -1
            if (b.id === hallEntryFocusId.value) return 1
          }
          const aCount = hallPendingApplications(a).length
          const bCount = hallPendingApplications(b).length
          if (bCount !== aCount) return bCount - aCount
          if (a.entry_type !== b.entry_type) return a.entry_type === 'takeover_candidate' ? -1 : 1
          return (b.created_at || '').localeCompare(a.created_at || '')
        })
      setCache(cacheKey, hallEntries.value)
      await loadCounts()
    } catch { /* handled */ }
    finally { loading.value = false }
    return
  }

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
    if (activeTab.value === 'pending_dispatch') {
      const buildingKeys = new Set(res.incidents.map(item => item.building_id).filter(Boolean))
      if (pendingBuildingFilter.value !== 'all' && !buildingKeys.has(pendingBuildingFilter.value)) {
        pendingBuildingFilter.value = 'all'
      }
    }
    setCache(cacheKey, res.incidents)
    if (res.incidents.length < PAGE_SIZE) noMore.value = true
    await loadCounts()
    await maybeHandlePendingFocus()
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
  try {
    const hallRes = await workOrderApi.listDispatchHallEntries({
      status: 'open',
      entry_type: 'support_request,takeover_candidate',
      include_applications: true,
      page: 1,
      page_size: 50,
    })
    switchTabs.value[5].count = hallRes.hall_entries.length
  } catch {
    switchTabs.value[5].count = hallEntryCount.value
  }
}

async function loadMore() {
  if (activeTab.value === 'shared_hall') return
  if (loading.value || noMore.value) return
  page.value++
  try {
    const res = await incidentApi.list({ workflow_status: activeTab.value, page: page.value, page_size: PAGE_SIZE })
    incidents.value.push(...res.incidents)
    if (res.incidents.length < PAGE_SIZE) noMore.value = true
  } catch { page.value-- }
}

function onSwitchTab(val: string) {
  activeTab.value = val
  if (val !== 'dispatched') {
    dispatchExecutionFilter.value = 'all'
  }
  loadData()
}

function formatTabCount(count: number) {
  return count > 99 ? '99+' : String(count)
}

function hallPendingApplications(entry: DispatchHallEntry) {
  return entry.applications.filter(item => item.status === 'pending')
}

function hallEntryTypeLabel(entry: DispatchHallEntry) {
  return entry.entry_type === 'support_request' ? '共享协同' : '待接管'
}

function hallEntryTitle(entry: DispatchHallEntry) {
  return sanitizeDisplayText(entry.support_reason || entry.reason || entry.work_order?.issue_description) || '共享工单待处理'
}

function hallEntryBuilding(entry: DispatchHallEntry) {
  return formatBuildingLabel(entry.work_order?.building_id)
}

function hallEntryLocation(entry: DispatchHallEntry) {
  return formatDeviceLabel(entry.work_order?.device_id, entry.work_order?.building_id) || '现场待确认'
}

function hallEntryOwner(entry: DispatchHallEntry) {
  return entry.source_dispatch?.assigned_to_name || '主责任人待确认'
}

function hallEntryReason(entry: DispatchHallEntry) {
  if (entry.entry_type === 'takeover_candidate') {
    return sanitizeDisplayText(entry.reason || entry.work_order?.dispatch_blocked_reason) || '当前派工已超时，等待接管确认'
  }
  return sanitizeDisplayText(entry.support_reason || entry.reason) || '主责任人申请协同支援'
}

function applicationTypeLabel(application: DispatchHallApplication) {
  return application.application_type === 'takeover' ? '申请接管' : '申请协同'
}

function hallEmptyHint(entry: DispatchHallEntry) {
  if (entry.entry_type === 'takeover_candidate') {
    return '当前没有接管申请，系统已开放待接管，可先查看改派建议或催办责任人。'
  }
  return '当前没有待处理申请，可先查看详情或关闭共享事项。'
}

function canSuggestHallTakeover(entry: DispatchHallEntry) {
  return entry.entry_type === 'takeover_candidate' && Boolean(entry.work_order?.ticket_id && entry.source_dispatch?.id)
}

function canNudgeHallOwner(entry: DispatchHallEntry) {
  return Boolean(entry.source_dispatch?.id)
}

function buildHallActionKey(
  entryId: string,
  applicationId: string,
  action: 'approve' | 'reject' | 'close' | 'suggest' | 'nudge',
) {
  return `hall_${entryId}_${applicationId || 'entry'}_${action}`
}

async function approveHallApplication(entry: DispatchHallEntry, application: DispatchHallApplication) {
  const key = buildHallActionKey(entry.id, application.id, 'approve')
  actionLoading.value = key
  try {
    if (entry.entry_type === 'support_request') {
      await workOrderApi.assignDispatchHallSupport(
        entry.id,
        application.applicant_user_id,
        application.id,
        application.note || '共享大厅协同申请已同意',
      )
      uni.showToast({ title: `已指派协同给${application.applicant_username || '维修人员'}`, icon: 'success' })
    } else {
      await workOrderApi.assignDispatchHallTakeover(
        entry.id,
        application.applicant_user_id,
        `共享大厅接管申请通过：${application.note || application.applicant_username || '维修人员'}`,
        application.id,
      )
      uni.showToast({ title: `已将工单改派给${application.applicant_username || '维修人员'}`, icon: 'success' })
    }
    await loadData()
    await loadCounts()
  } catch {
    uni.showToast({ title: '处理申请失败', icon: 'none' })
  } finally {
    actionLoading.value = null
  }
}

async function rejectHallApplication(entry: DispatchHallEntry, application: DispatchHallApplication) {
  const key = buildHallActionKey(entry.id, application.id, 'reject')
  actionLoading.value = key
  try {
    const rejectNote = await pickHallRejectNote(application)
    if (!rejectNote) {
      actionLoading.value = null
      return
    }
    await workOrderApi.rejectDispatchHallApplication(
      application.id,
      rejectNote,
    )
    uni.showToast({ title: '已驳回申请', icon: 'success' })
    await loadData()
    await loadCounts()
  } catch {
    uni.showToast({ title: '驳回失败', icon: 'none' })
  } finally {
    actionLoading.value = null
  }
}

function pickHallRejectNote(application: DispatchHallApplication): Promise<string | null> {
  return new Promise((resolve) => {
    const applicantName = application.applicant_username || '该维修人员'
    const itemList = [
      `${applicantName}当前不纳入本次处理`,
      '当前已有更合适的处理人选',
      '当前技能或班组匹配度不足',
    ]
    uni.showActionSheet({
      itemList,
      success(res) {
        resolve(itemList[res.tapIndex] || null)
      },
      fail() {
        resolve(null)
      },
    })
  })
}

async function closeHallEntry(entry: DispatchHallEntry) {
  const key = buildHallActionKey(entry.id, '', 'close')
  actionLoading.value = key
  try {
    await workOrderApi.closeDispatchHallEntry(entry.id, '当前共享事项已结束')
    uni.showToast({ title: '共享事项已关闭', icon: 'success' })
    hallEntries.value = hallEntries.value.filter(item => item.id !== entry.id)
    await loadCounts()
  } catch {
    uni.showToast({ title: '关闭失败', icon: 'none' })
  } finally {
    actionLoading.value = null
  }
}

async function openHallReassignSuggestion(entry: DispatchHallEntry) {
  const key = buildHallActionKey(entry.id, '', 'suggest')
  if (!entry.work_order?.ticket_id || !entry.source_dispatch?.id) {
    uni.showToast({ title: '当前共享事项缺少改派信息', icon: 'none' })
    return
  }
  actionLoading.value = key
  try {
    const result = await workOrderApi.dispatchCandidates(entry.work_order.ticket_id)
    dispatchPanel.value = {
      visible: true,
      ticketId: entry.work_order.ticket_id,
      incidentId: entry.incident_id || null,
      dispatchId: entry.source_dispatch.id,
      mode: 'reassign',
      requirement: result.requirement,
      candidates: result.candidates,
    }
    if (!dispatchPanel.value.candidates.length) {
      uni.showToast({ title: '暂无改派候选人', icon: 'none' })
      closeDispatchPanel()
    }
  } catch {
    uni.showToast({ title: '改派候选人加载失败', icon: 'none' })
  } finally {
    actionLoading.value = null
  }
}

async function nudgeHallOwner(entry: DispatchHallEntry) {
  const key = buildHallActionKey(entry.id, '', 'nudge')
  if (!entry.source_dispatch?.id) {
    uni.showToast({ title: '当前责任人不存在', icon: 'none' })
    return
  }
  actionLoading.value = key
  try {
    const stageLabel = entry.entry_type === 'takeover_candidate' ? '当前工单已超时' : '当前工单正在等待协同'
    await workOrderApi.nudgeDispatchTask(
      entry.source_dispatch.id,
      `${stageLabel}，请尽快同步最新处理进展并反馈是否需要改派`,
    )
    uni.showToast({ title: '已催办责任人', icon: 'success' })
    await loadData()
    await loadCounts()
  } catch {
    uni.showToast({ title: '催办失败', icon: 'none' })
  } finally {
    actionLoading.value = null
  }
}

function openHallDetail(entry: DispatchHallEntry) {
  const ticketId = entry.work_order?.ticket_id
  if (!ticketId) return
  uni.navigateTo({
    url: `/pages/worker/workorder-detail/index?hall_entry_id=${entry.id}&incident_id=${entry.incident_id || ''}&ticket_id=${ticketId}&readonly=1`,
  })
}

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

function closeBatchDispatchPanel() {
  if (batchDispatchApplying.value) return
  batchDispatchPanel.value = {
    visible: false,
    preview: null,
    result: null,
  }
}

async function openBatchDispatchPanel() {
  batchDispatchPanel.value = {
    visible: true,
    preview: null,
    result: null,
  }
  await refreshBatchDispatchPreview()
}

async function refreshBatchDispatchPreview() {
  batchPreviewLoading.value = true
  try {
    const preview = await workOrderApi.batchDispatchPreview({
      sample_size: batchDispatchOptions.value.sampleSize,
      scan_limit: Math.max(batchDispatchOptions.value.sampleSize * 4, batchDispatchOptions.value.sampleSize),
      min_score: 100,
      min_gap: 10,
      priority: batchDispatchOptions.value.priority === 'all' ? undefined : batchDispatchOptions.value.priority,
      max_per_worker: batchDispatchOptions.value.maxPerWorker,
    })
    batchDispatchPanel.value = {
      ...batchDispatchPanel.value,
      visible: true,
      preview,
      result: null,
    }
  } catch {
    closeBatchDispatchPanel()
  } finally {
    batchPreviewLoading.value = false
  }
}

async function selectBatchSampleSize(size: number) {
  if (batchDispatchOptions.value.sampleSize === size) return
  batchDispatchOptions.value.sampleSize = size
  if (batchDispatchPanel.value.visible) {
    await refreshBatchDispatchPreview()
  }
}

async function selectBatchPriority(priority: PendingPriorityFilter) {
  if (batchDispatchOptions.value.priority === priority) return
  batchDispatchOptions.value.priority = priority
  if (batchDispatchPanel.value.visible) {
    await refreshBatchDispatchPreview()
  }
}

async function selectBatchWorkerCap(count: number) {
  if (batchDispatchOptions.value.maxPerWorker === count) return
  batchDispatchOptions.value.maxPerWorker = count
  if (batchDispatchPanel.value.visible) {
    await refreshBatchDispatchPreview()
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

function buildNudgeMessage(incident: Incident) {
  const executionStatus = resolveExecutionStatus(incident)
  if (executionStatus === 'pending_accept') return '工单已派发，请尽快接单并同步到场时间'
  if (executionStatus === 'waiting_support') return '当前工单处于待协同状态，请尽快同步协同进展'
  if (executionStatus === 'overdue') return '当前工单已超时，请立即处理并回传最新进展'
  return '请尽快跟进当前工单，并同步处理进度'
}

async function maybeHandlePendingFocus() {
  if (!pendingFocus.value) return
  const target = incidents.value.find(item => item.current_work_order?.ticket_id === pendingFocus.value?.ticketId)
  if (!target || !target.current_work_order?.ticket_id) return
  const focus = pendingFocus.value
  pendingFocus.value = null
  try {
    await openDispatchPanel(target, target.current_work_order.ticket_id, focus.action)
    if (!dispatchPanel.value.candidates.length) {
      uni.showToast({ title: focus.action === 'reassign' ? '暂无改派候选人' : '暂无可派工维修人员', icon: 'none' })
      closeDispatchPanel()
    }
  } catch {
    uni.showToast({ title: '候选人加载失败', icon: 'none' })
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
    dispatchSubmitting.value = null
    closeDispatchPanel()
    if (activeTab.value === 'shared_hall') {
      await loadData()
    } else {
      incidents.value = incidents.value.filter(item => item.id !== dispatchPanel.value.incidentId)
    }
    await loadCounts()
  } catch {
    uni.showToast({ title: '派工失败', icon: 'none' })
  } finally {
    dispatchSubmitting.value = null
  }
}

async function confirmBatchDispatch() {
  const recommendations = batchDispatchPanel.value.preview?.recommendations || []
  if (!recommendations.length) return
  batchDispatchApplying.value = true
  try {
    const response = await workOrderApi.batchDispatch(
      recommendations
        .filter(item => item.chosen_candidate?.user_id)
        .map(item => ({
          ticket_id: item.ticket_id,
          assigned_to: item.chosen_candidate!.user_id,
          dispatch_mode: 'assisted',
          selection_reason: item.selection_reason,
        })),
    )
    await loadData()
    await loadCounts()
    await refreshBatchDispatchPreview()
    batchDispatchPanel.value = {
      ...batchDispatchPanel.value,
      visible: true,
      result: response,
    }

    const summary = [
      `成功派工 ${response.dispatched_count} 张`,
      response.failed_count ? `失败 ${response.failed_count} 张` : '',
    ].filter(Boolean).join('，')

    if (response.failed_count) {
      uni.showToast({ title: '部分派工成功，请处理失败项', icon: 'none' })
      return
    }

    closeBatchDispatchPanel()
    uni.showToast({ title: summary, icon: 'success' })
  } catch {
    uni.showToast({ title: '批量派工失败', icon: 'none' })
  } finally {
    batchDispatchApplying.value = false
  }
}

async function retryBatchFailedItems(ticketId?: string) {
  const items = (ticketId
    ? retryableBatchFailures.value.filter(item => item.ticket_id === ticketId)
    : retryableBatchFailures.value
  )
  if (!items.length) {
    uni.showToast({ title: '当前没有可直接重试的失败项', icon: 'none' })
    return
  }
  batchDispatchApplying.value = true
  try {
    const response = await workOrderApi.batchDispatch(
      items.map(item => ({
        ticket_id: item.ticket_id,
        assigned_to: item.assigned_to,
        dispatch_mode: item.dispatch_mode || 'assisted',
        selection_reason: item.selection_reason || item.reason,
      })),
    )
    await loadData()
    await loadCounts()
    await refreshBatchDispatchPreview()
    batchDispatchPanel.value = {
      ...batchDispatchPanel.value,
      visible: true,
      result: response,
    }
    const summary = [
      `重试成功 ${response.dispatched_count} 张`,
      response.failed_count ? `仍失败 ${response.failed_count} 张` : '',
    ].filter(Boolean).join('，')
    if (response.failed_count) {
      uni.showToast({ title: summary, icon: 'none' })
      return
    }
    closeBatchDispatchPanel()
    uni.showToast({ title: summary, icon: 'success' })
  } catch {
    uni.showToast({ title: '失败项重试失败', icon: 'none' })
  } finally {
    batchDispatchApplying.value = false
  }
}

async function reviewBatchFailedItem(ticketId: string) {
  let target = incidents.value.find(item => item.current_work_order?.ticket_id === ticketId)
  if (!target) {
    await loadData()
    target = incidents.value.find(item => item.current_work_order?.ticket_id === ticketId)
  }
  if (!target || !target.current_work_order?.ticket_id) {
    uni.showToast({ title: '当前工单已不在待派工列表', icon: 'none' })
    return
  }
  closeBatchDispatchPanel()
  try {
    await openDispatchPanel(target, target.current_work_order.ticket_id, 'dispatch')
    if (!dispatchPanel.value.candidates.length) {
      uni.showToast({ title: '暂无可派工维修人员', icon: 'none' })
      closeDispatchPanel()
    }
  } catch {
    uni.showToast({ title: '候选人加载失败', icon: 'none' })
  }
}

function openDetail(incident: Incident) {
  const ticketId = incident.current_work_order?.ticket_id
  if (!ticketId) return
  uni.navigateTo({ url: `/pages/worker/workorder-detail/index?incident_id=${incident.incident_id}&ticket_id=${ticketId}&readonly=1` })
}

async function handleCardAction(payload: { type: IncidentCardAction; incident: Incident }) {
  const { type, incident } = payload
  if (type === 'trend' || type === 'detail') {
    openDetail(incident)
    return
  }

  if (type === 'contact') {
    const phone = incident.current_dispatch?.assigned_phone || incident.current_work_order?.assigned_phone
    if (!phone) {
      uni.showToast({ title: '暂无责任人联系方式', icon: 'none' })
      return
    }
    uni.makePhoneCall({ phoneNumber: phone })
    return
  }

  if (type === 'nudge') {
    if (!incident.current_dispatch?.id) {
      uni.showToast({ title: '当前派工任务不存在', icon: 'none' })
      return
    }
    try {
      await workOrderApi.nudgeDispatchTask(incident.current_dispatch.id, buildNudgeMessage(incident))
      await loadData()
      await loadCounts()
      const assignee = incident.current_dispatch?.assigned_to_name || incident.current_work_order?.assigned_to_name || '责任人'
      uni.showToast({ title: `已催办${assignee}`, icon: 'success' })
    } catch {
      uni.showToast({ title: '催办失败', icon: 'none' })
    }
    return
  }

  if (type === 'suggest_reassign') {
    const ticketId = incident.current_work_order?.ticket_id
    if (!ticketId) return
    try {
      await openDispatchPanel(incident, ticketId, 'reassign')
      if (!dispatchPanel.value.candidates.length) {
        uni.showToast({ title: '暂无改派候选人', icon: 'none' })
        closeDispatchPanel()
      }
    } catch {
      uni.showToast({ title: '候选人加载失败', icon: 'none' })
    }
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

onLoad((query) => {
  if (typeof query?.active_tab === 'string' && switchTabs.value.some(tab => tab.value === query.active_tab)) {
    activeTab.value = query.active_tab
  }
  if (typeof query?.hall_entry_id === 'string') {
    hallEntryFocusId.value = query.hall_entry_id
  }
  if (typeof query?.ticket_id === 'string' && (query?.focus_action === 'dispatch' || query?.focus_action === 'reassign')) {
    pendingFocus.value = {
      ticketId: query.ticket_id,
      action: query.focus_action,
    }
  }
})

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
  padding: 16rpx;
  border-radius: 28rpx;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(245, 248, 253, 0.88));
  border: 1rpx solid rgba(225, 231, 240, 0.95);
  box-shadow: 0 12rpx 34rpx rgba(20, 32, 58, 0.08);
}

.tab-shell-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
  padding: 0 6rpx 12rpx;
}

.tab-shell-title {
  font-size: 24rpx;
  font-weight: 700;
  color: #1f2937;
}

.tab-shell-hint {
  font-size: 20rpx;
  color: #8a94a6;
}

.tab-switch-scroll {
  white-space: nowrap;
}

.tab-switch {
  display: inline-flex;
  gap: 12rpx;
  min-width: 100%;
  box-sizing: border-box;
}

.switch-item {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10rpx;
  min-width: 144rpx;
  height: 80rpx;
  padding: 0 24rpx;
  color: #6b7280;
  position: relative;
  flex-shrink: 0;
  border-radius: 22rpx;
  border: 1rpx solid rgba(214, 223, 235, 0.92);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 8rpx 18rpx rgba(15, 23, 42, 0.04);
  &.active {
    color: #ffffff;
    font-weight: 700;
    border-color: transparent;
    background: linear-gradient(135deg, #2563eb, #3b82f6);
    box-shadow: 0 14rpx 28rpx rgba(37, 99, 235, 0.22);
  }
}

.switch-label {
  font-size: 24rpx;
  font-weight: 700;
  white-space: nowrap;
}

.count-dot {
  background: rgba(37, 99, 235, 0.1);
  color: #2563eb;
  border-radius: 999rpx;
  font-size: 18rpx;
  font-weight: 700;
  line-height: 1;
  padding: 6rpx 12rpx;
  min-width: 40rpx;
  text-align: center;
  box-sizing: border-box;
}

.switch-item.active .count-dot {
  background: rgba(255, 255, 255, 0.18);
  color: #ffffff;
}

.list-area {
  flex: 1;
  min-height: 0;
  height: auto;
  box-sizing: border-box;
  padding: 22rpx 24rpx calc(env(safe-area-inset-bottom, 0px) + 140rpx);
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18rpx;
  padding: 10rpx 6rpx 18rpx;
}

.section-action-btn {
  margin: 0;
  padding: 0 24rpx;
  height: 64rpx;
  line-height: 64rpx;
  border-radius: 999rpx;
  border: none;
  background: linear-gradient(135deg, #2563eb, #3b82f6);
  color: #fff;
  font-size: 22rpx;
  font-weight: 700;
  box-shadow: 0 12rpx 24rpx rgba(37, 99, 235, 0.16);
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

.pending-batch-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12rpx;
  margin: 0 0 18rpx;
}

.track-filter-row {
  display: flex;
  gap: 12rpx;
  overflow-x: auto;
  padding: 0 0 18rpx;
  white-space: nowrap;
}

.track-filter-row--secondary {
  padding-top: 0;
}

.track-filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 10rpx;
  padding: 14rpx 18rpx;
  border-radius: 999rpx;
  background: rgba(255, 255, 255, 0.92);
  border: 1rpx solid rgba(221, 228, 238, 0.95);
  color: #66758a;
  flex-shrink: 0;

  &.active {
    background: #eef4ff;
    border-color: rgba(59, 130, 246, 0.22);
    color: #2563eb;
    box-shadow: 0 10rpx 20rpx rgba(59, 130, 246, 0.08);
  }
}

.track-filter-chip--building {
  max-width: 300rpx;
}

.track-filter-label {
  font-size: 22rpx;
  font-weight: 700;
}

.track-filter-count {
  min-width: 32rpx;
  padding: 2rpx 10rpx;
  border-radius: 999rpx;
  background: rgba(59, 130, 246, 0.12);
  font-size: 18rpx;
  text-align: center;
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

.batch-sheet {
  max-height: 82vh;
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

.batch-config-box {
  margin-top: 18rpx;
  border-radius: 24rpx;
  background: #f8fbff;
  border: 1rpx solid rgba(59, 130, 246, 0.12);
  padding: 18rpx;
}

.batch-config-group + .batch-config-group {
  margin-top: 14rpx;
}

.batch-config-label {
  display: block;
  font-size: 22rpx;
  color: #5b6576;
  margin-bottom: 10rpx;
}

.batch-config-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
}

.batch-config-chip {
  padding: 10rpx 16rpx;
  border-radius: 999rpx;
  background: #fff;
  border: 1rpx solid rgba(226, 232, 240, 0.95);
  color: #64748b;
  font-size: 20rpx;
  font-weight: 700;

  &.active {
    color: #2563eb;
    border-color: rgba(59, 130, 246, 0.22);
    background: #eef4ff;
  }
}

.batch-refresh-btn {
  margin-top: 18rpx;
  height: 64rpx;
  line-height: 64rpx;
  border: none;
  border-radius: 18rpx;
  background: #e8f1ff;
  color: #2563eb;
  font-size: 22rpx;
  font-weight: 700;
}

.batch-planned-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
  margin-top: 16rpx;
}

.batch-planned-pill {
  display: inline-flex;
  align-items: center;
  gap: 10rpx;
  padding: 10rpx 14rpx;
  border-radius: 999rpx;
  background: #eefcf7;
  color: #18794e;
  font-size: 20rpx;
}

.batch-planned-name {
  font-weight: 700;
}

.batch-planned-count {
  color: #2563eb;
  font-weight: 700;
}

.batch-load-box {
  margin-top: 14rpx;
  border-radius: 22rpx;
  background: #f8fafc;
  border: 1rpx solid rgba(226, 232, 240, 0.95);
  padding: 18rpx;
}

.batch-load-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
  padding: 14rpx 0;
  border-bottom: 1rpx solid rgba(226, 232, 240, 0.76);

  &:last-child {
    border-bottom: none;
    padding-bottom: 0;
  }
}

.batch-load-name {
  display: block;
  font-size: 24rpx;
  font-weight: 800;
  color: #172033;
}

.batch-load-meta {
  display: block;
  margin-top: 6rpx;
  font-size: 20rpx;
  color: #7b8797;
}

.batch-load-values {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6rpx;
}

.batch-load-stat {
  font-size: 20rpx;
  color: #526071;

  &.accent {
    color: #2563eb;
    font-weight: 700;
  }
}

.batch-result-box {
  margin-top: 14rpx;
  border-radius: 22rpx;
  background: #fffaf5;
  border: 1rpx solid #f3d8b2;
  padding: 18rpx;
}

.batch-result-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16rpx;
}

.batch-result-note {
  display: block;
  margin-top: 6rpx;
  font-size: 20rpx;
  color: #7b8797;
}

.batch-result-retry {
  margin: 0;
  height: 58rpx;
  line-height: 58rpx;
  padding: 0 20rpx;
  border-radius: 999rpx;
  border: none;
  background: #fff;
  color: #d97706;
  font-size: 20rpx;
  font-weight: 700;
}

.batch-result-row + .batch-result-row {
  margin-top: 14rpx;
  padding-top: 14rpx;
  border-top: 1rpx solid rgba(243, 216, 178, 0.7);
}

.batch-result-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16rpx;
}

.batch-result-reason {
  flex-shrink: 0;
  font-size: 20rpx;
  line-height: 1.5;
  color: #b45309;
  font-weight: 700;
  text-align: right;
}

.batch-result-actions {
  display: flex;
  gap: 12rpx;
  margin-top: 12rpx;
}

.batch-mini-btn {
  margin: 0;
  height: 56rpx;
  line-height: 56rpx;
  padding: 0 20rpx;
  border-radius: 16rpx;
  border: none;
  background: #fff;
  color: #b45309;
  font-size: 20rpx;
  font-weight: 700;

  &.accent {
    background: #eef4ff;
    color: #2563eb;
  }
}

.candidate-card {
  border-radius: 26rpx;
  border: 1rpx solid rgba(226, 232, 240, 0.95);
  padding: 20rpx;
  margin-bottom: 16rpx;
  background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
}

.batch-card {
  border-color: rgba(59, 130, 246, 0.12);
  background:
    radial-gradient(circle at top right, rgba(59, 130, 246, 0.05), transparent 24%),
    linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
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

.muted-text {
  color: #7b8797;
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

.batch-skipped-box {
  margin-top: 12rpx;
  border-radius: 22rpx;
  background: #f8fafc;
  border: 1rpx solid rgba(226, 232, 240, 0.95);
  padding: 18rpx;
}

.section-title--small {
  font-size: 24rpx;
  margin-bottom: 10rpx;
}

.batch-skipped-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
  padding: 10rpx 0;
  font-size: 22rpx;
  color: #526071;
}

.batch-skipped-count {
  color: #1f2937;
  font-weight: 700;
}

.batch-skipped-example-box {
  margin-top: 14rpx;
}

.batch-skip-example-row + .batch-skip-example-row {
  margin-top: 16rpx;
  padding-top: 16rpx;
  border-top: 1rpx solid rgba(226, 232, 240, 0.88);
}

.batch-skip-example-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16rpx;
}

.batch-skip-ticket {
  display: block;
  font-size: 24rpx;
  font-weight: 800;
  color: #172033;
}

.batch-skip-meta {
  display: block;
  margin-top: 6rpx;
  font-size: 20rpx;
  color: #7b8797;
}

.batch-skip-reason {
  flex-shrink: 0;
  font-size: 20rpx;
  color: #d97706;
  font-weight: 700;
}

.batch-skip-detail {
  display: block;
  margin-top: 10rpx;
  font-size: 22rpx;
  line-height: 1.6;
  color: #4b5563;
}

.batch-submit {
  margin-top: 16rpx;
}

.hall-wrap {
  margin-bottom: 18rpx;
}

.hall-card {
  border-radius: 28rpx;
  border: 1rpx solid rgba(226, 232, 240, 0.95);
  padding: 22rpx;
  background:
    radial-gradient(circle at top right, rgba(183, 204, 118, 0.1), transparent 24%),
    linear-gradient(180deg, #ffffff 0%, #fbfcf8 100%);
  box-shadow: 0 12rpx 28rpx rgba(15, 23, 42, 0.06);
}

.hall-card-head,
.hall-badge-row,
.hall-application-top,
.hall-application-actions,
.hall-bottom-actions {
  display: flex;
  align-items: center;
}

.hall-card-head {
  justify-content: space-between;
  gap: 16rpx;
}

.hall-badge-row {
  gap: 10rpx;
  flex-wrap: wrap;
}

.hall-type-badge,
.hall-priority-badge,
.hall-application-status {
  padding: 8rpx 14rpx;
  border-radius: 999rpx;
  font-size: 20rpx;
  font-weight: 700;
}

.hall-type-badge.support {
  background: rgba(183, 204, 118, 0.2);
  color: #486533;
}

.hall-type-badge.takeover {
  background: rgba(255, 179, 163, 0.18);
  color: #cf5f45;
}

.hall-priority-badge {
  background: #f8fafc;
  color: #6b7280;
}

.hall-time {
  flex-shrink: 0;
  font-size: 20rpx;
  color: #8d97a6;
}

.hall-title {
  display: block;
  margin-top: 18rpx;
  font-size: 30rpx;
  font-weight: 800;
  color: #182235;
}

.hall-location {
  display: block;
  margin-top: 10rpx;
  font-size: 22rpx;
  color: #7b8797;
}

.hall-detail-panel {
  margin-top: 16rpx;
  border-radius: 22rpx;
  background: #f8fafc;
  padding: 18rpx;
}

.hall-detail-line {
  display: flex;
  align-items: flex-start;
  gap: 14rpx;
  margin-top: 10rpx;
}

.hall-detail-line:first-child {
  margin-top: 0;
}

.hall-detail-label {
  width: 110rpx;
  flex-shrink: 0;
  font-size: 22rpx;
  color: #7b8797;
}

.hall-detail-value {
  flex: 1;
  font-size: 22rpx;
  line-height: 1.6;
  color: #2a3445;
}

.hall-detail-value.multiline {
  white-space: pre-wrap;
}

.hall-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12rpx;
  margin-top: 18rpx;
}

.hall-section-title {
  font-size: 24rpx;
  font-weight: 800;
  color: #182235;
}

.hall-section-note {
  font-size: 20rpx;
  color: #7b8797;
}

.hall-application-list {
  margin-top: 12rpx;
}

.hall-application-card {
  padding: 18rpx;
  border-radius: 22rpx;
  background: linear-gradient(180deg, #fefefe 0%, #f7faf1 100%);
  border: 1rpx solid rgba(226, 232, 240, 0.95);
  margin-bottom: 12rpx;
}

.hall-application-top {
  justify-content: space-between;
  align-items: flex-start;
  gap: 14rpx;
}

.hall-application-name {
  display: block;
  font-size: 26rpx;
  font-weight: 800;
  color: #182235;
}

.hall-application-meta {
  display: block;
  margin-top: 6rpx;
  font-size: 20rpx;
  color: #7b8797;
}

.hall-application-status {
  background: #eef4ff;
  color: #2563eb;
}

.hall-application-note {
  display: block;
  margin-top: 12rpx;
  font-size: 22rpx;
  line-height: 1.6;
  color: #4b5563;
}

.hall-application-actions {
  gap: 12rpx;
  margin-top: 14rpx;
}

.hall-mini-btn,
.hall-secondary-btn {
  margin: 0;
  border: none;
  font-size: 22rpx;
  font-weight: 700;
}

.hall-mini-btn {
  flex: 1;
  height: 64rpx;
  line-height: 64rpx;
  border-radius: 16rpx;
}

.hall-mini-btn.approve {
  background: linear-gradient(135deg, #12b76a, #16c47f);
  color: #fff;
}

.hall-mini-btn.danger {
  background: #fff2f0;
  color: #ff4d4f;
}

.hall-application-empty {
  margin-top: 12rpx;
  padding: 22rpx 18rpx;
  border-radius: 20rpx;
  background: #f8fafc;
  color: #7b8797;
  font-size: 22rpx;
  line-height: 1.6;
}

.hall-bottom-actions {
  gap: 12rpx;
  margin-top: 16rpx;
}

.hall-secondary-btn {
  flex: 1;
  height: 68rpx;
  line-height: 68rpx;
  border-radius: 18rpx;
  background: #eef4ff;
  color: #2563eb;
}

.hall-secondary-btn.danger {
  background: #fff2f0;
  color: #ff4d4f;
}

@media (max-width: 430px) {
  .summary-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .pending-batch-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .requirement-strip {
    grid-template-columns: 1fr;
  }
}
</style>
