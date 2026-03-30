<!-- 工单卡片，运维端和维修端通用 -->
<template>
  <view class="wo-card" @click="$emit('click', order)">
    <!-- 顶部：优先级 + 状态 -->
    <view class="wo-header">
      <view class="badge" :class="order.priority">
        {{ PRIORITY_LABEL[order.priority] || order.priority }}
      </view>
      <view class="status-tag" :class="order.status">
        {{ STATUS_LABEL[order.status] || order.status }}
      </view>
    </view>

    <!-- 建筑 + 设备 -->
    <view class="wo-title-row">
      <text class="wo-building">{{ order.building_id }}</text>
      <text v-if="order.device_id" class="wo-dot">·</text>
      <text v-if="order.device_id" class="wo-type">{{ order.device_id }}</text>
    </view>

    <!-- 描述（对齐后端字段 issue_description） -->
    <text class="wo-desc">{{ order.issue_description }}</text>

    <!-- 底部：时间 + AI决策 -->
    <view class="wo-footer">
      <text class="wo-time">{{ formatRelativeTime(order.created_at) }}</text>
      <view v-if="order.ai_decision" class="ai-tag" :class="order.ai_decision">
        <text>AI {{ order.ai_decision === 'approved' ? '批准' : '驳回' }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { WorkOrder } from '../api/workorder'
import { STATUS_LABEL, PRIORITY_LABEL } from '../constants/status'
import { formatRelativeTime } from '../utils/format'

const props = defineProps<{ order: WorkOrder }>()
defineEmits<{ (e: 'click', order: WorkOrder): void }>()
</script>

<style lang="scss" scoped>
.wo-card {
  background: #fff;
  border-radius: 16rpx;
  padding: 28rpx;
  margin-bottom: 20rpx;
  box-shadow: 0 2rpx 12rpx rgba(0,0,0,0.06);
  active-opacity: 0.8;
}

.wo-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16rpx;
}

.badge {
  padding: 6rpx 16rpx;
  border-radius: 20rpx;
  font-size: 22rpx;
  font-weight: 500;

  &.high   { background: #fff2f0; color: #ff4d4f; }
  &.medium { background: #fff7e6; color: #fa8c16; }
  &.low    { background: #f6ffed; color: #52c41a; }
}

.status-tag {
  padding: 6rpx 16rpx;
  border-radius: 20rpx;
  font-size: 22rpx;

  &.pending_review          { background: #fffbe6; color: #d48806; }
  &.auto_approved           { background: #e6f7ff; color: #096dd9; }
  &.auto_rejected           { background: #fff2f0; color: #ff4d4f; }
  &.dispatched              { background: #e6f7ff; color: #096dd9; }
  &.completed               { background: #f6ffed; color: #389e0d; }
  &.closed                  { background: #f5f5f5; color: #8c8c8c; }
  &.false_alarm             { background: #f0f0f0; color: #595959; }
  &.escalated               { background: #f0f0ff; color: #722ed1; }
  &.admin_override_approved { background: #e6f7ff; color: #096dd9; }
  &.admin_override_rejected { background: #fff2f0; color: #ff4d4f; }
}

.wo-title-row {
  display: flex;
  align-items: center;
  gap: 8rpx;
  margin-bottom: 12rpx;
}

.wo-building {
  font-size: 30rpx;
  font-weight: 600;
  color: #1a1a2e;
}

.wo-dot {
  color: #ccc;
  font-size: 28rpx;
}

.wo-type {
  font-size: 26rpx;
  color: #666;
  flex: 1;
}

.wo-desc {
  font-size: 26rpx;
  color: #666;
  line-height: 1.6;
  margin-bottom: 16rpx;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.wo-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.wo-time {
  font-size: 22rpx;
  color: #aaa;
}

.ai-tag {
  padding: 4rpx 12rpx;
  border-radius: 12rpx;
  font-size: 20rpx;

  &.approved { background: #f0fff4; color: #00b96b; }
  &.rejected { background: #fff0f0; color: #ff4d4f; }
}
</style>
